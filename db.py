"""
db.py - Postgres connection helper for InsightAgent v2.

The single place that knows how to reach the Pagila database. Reads connection
settings from .env and hands out a psycopg3 connection; every module that
touches Postgres goes through here.
"""
from __future__ import annotations

from pathlib import Path

import psycopg

_ENV_PATH = Path(__file__).with_name(".env")


def load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, ignoring blanks and '#' comments,
    stripping surrounding whitespace and quotes."""
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def connection_string(cfg: dict[str, str] | None = None) -> str:
    cfg = cfg or load_env()
    return (
        f"host={cfg['DB_HOST']} port={cfg['DB_PORT']} dbname={cfg['DB_NAME']} "
        f"user={cfg['DB_USER']} password={cfg['DB_PASSWORD']}"
    )


def get_connection():
    """Open a new psycopg3 connection to the Pagila database."""
    return psycopg.connect(connection_string())


# --- catalog introspection (used by SQL generation and validation) ----------

_FK_COLS_SQL = """
SELECT
  CASE WHEN src.relname LIKE 'payment_p%' THEN 'payment' ELSE src.relname END AS src_table,
  sa.attname AS src_col,
  CASE WHEN tgt.relname LIKE 'payment_p%' THEN 'payment' ELSE tgt.relname END AS tgt_table,
  ta.attname AS tgt_col
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
JOIN pg_namespace n ON n.oid = src.relnamespace
JOIN LATERAL unnest(con.conkey, con.confkey) AS k(src_attnum, tgt_attnum) ON true
JOIN pg_attribute sa ON sa.attrelid = con.conrelid AND sa.attnum = k.src_attnum
JOIN pg_attribute ta ON ta.attrelid = con.confrelid AND ta.attnum = k.tgt_attnum
WHERE con.contype = 'f' AND n.nspname = 'public';
"""


def get_columns(conn, tables: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Real columns (name, type) for each given table, in definition order."""
    out: dict[str, list[tuple[str, str]]] = {t: [] for t in tables}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ANY(%s)
            ORDER BY table_name, ordinal_position;
            """,
            (tables,),
        )
        for t, c, ty in cur.fetchall():
            out.setdefault(t, []).append((c, ty))
    return out


def get_fk_join_edges(conn, tables: list[str]) -> list[tuple[str, str, str, str]]:
    """Foreign-key join paths (src_table, src_col, tgt_table, tgt_col) where both
    ends are in `tables`. Payment partitions collapse to 'payment'."""
    sel = set(tables)
    seen: set[tuple[str, str, str, str]] = set()
    edges: list[tuple[str, str, str, str]] = []
    with conn.cursor() as cur:
        cur.execute(_FK_COLS_SQL)
        for s, sc, t, tc in cur.fetchall():
            if s in sel and t in sel and (s, sc, t, tc) not in seen:
                seen.add((s, sc, t, tc))
                edges.append((s, sc, t, tc))
    return edges


def get_schema(conn) -> dict[str, set[str]]:
    """Every public table/view mapped to its set of column names. Used by the
    validator to confirm generated SQL references only real tables and columns."""
    out: dict[str, set[str]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public';
            """
        )
        for t, c in cur.fetchall():
            out.setdefault(t, set()).add(c)
    return out
