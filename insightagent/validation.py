"""
validation.py - InsightAgent v2 SQL validation (step 3: the guard behind generation).

Checks that generated SQL is safe to run BEFORE it reaches the database:
  1. Parses (rejects garbage).
  2. Exactly one statement (blocks "SELECT 1; DROP TABLE ...").
  3. Read-only: root is a query and NO data-modifying/DDL node anywhere
     (catches a DELETE hidden inside a CTE).
  4. Real tables: every referenced table exists in the public schema.
  5. Real columns (best-effort): qualified columns must exist on their table;
     unqualified columns in simple queries must exist on a referenced table or be
     a SELECT alias. Ambiguous scopes (CTEs/subqueries) are skipped.
  6. PII policy (pii.py): block secrets anywhere, block contact PII in output,
     flag identity columns (names). Errors reject; warnings are advisory.

On failure the pipeline retries generation once (per the lifecycle diagram).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from insightagent.db import get_connection, get_schema
from insightagent.pii import check_pii

# Data-modifying / DDL node types that must never appear (even inside a CTE).
_FORBIDDEN_NAMES = ["Insert", "Update", "Delete", "Merge", "Create", "Drop",
                    "Alter", "TruncateTable", "Command", "Grant"]
_FORBIDDEN = tuple(getattr(exp, n) for n in _FORBIDDEN_NAMES if hasattr(exp, n))

# Acceptable top-level node types (all read-only).
_QUERY_ROOTS = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_sql(sql: str, schema: dict[str, set[str]] | None = None) -> ValidationResult:
    # 1. parse
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except ParseError as e:
        return ValidationResult(False, [f"could not parse SQL: {str(e).splitlines()[0]}"])

    # 2. exactly one statement
    if not statements:
        return ValidationResult(False, ["empty SQL"])
    if len(statements) > 1:
        return ValidationResult(False, [f"expected one statement, got {len(statements)}"])
    root = statements[0]

    # 3. read-only
    if not isinstance(root, _QUERY_ROOTS):
        return ValidationResult(False, [f"not a read-only query (got {type(root).__name__})"])
    forbidden = next(root.find_all(*_FORBIDDEN), None)
    if forbidden is not None:
        return ValidationResult(False, [f"forbidden statement type: {type(forbidden).__name__}"])

    # catalog needed for table/column/PII checks
    if schema is None:
        with get_connection() as conn:
            schema = get_schema(conn)

    errors: list[str] = []
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}

    # 4. real tables (and build alias -> real-table map)
    alias_map: dict[str, str] = {}
    referenced: set[str] = set()
    for tbl in root.find_all(exp.Table):
        name = tbl.name.lower()
        alias = (tbl.alias_or_name or tbl.name).lower()
        alias_map[alias] = name
        if name in cte_names:
            continue
        referenced.add(name)
        if name not in schema:
            errors.append(f"unknown table: {tbl.name}")

    # 5. real columns (best-effort)
    output_aliases = {
        proj.alias.lower()
        for sel in root.find_all(exp.Select)
        for proj in sel.expressions
        if isinstance(proj, exp.Alias)
    }
    complex_query = len(list(root.find_all(exp.Select))) > 1 or bool(cte_names)
    known_cols: set[str] = set().union(
        *(schema[t] for t in referenced if t in schema)
    ) if referenced else set()

    for col in root.find_all(exp.Column):
        cname = (col.name or "").lower()
        if not cname or cname == "*":
            continue
        qual = (col.table or "").lower()
        if qual:
            real = alias_map.get(qual, qual)
            if real in cte_names:
                continue
            if real in schema and cname not in schema[real]:
                errors.append(f"unknown column: {col.table}.{col.name}")
        else:
            if complex_query:
                continue
            if cname not in known_cols and cname not in output_aliases:
                errors.append(f"unknown column: {col.name}")

    # 6. PII policy
    pii = check_pii(root, referenced, schema)
    errors.extend(pii.errors)

    return ValidationResult(not errors, errors, pii.warnings)


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
    q5 = (
        "SELECT c.customer_id, c.first_name, c.last_name, COUNT(r.rental_id) AS rental_count "
        "FROM customer c "
        "JOIN address a ON a.address_id = c.address_id "
        "JOIN rental r ON r.customer_id = c.customer_id "
        "WHERE a.district = 'California' "
        "GROUP BY c.customer_id, c.first_name, c.last_name "
        "HAVING COUNT(r.rental_id) > 30 ORDER BY rental_count DESC"
    )
    cases = [
        ("valid: simple SELECT",       "SELECT SUM(amount) AS total FROM payment", True),
        ("valid: Q8 join chain",       q8, True),
        ("valid: CTE",                 "WITH r AS (SELECT amount FROM payment) SELECT SUM(amount) AS t FROM r", True),
        ("valid: ORDER BY alias",      "SELECT c.name AS cat, COUNT(*) AS n FROM category c GROUP BY c.name ORDER BY n DESC", True),
        ("reject: DELETE",             "DELETE FROM rental", False),
        ("reject: UPDATE",             "UPDATE film SET rental_rate = 0", False),
        ("reject: DROP",               "DROP TABLE rental", False),
        ("reject: INSERT",             "INSERT INTO category (name) VALUES ('x')", False),
        ("reject: TRUNCATE",           "TRUNCATE TABLE rental", False),
        ("reject: multi-statement",    "SELECT 1; DROP TABLE rental", False),
        ("reject: data-modifying CTE", "WITH x AS (DELETE FROM rental RETURNING rental_id) SELECT * FROM x", False),
        ("reject: unknown table",      "SELECT * FROM sales", False),
        ("reject: unknown column",     "SELECT bogus_col FROM payment", False),
        ("reject: empty",              "", False),
        # --- PII policy ---
        ("PII allow: filter by email",    "SELECT customer_id FROM customer WHERE email = 'x@y.com'", True),
        ("PII reject: email in output",   "SELECT first_name, email FROM customer", False),
        ("PII reject: staff.password",    "SELECT staff_id, password FROM staff", False),
        ("PII reject: SELECT * customer", "SELECT * FROM customer", False),
        ("PII allow: SELECT * category",  "SELECT * FROM category", True),
        ("PII allow: COUNT(email)",       "SELECT COUNT(email) AS n FROM customer", True),
        ("PII warn: Q5 names",            q5, True),
    ]
    with get_connection() as conn:
        schema = get_schema(conn)
    print(f"loaded catalog: {len(schema)} public tables/views\n")
    mismatches = 0
    for label, sql, expect_ok in cases:
        res = validate_sql(sql, schema=schema)
        ok = res.ok == expect_ok
        mismatches += 0 if ok else 1
        print(f"[{'PASS' if ok else '**MISMATCH**'}] want_ok={expect_ok!s:5} got_ok={res.ok!s:5}  {label}")
        if res.errors:
            print(f"            err:  {res.errors}")
        if res.warnings:
            print(f"            warn: {res.warnings}")
    print(f"\n{len(cases) - mismatches}/{len(cases)} behaved as expected.")
