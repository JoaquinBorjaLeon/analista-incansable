"""Tests del panel de solo lectura (Fase 6) con una base de datos temporal."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from src import db


class TestPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self._db, self._cfg = db.RUTA_DB, db.RUTA_CONFIG
        db.RUTA_DB, db.RUTA_CONFIG = raiz / "datos.db", raiz / "config.yaml"
        db.RUTA_CONFIG.write_text(yaml.safe_dump({
            "watchlist": {
                "AAA": {"zona_entrada": [10, 11], "nota_manual": "Entrada escalonada."},
                "BBB": {"zona_entrada": [50, 55]},
            },
            "secundarios": {"CCC": {"nota_manual": "Solo vigilar."}},
            "alertas": {"proximidad_zona_pct": 3},
        }), encoding="utf-8")
        con = db.conectar()
        inicio = date(2026, 1, 1)
        db.upsert_precios(con, [("AAA", (inicio + timedelta(days=i)).isoformat(), 0, 0, 0, c, 1)
                                for i, c in enumerate([12, 11.5, 10.5])])
        db.upsert_precios(con, [("BBB", (inicio + timedelta(days=i)).isoformat(), 0, 0, 0, c, 1)
                                for i, c in enumerate([80, 79])])
        db.upsert_score(con, "AAA", "2026-01-03", 75, json.dumps({
            "desglose": [{"criterio": "ROE", "estado": "verde", "valor": "18.0%", "puntos": 10, "max": 10}],
            "banderas": ["🚩 Dilución > 5% anual (6.0%)"],
        }, ensure_ascii=False))
        con.close()
        from panel.app import app
        self.cliente = TestClient(app)

    def tearDown(self):
        db.RUTA_DB, db.RUTA_CONFIG = self._db, self._cfg
        self.tmp.cleanup()

    def test_dashboard_ordena_por_distancia(self):
        r = self.cliente.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("En zona", r.text)
        self.assertLess(r.text.index("AAA"), r.text.index("BBB"))
        self.assertIn("No es una recomendación de inversión", r.text)

    def test_detalle(self):
        r = self.cliente.get("/ticker/aaa")
        self.assertEqual(r.status_code, 200)
        self.assertIn("75/100", r.text)
        self.assertIn("Entrada escalonada.", r.text)
        self.assertIn("Dilución", r.text)

    def test_ticker_desconocido_da_404(self):
        self.assertEqual(self.cliente.get("/ticker/ZZZ").status_code, 404)

    def test_sin_endpoints_de_escritura(self):
        self.assertEqual(self.cliente.post("/").status_code, 405)


if __name__ == "__main__":
    unittest.main()
