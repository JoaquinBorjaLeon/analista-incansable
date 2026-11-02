"""Tests de la Fase 3 (alertas y titulares) con datos sintéticos: sin red."""

import json
import sqlite3
import unittest
from datetime import date, timedelta

import pandas as pd

from src import alertas, db, titulares


def _con():
    con = sqlite3.connect(":memory:")
    con.executescript(db.ESQUEMA)
    return con


def _precios(con, ticker, cierres, inicio=date(2025, 1, 1)):
    filas = [(ticker, (inicio + timedelta(days=i)).isoformat(), c, c, c, c, 1000)
             for i, c in enumerate(cierres)]
    db.upsert_precios(con, filas)


CONFIG = {
    "watchlist": {"ZZZ": {"zona_entrada": [18.5, 19.5], "nota_manual": "Tamaño pequeño."}},
    "alertas": {"proximidad_zona_pct": 3, "antispam_dias": 5},
}


class TestDistancia(unittest.TestCase):
    def test_dentro_encima_debajo(self):
        self.assertEqual(alertas.distancia_pct(19.0, [18.5, 19.5]), 0.0)
        self.assertAlmostEqual(alertas.distancia_pct(20.475, [18.5, 19.5]), 5.0)
        self.assertAlmostEqual(alertas.distancia_pct(17.575, [18.5, 19.5]), -5.0)


class TestAlertasDePrecio(unittest.TestCase):
    def test_entrada_en_zona(self):
        a = alertas.alertas_de_precio("ZZZ", pd.Series([25.0, 19.0]), {"zona_entrada": [18.5, 19.5]}, 3)
        self.assertEqual([x["tipo"] for x in a], ["entrada_zona"])

    def test_proximidad_y_fuera_de_rango(self):
        cerca = alertas.alertas_de_precio("ZZZ", pd.Series([25.0, 19.9]), {"zona_entrada": [18.5, 19.5]}, 3)
        self.assertEqual([x["tipo"] for x in cerca], ["proximidad"])
        lejos = alertas.alertas_de_precio("ZZZ", pd.Series([25.0, 22.0]), {"zona_entrada": [18.5, 19.5]}, 3)
        self.assertEqual(lejos, [])

    def test_cruce_sma200_al_alza_y_a_la_baja(self):
        alza = pd.Series([100.0] * 240 + [95.0] * 10 + [105.0])
        a = alertas.alertas_de_precio("ZZZ", alza, {}, 3)
        self.assertEqual(a[0]["tipo"], "cruce_media")
        self.assertEqual(a[0]["datos"]["sentido"], "al alza")

        baja = pd.Series([100.0] * 240 + [105.0] * 10 + [95.0])
        b = alertas.alertas_de_precio("ZZZ", baja, {}, 3)
        self.assertEqual(b[0]["datos"]["sentido"], "a la baja")

    def test_sin_historia_suficiente_no_hay_cruce(self):
        self.assertEqual(alertas.alertas_de_precio("ZZZ", pd.Series([100.0] * 50 + [120.0]), {}, 3), [])


class TestBanderas(unittest.TestCase):
    def test_bandera_nueva_ignora_el_valor(self):
        ayer = {"banderas": ["🚩 Dilución > 5% anual (6.1%)"]}
        hoy = {"banderas": ["🚩 Dilución > 5% anual (6.4%)", "🚩 FCF negativo (-12 M USD)"]}
        self.assertEqual(alertas.banderas_nuevas(hoy, ayer), ["🚩 FCF negativo (-12 M USD)"])

    def test_sin_score_anterior_no_avisa(self):
        self.assertEqual(alertas.banderas_nuevas({"banderas": ["🚩 FCF negativo (-1 M USD)"]}, None), [])


class TestEvaluarYAntispam(unittest.TestCase):
    def test_flujo_completo(self):
        con = _con()
        _precios(con, "ZZZ", [25.0, 24.0, 19.2])
        hoy = date(2026, 6, 10)
        falsos = [{"titulo": "Resultados trimestrales", "fuente": "Agencia", "url": "", "fecha": None}]

        primera = alertas.evaluar(con, CONFIG, hoy, obtener_titulares=lambda t, n: falsos)
        self.assertEqual([a["tipo"] for a in primera], ["entrada_zona"])
        self.assertEqual(primera[0]["titulares"], falsos)
        self.assertEqual(primera[0]["nota_manual"], "Tamaño pequeño.")

        alertas.registrar(con, primera)
        self.assertEqual(alertas.evaluar(con, CONFIG, hoy + timedelta(days=4), obtener_titulares=lambda t, n: []), [])
        self.assertEqual(len(alertas.evaluar(con, CONFIG, hoy + timedelta(days=5), obtener_titulares=lambda t, n: [])), 1)

    def test_bandera_nueva_desde_scores(self):
        con = _con()
        _precios(con, "ZZZ", [30.0, 31.0])
        db.upsert_score(con, "ZZZ", "2026-06-09", 70, json.dumps({"banderas": []}))
        db.upsert_score(con, "ZZZ", "2026-06-10", 60, json.dumps({"banderas": ["🚩 FCF negativo (-5 M USD)"]}))
        res = alertas.evaluar(con, CONFIG, date(2026, 6, 10), obtener_titulares=lambda t, n: [])
        self.assertEqual([a["tipo"] for a in res], ["bandera_roja_nueva"])


class TestFormato(unittest.TestCase):
    def test_incluye_nota_titulares_y_aviso(self):
        texto = alertas.formatear({
            "tipo": "entrada_zona", "mensaje": "ZZZ cierra en 19.20, dentro de su zona 18.5-19.5.",
            "nota_manual": "Tamaño pequeño.",
            "titulares": [{"titulo": "Resultados trimestrales", "fuente": "Agencia"}],
        })
        self.assertIn("Nota: Tamaño pequeño.", texto)
        self.assertIn("- Resultados trimestrales (Agencia)", texto)
        self.assertIn("no es una recomendación", texto)

    def test_zona_sin_titulares_pide_revisar(self):
        texto = alertas.formatear({"tipo": "proximidad", "mensaje": "ZZZ cerca.", "titulares": []})
        self.assertIn("revisa las noticias", texto)


class _ClienteFalso:
    def __init__(self, noticias=None, error=False):
        self._noticias, self._error = noticias, error

    @property
    def news(self):
        if self._error:
            raise RuntimeError("sin red")
        return self._noticias


class TestTitulares(unittest.TestCase):
    def test_formato_nuevo_y_antiguo(self):
        noticias = [
            {"content": {"title": "Titular nuevo", "provider": {"displayName": "Fuente A"},
                         "canonicalUrl": {"url": "https://a.example"}, "pubDate": "2026-06-10"}},
            {"title": "Titular antiguo", "publisher": "Fuente B", "link": "https://b.example"},
            {"content": {}},
        ]
        res = titulares.obtener_titulares("ZZZ", 5, cliente=_ClienteFalso(noticias))
        self.assertEqual([t["titulo"] for t in res], ["Titular nuevo", "Titular antiguo"])
        self.assertEqual(res[0]["fuente"], "Fuente A")
        self.assertEqual(res[1]["url"], "https://b.example")

    def test_fallo_devuelve_lista_vacia(self):
        self.assertEqual(titulares.obtener_titulares("ZZZ", cliente=_ClienteFalso(error=True)), [])


if __name__ == "__main__":
    unittest.main()
