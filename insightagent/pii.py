"""
pii.py - InsightAgent v2 PII policy (step 3 guardrail, enforced in validation.py).

Tiered column policy, classified by bare column name (unambiguous in Pagila):

  SECRET     password, picture                      -> blocked anywhere (error)
  RESTRICTED email, phone, address, address2,        -> blocked in SELECT output;
             postal_code                                allowed only as filter/join
  IDENTITY   first_name, last_name                   -> allowed, but flagged (warning)

Names are IDENTITY (allowed, not blocked) on purpose: Q5 ("California customers
with >30 rentals") legitimately returns customer names. We surface the answer but
flag that it carries personal data. SELECT * / t.* over a table holding
RESTRICTED/SECRET columns is blocked so it can't smuggle PII past the column list.
A PII column wrapped in COUNT(...) is not treated as output exposure (counting is
not leaking); MIN/MAX/STRING_AGG etc. over PII ARE treated as exposure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp

SECRET = {"password", "picture"}
RESTRICTED = {"email", "phone", "address", "address2", "postal_code"}
IDENTITY = {"first_name", "last_name"}


@dataclass
class PiiReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _projection_column_ids(root) -> set[int]:
    """ids of Column nodes that sit in some SELECT's output projection list."""
    ids: set[int] = set()
    for sel in root.find_all(exp.Select):
        for proj in sel.expressions:
            for col in proj.find_all(exp.Column):
                ids.add(id(col))
    return ids


def _has_select_star(root) -> bool:
    """True for a real projection star (SELECT * / t.*), but NOT for COUNT(*)."""
    for sel in root.find_all(exp.Select):
        for proj in sel.expressions:
            if isinstance(proj, exp.Star):
                return True
            if isinstance(proj, exp.Column) and isinstance(proj.args.get("this"), exp.Star):
                return True
    return False


def check_pii(root, referenced: set[str], schema: dict[str, set[str]]) -> PiiReport:
    rep = PiiReport()
    proj_ids = _projection_column_ids(root)

    secret_hit: set[str] = set()
    restricted_out: set[str] = set()
    identity_out: set[str] = set()
    for col in root.find_all(exp.Column):
        name = (col.name or "").lower()
        if name in SECRET:
            secret_hit.add(name)
        elif name in RESTRICTED or name in IDENTITY:
            # "exposed" = an output value that is not merely being counted
            counted = col.find_ancestor(exp.Count) is not None
            if id(col) in proj_ids and not counted:
                (restricted_out if name in RESTRICTED else identity_out).add(name)

    if _has_select_star(root):
        star_cols = set().union(*(schema[t] for t in referenced if t in schema)) if referenced else set()
        if star_cols & (SECRET | RESTRICTED):
            rep.errors.append("SELECT * would expose secret/PII columns; list output columns explicitly")
        elif star_cols & IDENTITY:
            rep.warnings.append("result includes personal names (via SELECT *)")

    if secret_hit:
        rep.errors.append(f"references secret column(s): {', '.join(sorted(secret_hit))}")
    if restricted_out:
        rep.errors.append(
            f"contact PII not allowed in output: {', '.join(sorted(restricted_out))} "
            "(you may filter/join on them, not return them)"
        )
    if identity_out:
        rep.warnings.append(f"result includes personal names: {', '.join(sorted(identity_out))}")
    return rep
