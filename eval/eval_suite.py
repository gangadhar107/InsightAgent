"""
eval_suite.py - InsightAgent v2 evaluation harness (PRD section 7).

Runs all 12 eval questions through answer_question() and scores two things
separately (so a failure is diagnosable as bad retrieval vs bad generation):

  * Answer accuracy    - final answer vs hand-verified ground truth.
        counts/whole numbers: exact;  money/averages: within 0.01;
        Q12 (ambiguity): pass iff the agent clarifies instead of answering.
  * Retrieval accuracy - did retrieval fetch the tables the question needs?
        (generate-path questions only; catalog + ambiguity skip retrieval = n/a)
"""
from __future__ import annotations

from decimal import Decimal

from insightagent.pipeline import answer_question


def _nums(r) -> list[float]:
    return [float(c) for row in r.rows for c in row
            if isinstance(c, (int, float, Decimal)) and not isinstance(c, bool)]


def _has(r, n, tol=1e-9) -> bool:
    return any(abs(x - n) <= tol for x in _nums(r))


def _text(r) -> str:
    return " ".join(str(c) for row in r.rows for c in row).lower()


# id, question, answer-check, expected_tables (None => retrieval n/a), ground-truth label
EVAL = [
    (1, "What is the total revenue across all stores?",
     lambda r: _has(r, 67416.51, 0.01), None, "67416.51"),
    (2, "How many active customers are there?",
     lambda r: _has(r, 584), None, "584"),
    (3, "What is the average payment amount?",
     lambda r: _has(r, 4.20, 0.01), None, "4.20"),
    (4, "How many R-rated films are in the Action category?",
     lambda r: _has(r, 14), {"film", "film_category", "category"}, "14"),
    (5, "Which customers in California have made more than 30 rentals?",
     lambda r: r.row_count == 2 and _has(r, 33) and _has(r, 31),
     {"customer", "address", "rental"}, "2 (Stewart 33, Johnston 31)"),
    (6, "What is the average rental rate for Comedy films?",
     lambda r: _has(r, 3.16, 0.01), {"film", "film_category", "category"}, "3.16"),
    (7, "How many rentals happened in February 2022?",
     lambda r: _has(r, 182), {"rental"}, "182"),
    (8, "Which film category generated the most revenue?",
     lambda r: "sports" in _text(r),
     {"payment", "rental", "inventory", "film_category", "category"}, "Sports"),
    (9, "How many films have never been rented?",
     lambda r: _has(r, 42), {"film", "inventory", "rental"}, "42"),
    (10, "How did rental volume in July 2022 compare to June 2022?",
     lambda r: _has(r, 6594) and _has(r, 2331), {"rental"}, "Jul 6594 / Jun 2331"),
    (11, "Which store had higher revenue, store 1 or store 2?",
     lambda r: abs(max([x for x in _nums(r) if x > 1000], default=0) - 33927.04) <= 0.01,
     {"payment", "staff"}, "store 2 (33927.04)"),
    (12, "What's our revenue?",
     lambda r: r.stage == "clarification", None, "clarify"),
]


def main() -> None:
    ans_pass = 0
    ret_total = ret_pass = 0
    detail = []
    print(f"{'#':>2}  {'answer':6}  {'retrieval':18}  {'source':9}  stage")
    print("-" * 60)
    for qid, question, check, expected, gt in EVAL:
        r = answer_question(question)
        a_ok = bool(check(r))
        ans_pass += a_ok
        if expected is None:
            ret = "n/a"
        else:
            ret_total += 1
            missing = expected - set(r.tables)
            ok = not missing
            ret_pass += ok
            ret = "PASS" if ok else f"MISS {sorted(missing)}"
        print(f"{qid:>2}  {'PASS' if a_ok else 'FAIL':6}  {ret:18}  {r.source:9}  {r.stage}")
        if (not a_ok) or (expected is not None and (expected - set(r.tables))):
            got = r.rows[:3] if r.rows else (r.clarify_question or r.errors)
            detail.append(f"  Q{qid}: want {gt!r}; got {got}; tables={r.tables}; stage={r.stage}")

    print("-" * 60)
    print(f"Answer accuracy:    {ans_pass}/{len(EVAL)}")
    print(f"Retrieval accuracy: {ret_pass}/{ret_total} (generate-path only)")
    if detail:
        print("\nFailures / misses:")
        print("\n".join(detail))


if __name__ == "__main__":
    main()
