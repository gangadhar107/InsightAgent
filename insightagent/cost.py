"""
cost.py - InsightAgent v2 cost guard (step 7, between validation and execution).

Runs EXPLAIN (FORMAT JSON) - the planner only, NOT EXPLAIN ANALYZE, so the query
is never executed - reads Postgres's estimated total cost, and blocks anything
above a ceiling. This stops a ruinously expensive query (e.g. an accidental
cross join) from ever reaching the database.

Costs are in Postgres's arbitrary planner units; the ceiling is calibrated to
sit well above normal Pagila analytics queries but below a cartesian blow-up.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from insightagent.db import get_connection

DEFAULT_CEILING = 1_000_000.0


@dataclass
class CostResult:
    ok: bool
    cost: float = 0.0
    ceiling: float = 0.0
    error: str | None = None


def estimate_cost(sql: str) -> float:
    """Planner's estimated total cost for `sql`, via EXPLAIN (no execution)."""
    stmt = "EXPLAIN (FORMAT JSON) " + sql.strip().rstrip(";")
    with get_connection() as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 5000")
            cur.execute(stmt)
            data = cur.fetchone()[0]
    if isinstance(data, str):
        data = json.loads(data)
    return float(data[0]["Plan"]["Total Cost"])


def cost_guard(sql: str, ceiling: float = DEFAULT_CEILING) -> CostResult:
    """Block the query if its estimated cost exceeds the ceiling."""
    try:
        cost = estimate_cost(sql)
    except psycopg.Error as e:
        msg = (str(e).strip().splitlines() or ["EXPLAIN failed"])[0]
        return CostResult(False, ceiling=ceiling, error=f"could not plan query: {msg}")
    ok = cost <= ceiling
    err = None if ok else f"estimated cost {cost:,.0f} exceeds ceiling {ceiling:,.0f}"
    return CostResult(ok, cost, ceiling, err)


if __name__ == "__main__":
    q8 = (
        "SELECT c.name, SUM(p.amount) FROM payment p "
        "JOIN rental r ON p.rental_id = r.rental_id "
        "JOIN inventory i ON r.inventory_id = i.inventory_id "
        "JOIN film_category fc ON i.film_id = fc.film_id "
        "JOIN category c ON fc.category_id = c.category_id GROUP BY c.name"
    )
    queries = [
        ("cheap: COUNT(category)", "SELECT COUNT(*) FROM category"),
        ("normal: Q8 5-table join", q8),
        ("EXPENSIVE: rental x rental cross join", "SELECT COUNT(*) FROM rental r1, rental r2"),
    ]
    ceiling = DEFAULT_CEILING
    for label, sql in queries:
        res = cost_guard(sql, ceiling)
        print(f"[{'PASS ' if res.ok else 'BLOCK'}] cost={res.cost:>16,.1f}  ceiling={ceiling:>12,.0f}  {label}")
        if res.error:
            print(f"          {res.error}")
