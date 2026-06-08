"""
resolver.py - InsightAgent v2 follow-up resolver (step 5, Level 1 continuity).

Rewrites the user's latest message into a STANDALONE question using recent
history, so the rest of the pipeline (routing, retrieval, generation) only ever
sees a self-contained question. Runs FIRST, before routing.

  history = ["how many rentals did store 1 handle in July 2022?", ...]
            (prior *resolved* questions, most recent last)
  "what about store 2?"  ->  "how many rentals did store 2 handle in July 2022?"

Deliberately conservative: a message that already stands alone, or that changes
topic, is returned unchanged - we never graft on context the user did not imply.
"""
from __future__ import annotations

from dataclasses import dataclass

from llm import complete

_SYSTEM = """You rewrite a user's latest message into a STANDALONE question understandable
with no conversation history, by filling in context the message clearly refers back to
(entities, time periods, metrics).

Rules:
- If the latest message already stands alone, return it UNCHANGED.
- Only carry over context the latest message clearly refers to: pronouns (it, they,
  that, those) or ellipsis ("what about X", "and for Y", "by month instead").
- Do NOT add filters, time periods, or details the user did not imply.
- If the latest message changes topic, treat it as standalone.
- Return ONLY the question text - no quotes, no preamble, no explanation."""


@dataclass
class ResolvedQuestion:
    text: str
    rewritten: bool
    original: str


def _normalize(s: str) -> str:
    return " ".join(s.lower().split()).rstrip("?.")


def resolve_question(question: str, history: list[str] | None = None) -> ResolvedQuestion:
    """Rewrite `question` to stand alone using `history` (prior resolved questions,
    most recent last). With no history, the question is returned unchanged."""
    history = history or []
    if not history:
        return ResolvedQuestion(question, False, question)

    convo = "\n".join(f"{i}. {h}" for i, h in enumerate(history, 1))
    user = (
        f"Conversation so far (most recent last):\n{convo}\n\n"
        f"Latest message: {question}\n\n"
        f"Rewrite the latest message as a standalone question:"
    )
    resolved = complete(user, system=_SYSTEM, max_tokens=120).strip().strip('"').strip()
    resolved = resolved or question
    return ResolvedQuestion(resolved, _normalize(resolved) != _normalize(question), question)


if __name__ == "__main__":
    cases = [
        (["How many rentals did store 1 handle in July 2022?"],
         "What about store 2?", True, "store 2"),
        (["What is the total revenue in July 2022?"],
         "And in June?", True, "june"),
        (["How many active customers are there?"],
         "Which film category generated the most revenue?", False, None),  # topic change
        ([],
         "What is the total revenue across all stores?", False, None),     # no history
        (["What is the total revenue across all stores?"],
         "How many rentals happened in February 2022?", False, None),      # complete -> leave alone
    ]
    miss = 0
    for history, q, expect_rw, substr in cases:
        r = resolve_question(q, history)
        ok = (r.rewritten == expect_rw) and (substr is None or substr.lower() in r.text.lower())
        miss += 0 if ok else 1
        print(f"[{'PASS' if ok else '**MISS**'}] rewritten={r.rewritten!s:5} (want {expect_rw!s:5})")
        print(f"        history: {history}")
        print(f"        '{q}'  ->  '{r.text}'")
    print(f"\n{len(cases) - miss}/{len(cases)} as expected.")
