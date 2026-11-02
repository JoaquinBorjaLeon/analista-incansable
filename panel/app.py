"""Fase 6: panel web de solo lectura para consultar la watchlist desde el móvil.

Lee SQLite y config.yaml directamente (sin API intermedia) y no tiene ningún
endpoint de escritura. Pensado para servirse dentro de la red privada (Tailscale),
nunca expuesto a internet.

Arranque: uvicorn panel.app:app --host 0.0.0.0 --port 8080
"""

import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src import db
from src.alertas import distancia_pct
from src.informe import rsi, vs_media
from src.ingesta import cargar_config

RAIZ = Path(__file__).resolve().parent
app = FastAPI(title="Analista Incansable", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=RAIZ / "static"), name="static")
plantillas = Jinja2Templates(directory=RAIZ / "templates")

PROXIMIDAD_POR_DEFECTO = 3.0


def _resumen(con, ticker: str, datos: dict, proximidad: float) -> dict:
    """Fila del panel: cierre, zona, distancia, técnicos y último score."""
    serie = pd.read_sql_query(
        "SELECT fecha, close FROM precios WHERE ticker = ? ORDER BY fecha", con, params=(ticker,)
    )
    fila = {"ticker": ticker, "nota": datos.get("nota_manual") or "", "zona": datos.get("zona_entrada"),
            "cierre": None, "fecha": None, "distancia": None, "estado": "sin-datos",
            "rsi": None, "sma50": "s/d", "sma200": "s/d", "score": None, "banderas": [], "desglose": []}
    if not serie.empty:
        cierres = serie["close"]
        cierre = float(cierres.iloc[-1])
        fila.update(cierre=cierre, fecha=serie["fecha"].iloc[-1])
        valor_rsi = rsi(cierres)
        fila["rsi"] = None if pd.isna(valor_rsi) else round(valor_rsi, 1)
        fila["sma50"] = vs_media(cierre, cierres.rolling(50).mean().iloc[-1])
        fila["sma200"] = vs_media(cierre, cierres.rolling(200).mean().iloc[-1])
        if fila["zona"]:
            d = distancia_pct(cierre, fila["zona"])
            fila["distancia"] = d
            fila["estado"] = "en-zona" if d == 0 else ("cerca" if abs(d) <= proximidad else "lejos")
        else:
            fila["estado"] = "sin-zona"
    scores = db.ultimos_scores(con, ticker, 1)
    if scores:
        detalle = json.loads(scores[0][2])
        fila.update(score=scores[0][1], banderas=detalle.get("banderas", []),
                    desglose=detalle.get("desglose", []), fecha_score=scores[0][0])
    return fila


def _orden(fila: dict):
    """Por distancia a la zona (los que no tienen zona o datos, al final)."""
    d = fila["distancia"]
    return (d is None, abs(d) if d is not None else 0, fila["ticker"])


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    config = cargar_config()
    proximidad = float((config.get("alertas") or {}).get("proximidad_zona_pct", PROXIMIDAD_POR_DEFECTO))
    con = db.conectar()
    try:
        filas = [_resumen(con, t, d or {}, proximidad) for t, d in (config.get("watchlist") or {}).items()]
        secundarios = [_resumen(con, t, d or {}, proximidad) for t, d in (config.get("secundarios") or {}).items()]
    finally:
        con.close()
    filas.sort(key=_orden)
    return plantillas.TemplateResponse(request, "index.html", {"filas": filas, "secundarios": secundarios})


@app.get("/ticker/{simbolo}", response_class=HTMLResponse)
def detalle(request: Request, simbolo: str):
    config = cargar_config()
    simbolo = simbolo.upper()
    todos = {**(config.get("watchlist") or {}), **(config.get("secundarios") or {})}
    if simbolo not in todos:
        raise HTTPException(status_code=404, detail="Ticker fuera de la watchlist")
    proximidad = float((config.get("alertas") or {}).get("proximidad_zona_pct", PROXIMIDAD_POR_DEFECTO))
    con = db.conectar()
    try:
        fila = _resumen(con, simbolo, todos[simbolo] or {}, proximidad)
        recientes = con.execute(
            "SELECT fecha, tipo, payload FROM alertas_enviadas WHERE ticker = ? ORDER BY fecha DESC LIMIT 10",
            (simbolo,),
        ).fetchall()
    finally:
        con.close()
    alertas = [{"fecha": f, "tipo": t, "mensaje": json.loads(p).get("mensaje", "")} for f, t, p in recientes]
    return plantillas.TemplateResponse(request, "ticker.html", {"f": fila, "alertas": alertas})
