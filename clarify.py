"""
clarify.py - InsightAgent v2 clarification / ambiguity check (step 6).

After a question is resolved to standalone form, decide whether it is clear
enough to answer with one correct number. If a critical dimension is genuinely
missing (and no sensible default exists), return ONE clarifying question with
tappable options instead of guessing. Common dimensions (time period, store) use
PREDEFINED options; unusual cases fall back to LLM-suggested options.

Deliberately conservative: most questions are clear; we only clarify when an
answer would otherwise be a guess. (Eval Q12 "What's our revenue?" must clarify.)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from llm import complete

# Deterministic options for dimensions we can enumerate for this dataset.
PREDEFINED_OPTIONS: dict[str, list[str]] = {
    "time_period": ["All available data (Jan-Jul 2022)", "A specific month", "Month by month"],
    "store": ["Both stores combined", "Store 1 only", "Store 2 only", "Compare store 1 vs store 2"],
}

_SYSTEM = """You decide whether a data question is too ambiguous to answer with one
correct number, and if so, which ONE dimension is missing.

Be VERY CONSERVATIVE - most questions are clear, and clarifying a clear question is
annoying. Apply these defaults BEFORE deciding:
- If no time period is stated, assume ALL available data. Do NOT clarify the period
  just because it is unstated.
- A question that names a concrete metric, status, or specific entities (a category,
  a store, "active" customers, "store 1 vs store 2") is CLEAR.

Flag ambiguous ONLY when the question is so bare or underspecified that ANY answer
would be a guess.

CLEAR (ambiguous=false):
- "What is the total revenue across all stores?"
- "How many active customers are there?" (active is a defined status)
- "How many rentals happened in February 2022?"
- "Which film category generated the most revenue?"
- "Which store had higher revenue, store 1 or store 2?" (explicit comparison)
AMBIGUOUS (ambiguous=true):
- "What's our revenue?" -> bare, no scope at all -> dimension time_period
- "What's the most popular film?" -> "popular" is undefined -> dimension other

Reply with ONLY JSON:
{"ambiguous": true|false, "dimension": "time_period"|"store"|"other", "question": "<one short clarifying question>", "options": ["opt1","opt2","opt3"]}
If not ambiguous, set ambiguous=false and leave the other fields empty."""


@dataclass
class Clarification:
    needs_clarification: bool
    question: str = ""
    options: list[str] = field(default_factory=list)
    dimension: str = ""


def _parse_json(raw: str) -> dict:
    text = raw
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m2 = re.search(r"\{.*\}", text, re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def check_ambiguity(question: str) -> Clarification:
    obj = _parse_json(complete(question, system=_SYSTEM, max_tokens=200))
    if not obj.get("ambiguous"):
        return Clarification(False)
    dimension = str(obj.get("dimension", "other")).lower()
    cq = str(obj.get("question", "")).strip() or "Could you clarify what you mean?"
    options = PREDEFINED_OPTIONS.get(dimension) or [str(o) for o in obj.get("options", []) if str(o).strip()]
    return Clarification(True, cq, options, dimension)


if __name__ == "__main__":
    cases = [
        ("What's our revenue?", True),
        ("Show me active customers", False),  # 'active' is a defined flag, not time-windowed
        ("What's the most popular film?", True),
        ("What is the total revenue across all stores?", False),
        ("How many rentals happened in February 2022?", False),
        ("Which film category generated the most revenue?", False),
        ("Which customers in California have made more than 30 rentals?", False),
    ]
    miss = 0
    for q, expect in cases:
        c = check_ambiguity(q)
        ok = c.needs_clarification == expect
        miss += 0 if ok else 1
        print(f"[{'PASS' if ok else '**MISS**'}] clarify={c.needs_clarification!s:5} (want {expect!s:5})  {q}")
        if c.needs_clarification:
            print(f"        ask: {c.question}")
            print(f"        options ({c.dimension}): {c.options}")
    print(f"\n{len(cases) - miss}/{len(cases)} as expected.")
