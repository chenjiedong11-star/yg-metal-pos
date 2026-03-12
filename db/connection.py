"""
Phase 3 — Centralised DB access with safe transactions.

Every DB interaction in the app goes through helpers defined here.
UI and services must NEVER write raw SQL — they call repo functions instead.
"""

import sqlite3
import pandas as pd
from contextlib import contextmanager

from core.config import DB_PATH


@contextmanager
def get_connection():
    """
    Context manager that guarantees:
      - timeout=30 s (avoid immediate SQLITE_BUSY under contention)
      - foreign-key enforcement
      - automatic COMMIT on success, ROLLBACK on exception
      - connection is always closed
    """
    print(f"[DB] get_connection DB_PATH={DB_PATH}")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Legacy convenience helpers — thin wrappers around get_connection()
# ---------------------------------------------------------------------------

def db():
    """Return a raw connection (caller must close). Prefer get_connection()."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def qdf(sql, params=()):
    """Execute *sql* and return the result as a pandas DataFrame."""
    with get_connection() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    return df


def qone(sql, params=()):
    """Execute *sql* and return the first row (or None)."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
    return row


def exec_sql(sql, params=()):
    """Execute a single write statement inside a transaction."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
