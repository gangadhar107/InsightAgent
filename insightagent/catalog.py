"""
catalog.py - InsightAgent v2 catalog routing (step 4).

A small set of blessed, human-written metric definitions. If a question asks for
exactly one of these (no extra filter/dimension/comparison/time window), the
pipeline uses the fixed SQL instead of retrieval+generation - and, because the
definition is trusted, skips the self-check. Anything else falls through to the
generated-SQL path.

Routing is an LLM intent classifier kept deliberately STRICT: a false route gives
a confidently wrong answer, whereas a miss just falls back to generation (which
handles it). So when unsure, it returns 'none'.
"""
from __future__ import annotations

from insightagent.llm import complete

CATALOG: dict[str, dict[str, str]] = {
    "total_revenue": {
        "description": "Total revenue / total sales across the whole business (sum of every payment).",
        "sql": "SELECT SUM(amount) AS total_revenue FROM payment;",
    },
    "active_customers": {
        "description": "The count of currently active customers.",
        "sql": "SELECT COUNT(*) AS active_customers FROM customer WHERE active = 1;",
    },
    "avg_payment": {
        "description": "The average payment amount per transaction.",
        "sql": "SELECT ROUND(AVG(amount), 2) AS avg_payment_amount FROM payment;",
    },
}

_SYSTEM = (
    "You route a user question to a known business metric, or to 'none'.\n"
    "Return a metric KEY only if the question asks for exactly that metric with NO "
    "extra filter, dimension, grouping, comparison, or time window. If it adds any "
    "of those, return 'none' (it is handled elsewhere).\n"
    "Examples: \"what's our total revenue\" -> total_revenue; "
    "\"revenue for store 1\" -> none (filter); "
    "\"which store had more revenue\" -> none (comparison); "
    "\"revenue in March\" -> none (time window).\n"
    "Reply with ONLY the key or the word none."
)


def route_to_catalog(question: str) -> str | None:
    """Return a catalog metric key if the question is exactly that metric, else None."""
    metrics = "\n".join(f"- {k}: {v['description']}" for k, v in CATALOG.items())
    user = f"Known metrics:\n{metrics}\n\nQuestion: {question}\n\nAnswer:"
    reply = complete(user, system=_SYSTEM, max_tokens=16).strip().lower()
    token = reply.split()[0].strip(".,'\"") if reply.split() else ""
    if token in CATALOG:
        return token
    for k in CATALOG:           # tolerate a slightly chatty reply
        if k in reply:
            return k
    return None


def catalog_sql(metric: str) -> str:
    return CATALOG[metric]["sql"]


if __name__ == "__main__":
    tests = [
        ("What is the total revenue across all stores?", "total_revenue"),
        ("How much money did we make in total?", "total_revenue"),
        ("How many active customers are there?", "active_customers"),
        ("What's the average payment amount?", "avg_payment"),
        ("Which store had higher revenue, store 1 or store 2?", None),  # comparison
        ("What is the total revenue for store 1?", None),               # filter
        ("How many rentals happened in February 2022?", None),          # different metric
        ("Which film category generated the most revenue?", None),      # dimension
    ]
    miss = 0
    for q, expected in tests:
        got = route_to_catalog(q)
        ok = got == expected
        miss += 0 if ok else 1
        print(f"[{'PASS' if ok else '**MISS**'}] route={str(got):16} expected={str(expected):16} {q}")
    print(f"\n{len(tests) - miss}/{len(tests)} routed as expected.")
