"""M3: alertas de la watchlist (Fase 3).

Evalúa cada ticker de la watchlist con los datos ya guardados en SQLite y devuelve
las alertas pendientes:

- entrada_zona        el cierre está dentro de la zona de entrada
- proximidad          el cierre está a menos de `proximidad_zona_pct` % de la zona
- cruce_media         el cierre cruza la SMA200 (en cualquier dirección)
- bandera_roja_nueva  aparece una bandera roja que no estaba en el score anterior

Reglas:
- Anti-spam: no se repite la misma alerta (ticker, tipo) durante `antispam_dias`
  (tabla `alertas_enviadas`).
- Toda alerta de zona incluye los titulares recientes ("¿por qué se ha movido?")
  y la `nota_manual` del ticker.
- Analiza y avisa; nunca recomienda comprar ni vender.

CLI:
  python -m src.alertas            vista previa legible, no registra nada
  python -m src.alertas --json     JSON para n8n (Execute Command) y registra las alertas
  python -m src.alertas --enviar   envía por Telegram (TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID
                                   en .env) y registra las alertas
  --sin-registrar                  con --json o --enviar, no escribe en alertas_enviadas
"""

import argparse
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

import pandas as pd

from . import db, titulares
from .ingesta import cargar_config

log = logging.getLogger("alertas")

AVISO = "Análisis automático, no es una recomendación de inversión."


def distancia_pct(cierre: float, zona) -> float:
    """% desde el cierre hasta el borde más cercano de la zona. 0 si está dentro.

    Positivo: el precio está por encima de la zona. Negativo: por debajo.
    """
    zona_min, zona_max = float(zona[0]), float(zona[1])
    if zona_min <= cierre <= zona_max:
        return 0.0
    if cierre > zona_max:
        return (cierre - zona_max) / zona_max * 100
    return (cierre - zona_min) / zona_min * 100


def alertas_de_precio(ticker: str, cierres: pd.Series, datos: dict, proximidad_pct: float) -> list[dict]:
    """Alertas de zona, proximidad y cruce de la SMA200 a partir de la serie de cierres."""
    cierres = cierres.dropna()
    if cierres.empty:
        return []
    cierre = float(cierres.iloc[-1])
    alertas = []

    zona = datos.get("zona_entrada")
    if zona:
        d = distancia_pct(cierre, zona)
        datos_zona = {"cierre": round(cierre, 2), "zona": [zona[0], zona[1]], "distancia_pct": round(d, 2)}
        if d == 0:
            alertas.append({
                "ticker": ticker, "tipo": "entrada_zona", "datos": datos_zona,
                "mensaje": f"{ticker} cierra en {cierre:.2f}, dentro de su zona {zona[0]}-{zona[1]}.",
            })
        elif abs(d) <= proximidad_pct:
            lado = "por encima" if d > 0 else "por debajo"
            alertas.append({
                "ticker": ticker, "tipo": "proximidad", "datos": datos_zona,
                "mensaje": (f"{ticker} cierra en {cierre:.2f}, a un {abs(d):.1f}% {lado} "
                            f"de su zona {zona[0]}-{zona[1]}."),
            })

    sma200 = cierres.rolling(200).mean()
    if len(cierres) >= 201 and not pd.isna(sma200.iloc[-1]) and not pd.isna(sma200.iloc[-2]):
        antes = float(cierres.iloc[-2]) - float(sma200.iloc[-2])
        ahora = cierre - float(sma200.iloc[-1])
        sentido = None
        if antes < 0 <= ahora:
            sentido = "al alza"
        elif antes >= 0 > ahora:
            sentido = "a la baja"
        if sentido:
            alertas.append({
                "ticker": ticker, "tipo": "cruce_media",
                "datos": {"cierre": round(cierre, 2), "sma200": round(float(sma200.iloc[-1]), 2), "sentido": sentido},
                "mensaje": f"{ticker} cruza su media de 200 sesiones {sentido} ({cierre:.2f} frente a {float(sma200.iloc[-1]):.2f}).",
            })
    return alertas


def _clave_bandera(bandera: str) -> str:
    """La parte estable de una bandera, sin el valor entre paréntesis que cambia cada día."""
    return bandera.split(" (")[0].strip()


def banderas_nuevas(detalle_actual: dict, detalle_anterior: dict | None) -> list[str]:
    """Banderas del score actual que no estaban en el anterior (comparadas sin su valor)."""
    actuales = detalle_actual.get("banderas", []) if detalle_actual else []
    if detalle_anterior is None:
        return []  # sin histórico no hay nada con lo que comparar: no se avisa
    previas = {_clave_bandera(b) for b in detalle_anterior.get("banderas", [])}
    return [b for b in actuales if _clave_bandera(b) not in previas]


