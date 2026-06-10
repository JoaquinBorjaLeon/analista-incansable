"""Informe diario (versión mínima Fase 1): tabla en consola.

ticker | cierre | zona | distancia % | RSI(14) | vs SMA50 | vs SMA200 | nota_manual

RSI y SMAs se calculan con pandas sobre los datos guardados en SQLite.
La distancia es respecto al borde más cercano de la zona de entrada:
positiva = el precio está por encima de la zona; negativa = por debajo;
"EN ZONA" si el cierre está dentro.
"""

import pandas as pd

from . import db
from .ingesta import cargar_config

PERIODO_RSI = 14


def rsi(close: pd.Series, periodo: int = PERIODO_RSI) -> float:
    """RSI con suavizado de Wilder. NaN si no hay datos suficientes."""
    delta = close.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    media_g = ganancia.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    media_p = perdida.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    ultima_g, ultima_p = media_g.iloc[-1], media_p.iloc[-1]
    if pd.isna(ultima_g) or pd.isna(ultima_p):
        return float("nan")
    if ultima_p == 0:
        return 100.0
    rs = ultima_g / ultima_p
    return 100 - 100 / (1 + rs)


def distancia_a_zona(cierre: float, zona: list) -> str:
    """% desde el cierre hasta el borde más cercano de la zona de entrada."""
    zona_min, zona_max = float(zona[0]), float(zona[1])
    if zona_min <= cierre <= zona_max:
        return "EN ZONA"
    if cierre > zona_max:
        return f"{(cierre - zona_max) / zona_max * 100:+.1f}%"
    return f"{(cierre - zona_min) / zona_min * 100:+.1f}%"


def vs_media(cierre: float, media: float) -> str:
    if pd.isna(media):
        return "s/d"
    return f"{(cierre / media - 1) * 100:+.1f}%"


def fila_ticker(con, ticker: str, datos_ticker: dict) -> dict:
    serie = pd.read_sql_query(
        "SELECT fecha, close FROM precios WHERE ticker = ? ORDER BY fecha",
        con,
        params=(ticker,),
    )["close"]
    if serie.empty:
        return {
            "ticker": ticker, "cierre": "s/d", "zona": "—", "distancia": "—",
            "rsi": "—", "sma50": "—", "sma200": "—",
            "nota": datos_ticker.get("nota_manual", ""),
        }

    cierre = float(serie.iloc[-1])
    zona = datos_ticker.get("zona_entrada")
    valor_rsi = rsi(serie)
    sma50 = serie.rolling(50).mean().iloc[-1]
    sma200 = serie.rolling(200).mean().iloc[-1]

    return {
        "ticker": ticker,
        "cierre": f"{cierre:.2f}",
        "zona": f"{zona[0]}-{zona[1]}" if zona else "—",
        "distancia": distancia_a_zona(cierre, zona) if zona else "—",
        "rsi": f"{valor_rsi:.1f}" if not pd.isna(valor_rsi) else "s/d",
        "sma50": vs_media(cierre, sma50),
        "sma200": vs_media(cierre, sma200),
        "nota": datos_ticker.get("nota_manual", ""),
    }


def main() -> None:
    config = cargar_config()
    con = db.conectar()
    try:
        filas = [
            fila_ticker(con, ticker, datos or {})
            for ticker, datos in config["watchlist"].items()
        ]
    finally:
        con.close()

    columnas = [
        ("ticker", "ticker", 6),
        ("cierre", "cierre", 8),
        ("zona", "zona", 12),
        ("distancia", "distancia %", 11),
        ("rsi", "RSI(14)", 7),
        ("sma50", "vs SMA50", 8),
        ("sma200", "vs SMA200", 9),
        ("nota", "nota_manual", 0),
    ]
    cabecera = " | ".join(
        titulo.ljust(ancho) if ancho else titulo for _, titulo, ancho in columnas
    )
    print(cabecera)
    print("-" * len(cabecera))
    for fila in filas:
        print(
            " | ".join(
                str(fila[clave]).ljust(ancho) if ancho else str(fila[clave])
                for clave, _, ancho in columnas
            )
        )


if __name__ == "__main__":
    main()
