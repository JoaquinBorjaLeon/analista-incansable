"""Genera una base de datos de demostración con datos sintéticos (sin red).

Sirve para probar el informe, las alertas y el panel sin descargar nada:

    python -m scripts.demo
    ANALISTA_DB=demo/datos.db ANALISTA_CONFIG=demo/config.yaml uvicorn panel.app:app --port 8080

Los tickers DEMO* y sus cifras son inventados. El score sí sale del motor real
(src.analisis.calcular_score) aplicado a esas métricas sintéticas.
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DEMO = RAIZ / "demo"

CONFIG = {
    "watchlist": {
        "DEMOA": {"zona_entrada": [41.0, 43.0], "nota_manual": "Entrada escalonada, no de golpe."},
        "DEMOB": {"zona_entrada": [118.0, 124.0], "nota_manual": "Esperar a resultados antes de ampliar."},
        "DEMOC": {"zona_entrada": [12.0, 13.0], "bandera_manual": "Dependencia de un único cliente",
                  "nota_manual": "Tamaño mínimo aunque toque zona."},
    },
    "secundarios": {"DEMOD": {"nota_manual": "Solo vigilar fundamentales."}},
}

METRICAS = {
    "DEMOA": dict(crecimiento_ingresos_yoy=24.0, crecimiento_ingresos_yoy_anterior=27.0, margen_bruto=62.0,
                  margen_bruto_anterior=61.0, fcf_ttm=180e6, fcf_anterior=140e6, margen_fcf=14.0,
                  deuda_total=90e6, caja=300e6, deuda_neta_ebitda=None, roe=17.0, dilucion_yoy=1.5,
                  beneficio_neto=60e6, crecimiento_beneficio_yoy=30.0),
    "DEMOB": dict(crecimiento_ingresos_yoy=12.0, crecimiento_ingresos_yoy_anterior=14.0, margen_bruto=41.0,
                  margen_bruto_anterior=42.0, fcf_ttm=50e6, fcf_anterior=55e6, margen_fcf=6.0,
                  deuda_total=400e6, caja=100e6, deuda_neta_ebitda=2.1, roe=11.0, dilucion_yoy=3.0,
                  beneficio_neto=20e6, crecimiento_beneficio_yoy=8.0),
    "DEMOC": dict(crecimiento_ingresos_yoy=6.0, crecimiento_ingresos_yoy_anterior=21.0, margen_bruto=33.0,
                  margen_bruto_anterior=38.0, fcf_ttm=-15e6, fcf_anterior=5e6, margen_fcf=-4.0,
                  deuda_total=300e6, caja=40e6, deuda_neta_ebitda=3.8, roe=4.0, dilucion_yoy=7.5,
                  beneficio_neto=-8e6, crecimiento_beneficio_yoy=None),
    "DEMOD": dict(crecimiento_ingresos_yoy=9.0, margen_bruto=48.0, fcf_ttm=30e6, fcf_anterior=28e6,
                  margen_fcf=9.0, deuda_total=10e6, caja=50e6, roe=14.0, dilucion_yoy=0.5,
                  beneficio_neto=25e6, crecimiento_beneficio_yoy=10.0),
}

# precio inicial y final aproximado de cada serie sintética (260 sesiones)
SERIES = {"DEMOA": (55.0, 42.2), "DEMOB": (110.0, 127.0), "DEMOC": (20.0, 15.6)}


def _serie(inicio: float, fin: float, n: int, semilla: int) -> list[float]:
    rnd = random.Random(semilla)
    valores, ruido = [], 0.0
    for i in range(n):
        tendencia = inicio + (fin - inicio) * i / (n - 1)
        ruido = 0.85 * ruido + rnd.gauss(0, inicio * 0.012)
        valores.append(round(max(0.5, tendencia + ruido), 2))
    valores[-1] = fin
    return valores


def main() -> None:
    DEMO.mkdir(exist_ok=True)
    ruta_db, ruta_cfg = DEMO / "datos.db", DEMO / "config.yaml"
    if ruta_db.exists():
        ruta_db.unlink()

    base = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    config = {**CONFIG, "umbrales_score": base["umbrales_score"], "pesos_score": base["pesos_score"],
              "alertas": base.get("alertas", {})}
    ruta_cfg.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    from src import db
    from src.analisis import calcular_score
    db.RUTA_DB, db.RUTA_CONFIG = ruta_db, ruta_cfg
    con = db.conectar()
    hoy = date.today()
    for i, (ticker, (ini, fin)) in enumerate(SERIES.items()):
        cierres = _serie(ini, fin, 260, semilla=7 + i)
        filas = [(ticker, (hoy - timedelta(days=len(cierres) - 1 - k)).isoformat(), c, c, c, c, 100000)
                 for k, c in enumerate(cierres)]
        db.upsert_precios(con, filas)
    for ticker, metricas in METRICAS.items():
        datos = {**config["watchlist"], **config["secundarios"]}[ticker]
        res = calcular_score(metricas, config, datos.get("bandera_manual"))
        detalle = {"desglose": res["desglose"], "banderas": res["banderas"], "nota_manual": datos.get("nota_manual")}
        db.upsert_score(con, ticker, hoy.isoformat(), res["score_total"], json.dumps(detalle, ensure_ascii=False))
    con.close()
    print(f"Demo creada en {DEMO}/ (datos sintéticos)")


if __name__ == "__main__":
    main()
