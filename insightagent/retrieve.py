"""
retrieve.py - InsightAgent v2 semantic schema retrieval (step 2 piece 3 + step 3 hardening).

Given a natural-language question, return the database tables most likely needed
to answer it. Two stages:

  1. Semantic: embed the question (RETRIEVAL_QUERY) and rank the 15 stored
     table-description vectors by cosine similarity; take the top-k as the seed.
  2. FK-graph expansion: the seed may be missing intermediate "join bridge"
     tables the question never names (e.g. Q8 names category + revenue but needs
     `rental` to connect payment -> inventory). We add a non-seed table only if
     it connects two otherwise-disconnected pieces of the seed in the foreign-key
     graph. That recovers the bridges without dragging in unrelated hub tables.

Vectors are unit-normalized so cosine == dot, but we compute full cosine to be
safe. With ~15 rows everything is exact in Python; no ANN index needed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from insightagent.db import get_connection
from insightagent.embedding import embed_text


@dataclass
class TableMatch:
    table_name: str
    score: float


@dataclass
class RetrievalResult:
    question: str
    seed: list[TableMatch]                       # semantic top-k, ranked
    bridges: dict[str, set[str]] = field(default_factory=dict)  # bridge -> seed tables it links
    tables: list[str] = field(default_factory=list)             # final joinable set


# --- foreign-key graph -------------------------------------------------------

_FK_SQL = """
SELECT DISTINCT
  CASE WHEN src.relname LIKE 'payment_p%' THEN 'payment' ELSE src.relname END AS src_table,
  CASE WHEN tgt.relname LIKE 'payment_p%' THEN 'payment' ELSE tgt.relname END AS tgt_table
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
JOIN pg_namespace n ON n.oid = src.relnamespace
WHERE con.contype = 'f' AND n.nspname = 'public';
"""


def load_fk_adjacency(conn) -> dict[str, set[str]]:
    """Undirected FK adjacency among the logical Pagila tables (payment
    partitions collapsed to 'payment'). A join can run either way, so edges
    are symmetric."""
    adj: dict[str, set[str]] = {}
    with conn.cursor() as cur:
        cur.execute(_FK_SQL)
        for src, tgt in cur.fetchall():
            if src == tgt:
                continue
            adj.setdefault(src, set()).add(tgt)
            adj.setdefault(tgt, set()).add(src)
    return adj


# --- similarity --------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _load_index(conn) -> list[tuple[str, list[float]]]:
    with conn.cursor() as cur:
        cur.execute("SELECT table_name, embedding FROM insightagent.schema_index;")
        return cur.fetchall()


# --- FK-graph expansion ------------------------------------------------------

def _induced_components(seed: list[str], adj: dict[str, set[str]]) -> list[set[str]]:
    """Connected components of the subgraph induced on `seed` (edges among seed
    tables only). Two seed tables are in the same component if they can be joined
    using only other seed tables."""
    seed_set = set(seed)
    seen: set[str] = set()
    comps: list[set[str]] = []
    for start in seed:
        if start in seen:
            continue
        comp, stack = {start}, [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            for nb in adj.get(node, ()):
                if nb in seed_set and nb not in seen:
                    seen.add(nb)
                    comp.add(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def _bridge_tables(seed: list[str], adj: dict[str, set[str]]) -> dict[str, set[str]]:
    """Non-seed tables that join two otherwise-disconnected pieces of the seed.
    Returns {bridge_table: {seed tables it connects}}. Single-hop bridges only,
    which is enough for the Pagila eval chains."""
    comps = _induced_components(seed, adj)
    if len(comps) < 2:
        return {}  # seed is already joinable; nothing to add
    comp_of = {t: i for i, comp in enumerate(comps) for t in comp}
    seed_set = set(seed)
    bridges: dict[str, set[str]] = {}
    for cand, nbrs in adj.items():
        if cand in seed_set:
            continue
        linked = {s for s in nbrs if s in seed_set}
        if len({comp_of[s] for s in linked}) >= 2:
            bridges[cand] = linked
    return bridges


# --- public API --------------------------------------------------------------

def retrieve_tables(question: str, k: int = 5, expand: bool = True) -> RetrievalResult:
    """Top-k tables by semantic similarity, plus FK bridges to keep them
    joinable. `tables` is the final set the SQL generator should use."""
    q = embed_text(question, task_type="RETRIEVAL_QUERY")
    with get_connection() as conn:
        index = _load_index(conn)
        adj = load_fk_adjacency(conn) if expand else {}

    scored = [TableMatch(name, _cosine(q, emb)) for name, emb in index]
    scored.sort(key=lambda m: m.score, reverse=True)
    seed = scored[:k]
    seed_names = [m.table_name for m in seed]

    bridges = _bridge_tables(seed_names, adj) if expand else {}
    tables = seed_names + [b for b in bridges if b not in seed_names]
    return RetrievalResult(question=question, seed=seed, bridges=bridges, tables=tables)


if __name__ == "__main__":
    cases = [
        ("EASY  (single table)", "What is the average payment amount?",
         {"payment"}),
        ("HARD  (5-table join chain)", "Which film category generated the most revenue?",
         {"payment", "rental", "inventory", "film_category", "category"}),
    ]
    for label, question, expected in cases:
        res = retrieve_tables(question, k=5, expand=True)
        print(f"\n[{label}]  {question}")
        print("   semantic seed (top 5):")
        for rank, m in enumerate(res.seed, 1):
            print(f"     {rank}. {m.table_name:<14} {m.score:.4f}")
        if res.bridges:
            for b, links in res.bridges.items():
                print(f"   + FK bridge added: {b}  (connects {', '.join(sorted(links))})")
        else:
            print("   + FK bridge added: none (seed already joinable)")
        missing = expected - set(res.tables)
        print(f"   => final tables: {res.tables}")
        print(f"   => expected coverage: {len(expected) - len(missing)}/{len(expected)}"
              + (f"  MISSING {sorted(missing)}" if missing else "  (all present)"))
