"""
summary.py - InsightAgent v2 one-line answer summary (for the UI answer card).

The pipeline returns rows; the wireframe's answer card opens with a plain-English
sentence. This turns (question, result table) into one sentence stating the
actual numbers, the way a data analyst would phrase the answer.
"""
from __future__ import annotations

from llm import complete

_SYSTEM = """You write ONE concise, plain-English sentence answering a business user's
question from a SQL result. State the actual number(s)/name(s) from the result.
No preamble, no markdown - just the sentence."""


def summarize_answer(question: str, columns: list[str], rows: list[tuple], max_rows: int = 15) -> str:
    if not rows:
        return "The query returned no rows."
    head = rows[:max_rows]
    table = " | ".join(columns) + "\n" + "\n".join(" | ".join(str(c) for c in r) for r in head)
    user = f"Question: {question}\n\nResult:\n{table}\n\nOne-sentence answer:"
    try:
        return complete(user, system=_SYSTEM, max_tokens=80).strip()
    except Exception:
        if len(head) == 1 and len(head[0]) == 1:        # single scalar fallback
            return f"{columns[0]}: {head[0][0]}"
        return "Here are the results."
