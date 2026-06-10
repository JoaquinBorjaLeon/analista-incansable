"""Esquema y helpers de SQLite (Fase 2: tablas `precios`, `fundamentales` y `scores`)."""

import sqlite3
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_DB = RAIZ_PROYECTO / "datos.db"
RUTA_CONFIG = RAIZ_PROYECTO / "config.yaml"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS precios (
    ticker TEXT NOT NULL,
    fecha DATE NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volumen INTEGER,
    PRIMARY KEY (ticker, fecha)
);

CREATE TABLE IF NOT EXISTS fundamentales (
    ticker TEXT NOT NULL,
    fecha_snapshot DATE NOT NULL,
    ingresos_ttm REAL,            -- USD
    crecimiento_ingresos_yoy REAL,-- % (TTM vs TTM-1y)
    margen_bruto REAL,            -- %
    margen_operativo REAL,        -- %
    margen_neto REAL,             -- %
    fcf_ttm REAL,                 -- USD
    margen_fcf REAL,              -- %
    deuda_total REAL,
    caja REAL,
    deuda_neta_ebitda REAL,       -- x (NULL si EBITDA <= 0)
    roe REAL,                     -- %
    acciones_circulacion REAL,
    dilucion_yoy REAL,            -- % crecimiento de acciones
    per_ttm REAL,                 -- NULL si pérdidas
    per_forward REAL,
    ev_ventas REAL,
    PRIMARY KEY (ticker, fecha_snapshot)
);

CREATE TABLE IF NOT EXISTS scores (
    ticker TEXT NOT NULL,
    fecha DATE NOT NULL,
    score_total REAL,             -- 0-100
    detalle_json TEXT,            -- desglose por criterio + banderas rojas
    PRIMARY KEY (ticker, fecha)
);
"""

CAMPOS_FUNDAMENTALES = [
    "ingresos_ttm", "crecimiento_ingresos_yoy", "margen_bruto", "margen_operativo",
    "margen_neto", "fcf_ttm", "margen_fcf", "deuda_total", "caja",
    "deuda_neta_ebitda", "roe", "acciones_circulacion", "dilucion_yoy",
    "per_ttm", "per_forward", "ev_ventas",
]


def conectar() -> sqlite3.Connection:
    """Abre la conexión y garantiza que el esquema existe."""
    con = sqlite3.connect(RUTA_DB)
    con.executescript(ESQUEMA)
    return con


def upsert_precios(con: sqlite3.Connection, filas) -> int:
    """Inserta o actualiza filas (ticker, fecha, open, high, low, close, volumen)."""
    cur = con.executemany(
        """
        INSERT INTO precios (ticker, fecha, open, high, low, close, volumen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, fecha) DO UPDATE SET
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volumen = excluded.volumen
        """,
        filas,
    )
    con.commit()
    return cur.rowcount


def upsert_fundamentales(con: sqlite3.Connection, ticker: str, fecha_snapshot: str, metricas: dict) -> None:
    """Guarda un snapshot de fundamentales. Las métricas ausentes quedan a NULL."""
    columnas = ", ".join(CAMPOS_FUNDAMENTALES)
    marcas = ", ".join("?" * (2 + len(CAMPOS_FUNDAMENTALES)))
    con.execute(
        f"INSERT OR REPLACE INTO fundamentales (ticker, fecha_snapshot, {columnas}) VALUES ({marcas})",
        [ticker, fecha_snapshot] + [metricas.get(c) for c in CAMPOS_FUNDAMENTALES],
    )
    con.commit()


def upsert_score(con: sqlite3.Connection, ticker: str, fecha: str, score_total: float, detalle_json: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO scores (ticker, fecha, score_total, detalle_json) VALUES (?, ?, ?, ?)",
        (ticker, fecha, score_total, detalle_json),
    )
    con.commit()