def alertas_de_banderas(ticker: str, scores: list) -> list[dict]:
    """scores: [(fecha, score_total, detalle_json), ...] del más reciente al más antiguo."""
    if not scores:
        return []
    actual = json.loads(scores[0][2])
    anterior = json.loads(scores[1][2]) if len(scores) > 1 else None
    nuevas = banderas_nuevas(actual, anterior)
    if not nuevas:
        return []
    return [{
        "ticker": ticker, "tipo": "bandera_roja_nueva",
        "datos": {"score": scores[0][1], "banderas": nuevas},
        "mensaje": f"{ticker} tiene banderas rojas nuevas: " + "; ".join(nuevas),
    }]


def evaluar(con, config: dict, hoy: date, obtener_titulares=titulares.obtener_titulares) -> list[dict]:
    """Todas las alertas pendientes de la watchlist, ya filtradas por anti-spam."""
    cfg = config.get("alertas") or {}
    proximidad = float(cfg.get("proximidad_zona_pct", 3))
    antispam = int(cfg.get("antispam_dias", 5))
    desde = (hoy - timedelta(days=antispam - 1)).isoformat()

    pendientes = []
    for ticker, datos in (config.get("watchlist") or {}).items():
        datos = datos or {}
        cierres = pd.read_sql_query(
            "SELECT fecha, close FROM precios WHERE ticker = ? ORDER BY fecha", con, params=(ticker,)
        )["close"]
        candidatas = alertas_de_precio(ticker, cierres, datos, proximidad)
        candidatas += alertas_de_banderas(ticker, db.ultimos_scores(con, ticker, 2))

        for alerta in candidatas:
            if db.alerta_reciente(con, ticker, alerta["tipo"], desde):
                continue
            alerta["fecha"] = hoy.isoformat()
            alerta["nota_manual"] = datos.get("nota_manual")
            if alerta["tipo"] in ("entrada_zona", "proximidad"):
                alerta["titulares"] = obtener_titulares(ticker, 5)
            pendientes.append(alerta)
    return pendientes


def formatear(alerta: dict) -> str:
    """Texto plano listo para Telegram."""
    lineas = [alerta["mensaje"]]
    if alerta.get("nota_manual"):
        lineas.append(f"Nota: {alerta['nota_manual']}")
    if alerta.get("titulares"):
        lineas.append("Titulares recientes:")
        lineas += [f"- {t['titulo']}" + (f" ({t['fuente']})" if t.get("fuente") else "")
                   for t in alerta["titulares"]]
    elif alerta["tipo"] in ("entrada_zona", "proximidad"):
        lineas.append("Sin titulares disponibles: revisa las noticias antes de decidir.")
    lineas.append(AVISO)
    return "\n".join(lineas)


def enviar_telegram(texto: str, token: str, chat_id: str, timeout: int = 15) -> None:
    datos = urllib.parse.urlencode({
        "chat_id": chat_id, "text": texto, "disable_web_page_preview": "true",
    }).encode()
    peticion = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=datos)
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        if respuesta.status != 200:
            raise RuntimeError(f"Telegram respondió {respuesta.status}")


def registrar(con, alertas: list[dict]) -> None:
    for alerta in alertas:
        db.registrar_alerta(con, alerta["ticker"], alerta["tipo"], alerta["fecha"],
                            json.dumps(alerta, ensure_ascii=False))


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Alertas de la watchlist")
    parser.add_argument("--json", action="store_true", help="salida JSON para n8n")
    parser.add_argument("--enviar", action="store_true", help="enviar por Telegram")
    parser.add_argument("--sin-registrar", action="store_true", help="no escribir en alertas_enviadas")
    args = parser.parse_args(argv)

    config = cargar_config()
    con = db.conectar()
    try:
        alertas = evaluar(con, config, date.today())

        if args.json:
            print(json.dumps({"total": len(alertas), "alertas": alertas,
                              "texto": "\n\n".join(formatear(a) for a in alertas)},
                             ensure_ascii=False, indent=2))
        elif not args.enviar:
            if not alertas:
                print("Sin alertas pendientes.")
            for alerta in alertas:
                print(formatear(alerta))
                print()

        if args.enviar and alertas:
            try:
                from dotenv import load_dotenv
                load_dotenv(db.RAIZ_PROYECTO / ".env")
            except ImportError:
                pass
            token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
            if not token or not chat_id:
                log.error("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env")
                return 1
            for alerta in alertas:
                enviar_telegram(formatear(alerta), token, chat_id)
            log.info("%d alertas enviadas por Telegram", len(alertas))

        if (args.json or args.enviar) and not args.sin_registrar:
            registrar(con, alertas)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
