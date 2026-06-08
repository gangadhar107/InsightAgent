"""
execution.py - InsightAgent v2 query execution (step 3).

Runs already-validated SQL with defense-in-depth, in case anything slips past the
validator:
  * a READ-ONLY transaction  -> Postgres rejects any write at the engine level,
  * a statement_timeout       -> nothing can hang,
  * a row cap                 -> large result sets are truncated, not unbounded.

Returns columns + rows + metadata. Never raises for a bad query; failures come
back as ok=False with the database's own message.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import psycopg

from db import get_connection


@dataclass
class ExecutionResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: str | None = None


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def execute_sql(sql: str, timeout_ms: int = 5000, max_rows: int = 1000) -> ExecutionResult:
    start = time.perf_counter()
    try:
        with get_connection() as conn:
            conn.read_only = True  # engine-level guard: writes are rejected
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {int(timeout_ms)}")
                cur.execute(sql)
                if cur.description is None:
                    return ExecutionResult(True, elapsed_ms=_ms(start))
                columns = [c.name for c in cur.description]
                fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = list(fetched[:max_rows])
        return ExecutionResult(True, columns, rows, len(rows), truncated, _ms(start))
    except psycopg.Error as e:
        msg = (str(e).strip().splitlines() or [type(e).__name__])[0]
        return ExecutionResult(False, error=msg, elapsed_ms=_ms(start))


if __name__ == "__main__":
    q8 = (
        "SELECT c.name AS category_name, SUM(p.amount) AS total_revenue "
        "FROM payment p "
        "JOIN rental r ON p.rental_id = r.rental_id "
        "JOIN inventory i ON r.inventory_id = i.inventory_id "
        "JOIN film_category fc ON i.film_id = fc.film_id "
        "JOIN category c ON fc.category_id = c.category_id "
        "GROUP BY c.category_id, c.name ORDER BY total_revenue DESC LIMIT 1"
    )

    print("--- Q1: total revenue (expect 67416.51) ---")
    r = execute_sql("SELECT SUM(amount) AS total_revenue FROM payment")
    print(f"ok={r.ok} cols={r.columns} rows={r.rows} {r.elapsed_ms}ms")

    print("\n--- Q8: top category (expect Sports, 5314.21) ---")
    r = execute_sql(q8)
    print(f"ok={r.ok} cols={r.columns} rows={r.rows} {r.elapsed_ms}ms")

    print("\n--- guard: statement_timeout (expect ok=False, timeout) ---")
    r = execute_sql("SELECT pg_sleep(2)", timeout_ms=200)
    print(f"ok={r.ok} error={r.error!r} {r.elapsed_ms}ms")

    print("\n--- guard: read-only blocks writes (expect ok=False, read-only) ---")
    r = execute_sql("CREATE TEMP TABLE _ro_probe (x int)")
    print(f"ok={r.ok} error={r.error!r}")

    print("\n--- guard: row cap (expect truncated=True, 5 rows) ---")
    r = execute_sql("SELECT rental_id FROM rental", max_rows=5)
    print(f"ok={r.ok} row_count={r.row_count} truncated={r.truncated}")
