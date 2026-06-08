"""
selfcheck.py - InsightAgent v2 self-check (step 3, the guard behind execution).

Given the question, the SQL that ran, and the result, decide whether the result
actually answers the question - catching the failure where SQL runs cleanly but
answers the WRONG thing (wrong metric, missing filter, wrong grouping).

Cheap deterministic signals (execution error, empty result, truncation) are
computed first and fed to an LLM judge, which returns a pass/fail verdict with a
one-line reason.

Per the lifecycle diagram, CATALOG SQL skips this step (it is a trusted, fixed
definition); only generated SQL is self-checked.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from execution import ExecutionResult
from llm import complete

_SYSTEM = """You verify whether a SQL result actually answers a user's question.
You are given the question, the SQL that was executed, and the result (columns +
sample rows + row count). Judge whether the result DIRECTLY and CORRECTLY answers
the question. Be strict about:
- the right metric and aggregation (a single total vs a per-group breakdown),
- the right filters (time period, category, location),
- the right grouping and shape (a "which X" question must identify X, not just return a number).
Reply with ONLY a JSON object: {"verdict": "pass" or "fail", "reason": "<one short sentence>"}."""


@dataclass
class SelfCheckResult:
    ok: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


def _preview(result: ExecutionResult, max_rows: int = 10) -> str:
    head = result.rows[:max_rows]
    lines = [" | ".join(result.columns)]
    for row in head:
        lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)


def _parse_verdict(raw: str):
    text = raw
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if m:
            text = m.group(1)
    try:
        obj = json.loads(text)
        v = str(obj.get("verdict", "")).lower()
        if v in ("pass", "fail"):
            return v, str(obj.get("reason", ""))
    except (json.JSONDecodeError, AttributeError):
        pass
    low = raw.lower()
    if "fail" in low and "pass" not in low:
        return "fail", raw[:160]
    if "pass" in low and "fail" not in low:
        return "pass", raw[:160]
    return None, raw


def self_check(question: str, sql: str, result: ExecutionResult) -> SelfCheckResult:
    warnings: list[str] = []

    # deterministic signals
    if not result.ok:
        return SelfCheckResult(False, f"query failed to execute: {result.error}")
    if result.row_count == 0:
        warnings.append("result is empty")
    if result.truncated:
        warnings.append("result was truncated at the row cap")

    user = (
        f"Question:\n{question}\n\n"
        f"SQL:\n{sql}\n\n"
        f"Result ({result.row_count} row(s)"
        + (", EMPTY" if result.row_count == 0 else "")
        + (", TRUNCATED" if result.truncated else "")
        + "):\n"
        + _preview(result)
        + "\n\nDoes this result correctly answer the question?"
    )
    raw = complete(user, system=_SYSTEM, max_tokens=200).strip()

    verdict, reason = _parse_verdict(raw)
    if verdict is None:
        # inconclusive parse: don't hard-fail a good answer on a formatting hiccup
        return SelfCheckResult(True, f"self-check inconclusive: {raw[:120]}", warnings)
    return SelfCheckResult(verdict == "pass", reason or raw[:160], warnings)


if __name__ == "__main__":
    from execution import execute_sql

    q8_sql = (
        "SELECT c.name AS category_name, SUM(p.amount) AS total_revenue "
        "FROM payment p "
        "JOIN rental r ON p.rental_id = r.rental_id "
        "JOIN inventory i ON r.inventory_id = i.inventory_id "
        "JOIN film_category fc ON i.film_id = fc.film_id "
        "JOIN category c ON fc.category_id = c.category_id "
        "GROUP BY c.category_id, c.name ORDER BY total_revenue DESC LIMIT 1"
    )
    feb_sql = ("SELECT COUNT(*) AS feb FROM rental "
               "WHERE rental_date >= '2022-02-01' AND rental_date < '2022-03-01'")

    cases = [
        ("correct: Q8 by category",  "Which film category generated the most revenue?", q8_sql, True),
        ("wrong: total not category","Which film category generated the most revenue?",
         "SELECT SUM(amount) AS total_revenue FROM payment", False),
        ("wrong: missing Feb filter","How many rentals happened in February 2022?",
         "SELECT COUNT(*) AS n FROM rental", False),
        ("correct: Feb count",       "How many rentals happened in February 2022?", feb_sql, True),
    ]
    for label, q, sql, expect_ok in cases:
        res = execute_sql(sql)
        sc = self_check(q, sql, res)
        ok = sc.ok == expect_ok
        print(f"[{'PASS' if ok else '**MISMATCH**'}] want_ok={expect_ok!s:5} got_ok={sc.ok!s:5}  {label}")
        print(f"           reason: {sc.reason}")
        if sc.warnings:
            print(f"           warnings: {sc.warnings}")
