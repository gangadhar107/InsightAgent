"""
generation.py - InsightAgent v2 SQL generation (step 3).

Turns a natural-language question into a single read-only SELECT. It retrieves
the relevant tables (retrieve.py), gathers their real columns and foreign-key
join paths from the catalog (db.py), hands the LLM that focused schema, and
returns the SQL. It does NOT validate or execute - those are the next pieces.
The guard behind this model step is the validator.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from db import get_connection, get_columns, get_fk_join_edges
from llm import complete
from retrieve import retrieve_tables
from table_descriptions import TABLE_DESCRIPTIONS

_SYSTEM = """You are a careful analytics engineer writing PostgreSQL for the Pagila
DVD-rental database. Given a question and the relevant tables (their columns,
plain-language descriptions, and foreign-key joins), write exactly ONE query that
answers it.

Rules:
- Read-only: a single SELECT or WITH ... SELECT. Never INSERT/UPDATE/DELETE, DDL,
  or transaction control.
- Use ONLY the tables and columns provided; never invent columns.
- Join only via the listed foreign-key relationships.
- For month/date filters use half-open ranges on the timestamp column, e.g.
  d >= '2022-07-01' AND d < '2022-08-01'.
- Privacy: never select staff.password or staff.picture; never return contact PII
  (email, phone, address, address2, postal_code) as output columns (you may filter
  or join on them). Returning customer/staff names is allowed when asked.
- Output ONLY the SQL - no prose, no markdown fences."""


@dataclass
class Generated:
    question: str
    tables: list[str]
    sql: str


def _extract_sql(text: str) -> str:
    """Pull SQL from the reply, tolerating an accidental ```sql fence."""
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip()


def _schema_context(conn, tables: list[str]) -> tuple[str, str]:
    cols = get_columns(conn, tables)
    edges = get_fk_join_edges(conn, tables)
    blocks = []
    for t in tables:
        desc = TABLE_DESCRIPTIONS.get(t, "")
        collist = ", ".join(f"{c} ({ty})" for c, ty in cols.get(t, []))
        blocks.append(f"TABLE {t} - {desc}\n    columns: {collist}")
    joins = "\n".join(f"- {s}.{sc} = {tt}.{tc}" for s, sc, tt, tc in edges)
    return "\n".join(blocks), (joins or "- (no foreign keys among these tables)")


def generate_sql_from_tables(question: str, tables: list[str],
                             repair: tuple[str, list[str]] | None = None) -> str:
    """Generate one SELECT for a question given a fixed set of tables. If `repair`
    is provided (previous_sql, validation_errors), the prompt asks the model to
    fix that specific failure - this is what makes the validate->retry loop useful
    instead of reproducing the same rejected SQL."""
    with get_connection() as conn:
        schema_block, joins = _schema_context(conn, tables)
    user = (
        f"Question: {question}\n\n"
        f"Relevant tables:\n{schema_block}\n\n"
        f"Foreign-key joins you can use:\n{joins}\n\n"
        f"Write the single SQL query."
    )
    if repair is not None:
        prev_sql, errors = repair
        user += (
            "\n\nYour previous attempt was REJECTED before running:\n"
            f"{prev_sql}\n"
            f"Reasons: {'; '.join(errors)}\n"
            "Write a corrected single SQL query that fixes these problems."
        )
    return _extract_sql(complete(user, system=_SYSTEM, max_tokens=700))


def generate_sql(question: str, k: int = 5) -> Generated:
    """Retrieve tables, then generate one SELECT (convenience wrapper)."""
    res = retrieve_tables(question, k=k)
    sql = generate_sql_from_tables(question, res.tables)
    return Generated(question=question, tables=res.tables, sql=sql)


if __name__ == "__main__":
    for q in [
        "What is the total revenue across all stores?",     # easy (catalog-style)
        "Which film category generated the most revenue?",   # hard 5-table chain (Q8)
    ]:
        g = generate_sql(q)
        print(f"\n### {q}")
        print(f"# retrieved tables: {g.tables}")
        print(g.sql)
