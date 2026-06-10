"""Tests del score (§5) con datos sintéticos — validan la lógica sin red.

Tres perfiles: empresa "verde total" (≈100), "amarilla" (≈50) y
"roja" (<30 con banderas), más la bandera manual desde config.
"""

import unittest

from src.analisis import calcular_score

CONFIG = {
    "umbrales_score": {
        "crecimiento_verde": 20,
        "crecimiento_amarillo": 10,
        "margen_bruto_verde": 50,
        "margen_bruto_amarillo": 35,
        "margen_fcf_verde": 10,
        "margen_fcf_amarillo": 5,
        "deuda_ebitda_verde": 1,
        "deuda_ebitda_amarillo": 3,
        "roe_verde": 15,
        "roe_amarillo": 8,
        "dilucion_verde": 2,
        "dilucion_amarillo": 5,
        "dilucion_maxima": 5,
        "caida_margen_bruto_pp": 3,
        "deuda_ebitda_bandera": 3,
        "deceleracion_ingresos_pp": 10,
    },
    "pesos_score": {
        "crecimiento": 20,
        "margen_bruto": 10,
        "fcf": 20,
        "margen_fcf": 10,
        "balance": 10,
        "roe": 10,
        "dilucion": 10,
        "beneficio_acompana": 10,
    },
}

VERDE_TOTAL = {
    "crecimiento_ingresos_yoy": 30.0,
    "crecimiento_ingresos_yoy_anterior": 25.0,
    "margen_bruto": 60.0,
    "margen_bruto_anterior": 58.0,
    "fcf_ttm": 120e6,
    "fcf_anterior": 100e6,
    "margen_fcf": 15.0,
    "deuda_total": 50e6,
    "caja": 200e6,          # caja neta → balance verde
    "deuda_neta_ebitda": None,
    "roe": 22.0,
    "dilucion_yoy": 1.0,
    "beneficio_neto": 50e6,
    "crecimiento_beneficio_yoy": 35.0,
}

AMARILLA = {
    "crecimiento_ingresos_yoy": 15.0,
    "crecimiento_ingresos_yoy_anterior": 20.0,
    "margen_bruto": 40.0,
    "margen_bruto_anterior": 41.0,
    "fcf_ttm": 80e6,
    "fcf_anterior": 80e6,   # positivo pero estable → amarillo
    "margen_fcf": 7.0,
    "deuda_total": 300e6,
    "caja": 100e6,
    "deuda_neta_ebitda": 2.0,
    "roe": 10.0,
    "dilucion_yoy": 3.0,
    "beneficio_neto": 20e6,
    "crecimiento_beneficio_yoy": 5.0,  # > 0 pero crece menos que ingresos
}

ROJA = {
    "crecimiento_ingresos_yoy": 2.0,
    "crecimiento_ingresos_yoy_anterior": 20.0,  # 🚩 decelera 18 p.p.
    "margen_bruto": 30.0,
    "margen_bruto_anterior": 35.0,              # 🚩 cae 5 p.p.
    "fcf_ttm": -50e6,                           # 🚩 FCF negativo
    "fcf_anterior": -20e6,
    "margen_fcf": -4.0,
    "deuda_total": 500e6,
    "caja": 50e6,
    "deuda_neta_ebitda": 4.5,                   # 🚩 > 3x
    "roe": -10.0,
    "dilucion_yoy": 12.0,                       # 🚩 > 5%
    "beneficio_neto": -30e6,
    "crecimiento_beneficio_yoy": None,
}


class TestScore(unittest.TestCase):
    def test_empresa_verde_total(self):
        r = calcular_score(VERDE_TOTAL, CONFIG)
        self.assertAlmostEqual(r["score_total"], 100)
        self.assertEqual(r["banderas"], [])
        self.assertTrue(all(c["estado"] == "verde" for c in r["desglose"]))

    def test_empresa_amarilla(self):
        r = calcular_score(AMARILLA, CONFIG)
        self.assertAlmostEqual(r["score_total"], 50)
        self.assertEqual(r["banderas"], [])
        self.assertTrue(all(c["estado"] == "amarillo" for c in r["desglose"]))

    def test_empresa_roja(self):
        r = calcular_score(ROJA, CONFIG)
        self.assertLess(r["score_total"], 30)
        self.assertGreaterEqual(len(r["banderas"]), 4)
        texto = " ".join(r["banderas"])
        self.assertIn("Dilución", texto)
        self.assertIn("FCF negativo", texto)
        self.assertIn("Margen bruto en caída", texto)
        self.assertIn("decelerando", texto)

    def test_bandera_manual(self):
        r = calcular_score(VERDE_TOTAL, CONFIG, bandera_manual="Litigio de valores")
        # la bandera manual se lista pero NO altera el score (no se promedia)
        self.assertAlmostEqual(r["score_total"], 100)
        self.assertEqual(r["banderas"], ["🚩 Manual: Litigio de valores"])

    def test_metrica_ausente_puntua_cero_y_marca_sd(self):
        metricas = dict(VERDE_TOTAL, roe=None)
        r = calcular_score(metricas, CONFIG)
        criterio_roe = next(c for c in r["desglose"] if c["criterio"] == "ROE")
        self.assertEqual(criterio_roe["estado"], "s/d")
        self.assertEqual(criterio_roe["valor"], "s/d")
        self.assertAlmostEqual(r["score_total"], 90)


if __name__ == "__main__":
    unittest.main()
