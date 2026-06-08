"""
pipeline.py - InsightAgent v2 core pipeline orchestrator (steps 3-7).

    resolve (follow-up -> standalone)
       |
    ambiguity check --(vague)--> CLARIFY (one question + tappable options)
       |(clear)
    route? --catalog--> validate -> cost guard -> execute -> answer   (skips gen/self-check)
       |
       | generate path:
    retrieve -> generate -> validate --(fail)--> generate (retry once) -> validate
                               |(pass)
                               v
                          cost guard -> execute -> self-check -> answer

A clarification's tapped option becomes the next message and re-enters at resolve.
Returns one PipelineResult with SQL, rows, verdict, warnings, and a trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from insightagent.catalog import catalog_sql, route_to_catalog
from insightagent.clarify import check_ambiguity
from insightagent.cost import cost_guard
from insightagent.db import get_connection, get_schema
from insightagent.execution import execute_sql
from insightagent.generation import generate_sql_from_tables
from insightagent.resolver import resolve_question
from insightagent.retrieve import retrieve_tables
from insightagent.selfcheck import self_check
from insightagent.validation import validate_sql


@dataclass
class PipelineResult:
    question: str                  # what the user typed
    ok: bool
    stage: str                     # answer | clarification | validation | cost_guard | execution | self_check
    source: str = "generated"      # generated | catalog
    resolved: str = ""             # standalone question actually answered
    rewritten: bool = False
    clarify_question: str = ""
    clarify_options: list[str] = field(default_factory=list)
    sql: str | None = None
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    estimated_cost: float = 0.0
    warnings: list[str] = field(default_factory=list)
    self_check_reason: str = ""
    errors: list[str] = field(default_factory=list)
    retried: bool = False
    trace: list[str] = field(default_factory=list)


def answer_question(question: str, history: list[str] | None = None, k: int = 5) -> PipelineResult:
    trace: list[str] = []

    # resolve a follow-up into a standalone question (Level 1 continuity)
    rq = resolve_question(question, history)
    q = rq.text
    trace.append(f"resolve -> rewrote: {q!r}" if rq.rewritten else "resolve -> standalone (no rewrite)")

    # ambiguity check: if vague, ask ONE clarifying question instead of guessing
    clar = check_ambiguity(q)
    if clar.needs_clarification:
        trace.append(f"ambiguity -> CLARIFY ({clar.dimension})")
        return PipelineResult(question, False, "clarification", resolved=q, rewritten=rq.rewritten,
                              clarify_question=clar.question, clarify_options=clar.options, trace=trace)
    trace.append("ambiguity -> clear")

    with get_connection() as conn:
        schema = get_schema(conn)

    # 0. catalog routing: blessed SQL skips retrieval, generation, AND self-check.
    metric = route_to_catalog(q)
    if metric:
        sql = catalog_sql(metric)
        trace.append(f"route -> catalog:{metric} (skips retrieval/generation/self-check)")
        val = validate_sql(sql, schema=schema)
        if not val.ok:
            trace.append(f"validate -> FAILED {val.errors}")
            return PipelineResult(question, False, "validation", source="catalog", resolved=q,
                                  rewritten=rq.rewritten, sql=sql, warnings=list(val.warnings),
                                  errors=val.errors, trace=trace)
        trace.append("validate -> ok")
        cg = cost_guard(sql)
        if not cg.ok:
            trace.append(f"cost_guard -> BLOCK ({cg.error})")
            return PipelineResult(question, False, "cost_guard", source="catalog", resolved=q,
                                  rewritten=rq.rewritten, sql=sql, estimated_cost=cg.cost,
                                  errors=[cg.error or "cost too high"], trace=trace)
        trace.append(f"cost_guard -> ok (cost {cg.cost:,.0f})")
        result = execute_sql(sql)
        if not result.ok:
            trace.append(f"execute -> FAILED {result.error}")
            return PipelineResult(question, False, "execution", source="catalog", resolved=q,
                                  rewritten=rq.rewritten, sql=sql, estimated_cost=cg.cost,
                                  errors=[result.error or "execution failed"], trace=trace)
        trace.append(f"execute -> {result.row_count} row(s) in {result.elapsed_ms}ms")
        trace.append("self_check -> skipped (catalog SQL is trusted)")
        return PipelineResult(question, True, "answer", source="catalog", resolved=q,
                              rewritten=rq.rewritten, sql=sql, columns=result.columns,
                              rows=result.rows, row_count=result.row_count, truncated=result.truncated,
                              estimated_cost=cg.cost, warnings=list(val.warnings),
                              self_check_reason="skipped (catalog definition is trusted)", trace=trace)
    trace.append("route -> generate")

    # 1. retrieve
    retrieval = retrieve_tables(q, k=k)
    tables = retrieval.tables
    trace.append(f"retrieve -> {tables}")
    if retrieval.bridges:
        trace.append(f"   fk-bridge added: {', '.join(retrieval.bridges)}")

    # 2. generate
    sql = generate_sql_from_tables(q, tables)
    trace.append("generate -> SQL produced")

    # 3. validate, retrying generation once on failure
    val = validate_sql(sql, schema=schema)
    retried = False
    if not val.ok:
        trace.append(f"validate -> FAILED {val.errors}; retrying generation with feedback")
        sql = generate_sql_from_tables(q, tables, repair=(sql, val.errors))
        val = validate_sql(sql, schema=schema)
        retried = True
        trace.append(f"validate(retry) -> {'ok' if val.ok else 'FAILED ' + str(val.errors)}")
    else:
        trace.append("validate -> ok")
    warnings = list(val.warnings)

    if not val.ok:
        return PipelineResult(question, False, "validation", resolved=q, rewritten=rq.rewritten,
                              sql=sql, tables=tables, warnings=warnings, errors=val.errors,
                              retried=retried, trace=trace)

    # 3b. cost guard (between validation and execution)
    cg = cost_guard(sql)
    if not cg.ok:
        trace.append(f"cost_guard -> BLOCK ({cg.error})")
        return PipelineResult(question, False, "cost_guard", resolved=q, rewritten=rq.rewritten,
                              sql=sql, tables=tables, warnings=warnings, estimated_cost=cg.cost,
                              errors=[cg.error or "cost too high"], retried=retried, trace=trace)
    trace.append(f"cost_guard -> ok (cost {cg.cost:,.0f})")

    # 4. execute
    result = execute_sql(sql)
    if not result.ok:
        trace.append(f"execute -> FAILED {result.error}")
        return PipelineResult(question, False, "execution", resolved=q, rewritten=rq.rewritten,
                              sql=sql, tables=tables, warnings=warnings, estimated_cost=cg.cost,
                              errors=[result.error or "execution failed"], retried=retried, trace=trace)
    trace.append(f"execute -> {result.row_count} row(s) in {result.elapsed_ms}ms")

    # 5. self-check (against the resolved standalone question)
    sc = self_check(q, sql, result)
    warnings += sc.warnings
    trace.append(f"self_check -> {'pass' if sc.ok else 'FAIL'}: {sc.reason}")

    return PipelineResult(
        question, sc.ok, "answer" if sc.ok else "self_check", resolved=q, rewritten=rq.rewritten,
        sql=sql, tables=tables, columns=result.columns, rows=result.rows,
        row_count=result.row_count, truncated=result.truncated, estimated_cost=cg.cost,
        warnings=warnings, self_check_reason=sc.reason, retried=retried, trace=trace,
    )


if __name__ == "__main__":
    for q in [
        "What is the total revenue across all stores?",     # catalog path
        "Which film category generated the most revenue?",   # generate path
    ]:
        r = answer_question(q)
        print("=" * 72)
        print(f"Q: {q}")
        print(f"   source={r.source}  stage={r.stage}  ok={r.ok}  est_cost={r.estimated_cost:,.0f}  rows={r.rows[:2]}")
        for t in r.trace:
            print(f"      {t}")
