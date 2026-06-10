"""M1: descarga OHLCV diario de la watchlist (yfinance, periodo 1y) → SQLite.

Si un ticker falla, se registra en el log y se continúa con el resto.
Las filas con Close en NaN se descartan antes de guardar.
"""

import logging

import yaml
import yfinance as yf

from . import db

log = logging.getLogger("ingesta")


def cargar_config() -> dict:
    with open(db.RUTA_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def descargar_ticker(con, ticker: str) -> int:
    """Descarga 1 año de OHLCV diario de un ticker y lo guarda. Devuelve nº de filas."""
    hist = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=False)
    if hist.empty:
        raise ValueError(f"yfinance no devolvió datos para {ticker}")

    hist = hist.dropna(subset=["Close"])

    filas = [
        (
            ticker,
            fecha.strftime("%Y-%m-%d"),
            float(fila["Open"]),
            float(fila["High"]),
            float(fila["Low"]),
            float(fila["Close"]),
            int(fila["Volume"]),
        )
        for fecha, fila in hist.iterrows()
    ]
    return db.upsert_precios(con, filas)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    config = cargar_config()
    tickers = list(config["watchlist"].keys())

    con = db.conectar()
    try:
        for ticker in tickers:
            try:
                n = descargar_ticker(con, ticker)
                log.info("%s: %d filas guardadas", ticker, n)
            except Exception:
                log.exception("%s: fallo en la descarga, se continúa", ticker)
    finally:
        con.close()


if __name__ == "__main__":
    main()
