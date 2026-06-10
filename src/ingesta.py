"""M1: descarga precios + fundamentales de la watchlist (yfinance) → SQLite.

- Precios: OHLCV diario, periodo 1y. Las filas con Close en NaN se descartan.
- Fundamentales: Ticker.info / financials / cashflow / balance_sheet.
  yfinance puede devolver campos vacíos o nombres cambiantes: cada métrica
  que falte se guarda como NULL — NUNCA se inventa ni se interpola.
Si un ticker falla, se registra en el log y se continúa con el resto.
"""

import logging
import math

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


def _num(x):
    """float o None. NaN/inf y valores no numéricos → None (se mostrará 's/d')."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _primero(*valores):
    for v in valores:
        if v is not None:
            return v
    return None


def _estado(t: yf.Ticker, nombre: str):
    """Estado financiero anual como DataFrame, o None si yfinance no lo da."""
    try:
        df = getattr(t, nombre)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def _valores_anuales(df, nombres, n=3):
    """Primeros n valores anuales (más reciente primero) de la primera fila que exista."""
    if df is not None:
        for nombre in nombres:
            if nombre in df.index:
                valores = [_num(v) for v in df.loc[nombre].iloc[:n]]
                return valores + [None] * (n - len(valores))
    return [None] * n


def _variacion_pct(actual, anterior):
    """% de variación YoY. None si falta dato o la base no es positiva."""
    if actual is None or anterior is None or anterior <= 0:
        return None
    return (actual - anterior) / anterior * 100


def _ratio_pct(numerador, denominador):
    if numerador is None or denominador is None or denominador == 0:
        return None
    return numerador / denominador * 100


def _frac_pct(x):
    """Fracción de yfinance.info (0.61) → porcentaje (61.0)."""
    v = _num(x)
    return None if v is None else v * 100


def descargar_fundamentales(ticker: str) -> dict:
    """Métricas del esquema `fundamentales` + auxiliares YoY para el score.

    Los YoY se calculan sobre los dos/tres últimos ejercicios anuales de los
    estados financieros (aproximación a TTM vs TTM-1y: yfinance no da 8 trimestres).
    """
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    fin = _estado(t, "financials")
    cf = _estado(t, "cashflow")
    bal = _estado(t, "balance_sheet")

    ing0, ing1, ing2 = _valores_anuales(fin, ["Total Revenue", "Operating Revenue"])
    gp0, gp1, _ = _valores_anuales(fin, ["Gross Profit"])
    op0, _, _ = _valores_anuales(fin, ["Operating Income"])
    ben0, ben1, _ = _valores_anuales(fin, ["Net Income", "Net Income Common Stockholders"])
    fcf0, fcf1, _ = _valores_anuales(cf, ["Free Cash Flow"])
    acc0, acc1, _ = _valores_anuales(bal, ["Ordinary Shares Number", "Share Issued"])

    ingresos_ttm = _primero(_num(info.get("totalRevenue")), ing0)
    fcf_ttm = _primero(_num(info.get("freeCashflow")), fcf0)
    deuda_total = _primero(_num(info.get("totalDebt")), _valores_anuales(bal, ["Total Debt"])[0])
    caja = _primero(
        _num(info.get("totalCash")),
        _valores_anuales(bal, ["Cash And Cash Equivalents"])[0],
    )
    ebitda = _num(info.get("ebitda"))
    deuda_neta_ebitda = None
    if ebitda is not None and ebitda > 0 and deuda_total is not None and caja is not None:
        deuda_neta_ebitda = (deuda_total - caja) / ebitda

    return {
        # columnas del esquema §4
        "ingresos_ttm": ingresos_ttm,
        "crecimiento_ingresos_yoy": _variacion_pct(ing0, ing1),
        "margen_bruto": _primero(_ratio_pct(gp0, ing0), _frac_pct(info.get("grossMargins"))),
        "margen_operativo": _primero(_frac_pct(info.get("operatingMargins")), _ratio_pct(op0, ing0)),
        "margen_neto": _primero(_frac_pct(info.get("profitMargins")), _ratio_pct(ben0, ing0)),
        "fcf_ttm": fcf_ttm,
        "margen_fcf": _ratio_pct(fcf_ttm, ingresos_ttm),
        "deuda_total": deuda_total,
        "caja": caja,
        "deuda_neta_ebitda": deuda_neta_ebitda,
        "roe": _frac_pct(info.get("returnOnEquity")),
        "acciones_circulacion": _primero(_num(info.get("sharesOutstanding")), acc0),
        "dilucion_yoy": _variacion_pct(acc0, acc1),
        "per_ttm": _num(info.get("trailingPE")),
        "per_forward": _num(info.get("forwardPE")),
        "ev_ventas": _num(info.get("enterpriseToRevenue")),
        # auxiliares YoY (van al detalle del score, no a la tabla fundamentales)
        "crecimiento_ingresos_yoy_anterior": _variacion_pct(ing1, ing2),
        "margen_bruto_anterior": _ratio_pct(gp1, ing1),
        "fcf_anterior": fcf1,
        "beneficio_neto": ben0,
        "crecimiento_beneficio_yoy": _variacion_pct(ben0, ben1),
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    from . import analisis  # import perezoso: evita ciclo ingesta ↔ analisis

    config = cargar_config()
    con = db.conectar()
    try:
        for ticker in config["watchlist"]:
            try:
                n = descargar_ticker(con, ticker)
                log.info("%s: %d filas de precios guardadas", ticker, n)
            except Exception:
                log.exception("%s: fallo en la descarga de precios, se continúa", ticker)

        # fundamentales + score: watchlist y secundarios ("solo vigilar fundamentales")
        todos = {**config["watchlist"], **(config.get("secundarios") or {})}
        for ticker in todos:
            try:
                score, _ = analisis.procesar_ticker(con, ticker, config)
                log.info("%s: fundamentales y score (%.1f) guardados", ticker, score)
            except Exception:
                log.exception("%s: fallo en fundamentales, se continúa", ticker)
    finally:
        con.close()


if __name__ == "__main__":
    main()
