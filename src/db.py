"""Esquema y helpers de SQLite (Fase 1: solo tabla `precios`)."""

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
"""


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
