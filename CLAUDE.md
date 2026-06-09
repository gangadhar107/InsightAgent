# InsightAgent v2 — Project Brain

> A natural-language analytics agent over the **Pagila** PostgreSQL database. A
> non-technical user asks a question in plain English ("which film category made
> the most revenue?") and gets back a number, a chart, a one-line summary, and the
> SQL that produced it — with a clarifying question instead of a guess when the
> ask is vague. Built one component at a time, each with its own guard.

This file is the single source of truth for the project. Read it first.

---

## 1. Core principle (the spine of the whole design)

**Never trust the model's output without a guard right behind it.** Every stage that depends on the LLM is followed immediately by a deterministic check:

| Model step | Guard right behind it |
|------------|-----------------------|
| SQL generation | validation (read-only, real tables/cols, PII) |
| (any SQL) | cost guard (EXPLAIN ceiling) before execution |
| execution | read-only transaction + statement_timeout + row cap |
| the answer | self-check ("does this actually answer the question?") |

If you add a feature, keep this shape: model proposes, a guard disposes.

---

## 2. Stack & environment

- **Python 3.13** (user site-packages at `C:\Users\ganga\AppData\Roaming\Python\Python313`).
- **PostgreSQL 18**, local, running on **port 5433** (NOT the default 5432).
  Database is **`pagila`**, user `postgres`. `psql.exe` lives at `C:\Program Files\PostgreSQL\18\bin\psql.exe` (not on PATH).
- **psycopg3** (`import psycopg`, NOT psycopg2) for DB access.
- **sqlglot** (30.x) for SQL parsing in validation.
- **Streamlit** (1.57) + **pandas** for the UI.
- **LLM:** Anthropic **`claude-sonnet-4-5`** via the Messages API (plain `urllib`, no SDK).
- **Embeddings:** Google **`gemini-embedding-2`** via the Generative Language API — returns **3072 dims**, vectors are **unit-normalized** (so cosine == dot product).
- **No third-party API SDKs:** both the LLM and embedding clients use stdlib `urllib`.
- **pgvector is NOT installed** and can't be easily installed here (no MSVC/Docker), so embeddings are stored in a plain `double precision[]` column and cosine is computed in Python (fine for a 15-row index; see §9).

### Secrets / config — `.env` (gitignored)
All config is read from `.env` by a tiny parser duplicated in each module (`_load_env` / `load_env`). Keys: `DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD`, `LLM_PROVIDER LLM_API_KEY LLM_MODEL`, EMBEDDING_PROVIDER EMBEDDING_MODEL, EMBEDDING_API_KEY`. **Gotcha:** the parser strips surrounding whitespace AND quotes because the password value was entered with a leading space. `.env` contains real API keys — never commit it.

---

## 3. Running it

```powershell
# 0. Prereqs: Postgres 18 running on 5433 with the pagila DB; .env filled in
#    (copy .env.example -> .env). Then install the package (editable):
pip install -e .                        # or: pip install -r requirements.txt

# 1. One-time: build the schema embedding index (creates insightagent.schema_index)
python scripts/build_schema_index.py

# 2. Run the app
streamlit run ui/app.py                 # opens http://localhost:8501

# 3. Run the full evaluation (all 12 PRD questions, ~2-3 min of LLM calls)
python eval/eval_suite.py

# 4. Every library module has its own __main__ smoke test, run via -m, e.g.
python -m insightagent.embedding        # prints dimension 3072
python -m insightagent.validation       # 21-case battery (read-only, PII, etc.)
python -m insightagent.retrieve         # easy vs hard-join-chain retrieval
```

**Running raw SQL** (the established pattern — psql isn't on PATH, password needs
stripping):

```powershell
$cfg=@{}; Get-Content .\.env | %{ $l=$_.Trim(); if($l -and -not $l.StartsWith('#') -and $l.Contains('=')){ $i=$l.IndexOf('='); $cfg[$l.Substring(0,$i).Trim()]=$l.Substring($i+1).Trim().Trim('"').Trim("'") } }
$env:PGPASSWORD=$cfg['DB_PASSWORD']
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -p 5433 -U postgres -d pagila -w -f sql\reference_queries.sql
```

---

## 4. The pipeline (architecture)

One question flows through `pipeline.answer_question(question, history)` →
`PipelineResult`. This implements the lifecycle diagram in
`insightagent_v2_lifecycle_mermaid.md`:

```
resolve (follow-up -> standalone, using history)
   |
ambiguity check --(vague)--> CLARIFY: one question + tappable options
   |(clear)                   (a tapped option becomes the next message,
   |                           re-entering at resolve)
route? --catalog--> validate -> cost guard -> execute -> answer
   |                                   (catalog SQL skips retrieval, generation,
   |                                    AND self-check: a blessed definition)
   | generate path:
retrieve -> generate -> validate --(fail)--> generate (retry ONCE w/ feedback) -> validate
                           |(pass)
                           v
                      cost guard -> execute -> self-check -> answer
```

Notes:
- **Resolve runs first** so later stages only ever see a self-contained question.
- **Catalog vs generate** is decided by a strict intent router (see `catalog.py`).
- **Validation failure retries generation exactly once**, and the retry is given the previous SQL + the validation errors so it can actually fix the problem (a deterministic model would otherwise reproduce the same rejected SQL).
- `PipelineResult` carries: `stage` (answer | clarification | validation | cost_guard | execution | self_check), `source` (generated | catalog), `sql`, `tables`, `columns`/`rows`, `warnings` (incl. PII), `self_check_reason`, `estimated_cost`, `clarify_question`/`clarify_options`, and a human-readable `trace`.

---

## 5. Module map

Two phases: an **offline index build**, then the **per-question pipeline**. Each file is small and has a `__main__` smoke test.

**Layout (pip-installable, see `pyproject.toml`):** the library modules below all live in `insightagent/`. Entry points are `ui/app.py`, `scripts/build_schema_index.py`, `eval/eval_suite.py`; reference SQL is
`sql/reference_queries.sql`; source docs are in `docs/`. The table uses bare module names for everything under `insightagent/`.

**Layout (pip-installable, see `pyproject.toml`):** the library modules below all
live in `insightagent/`. Entry points are `ui/app.py`,
`scripts/build_schema_index.py`, `eval/eval_suite.py`; reference SQL is
`sql/reference_queries.sql`; source docs are in `docs/`. The table uses bare
module names for everything under `insightagent/`.

| File | Role | Key entry point |
|------|------|-----------------|
| `db.py` | Postgres connection + catalog introspection | `get_connection`, `get_columns`, `get_fk_join_edges`, `get_schema` |
| `embedding.py` | text → 3072-d vector (Gemini) | `embed_text(text, task_type)` |
| `llm.py` | chat completion (Anthropic) | `complete(prompt, system)` |
| `table_descriptions.py` | 15 plain-language table descriptions (data) | `TABLE_DESCRIPTIONS` |
| `build_schema_index.py` | embed descriptions → `insightagent.schema_index` | run once |
| `retrieve.py` | semantic top-k **+ FK-bridge expansion** | `retrieve_tables(q, k=5)` |
| `generation.py` | retrieved tables + cols + FK joins → one SELECT | `generate_sql_from_tables(q, tables, repair=)` |
| `validation.py` | parse, single-stmt, read-only, real tables/cols, PII | `validate_sql(sql, schema)` |
| `pii.py` | tiered PII column policy | `check_pii(...)` |
| `cost.py` | EXPLAIN cost ceiling (no execution) | `cost_guard(sql, ceiling=1_000_000)` |
| `execution.py` | read-only txn + statement_timeout + row cap | `execute_sql(sql)` |
| `selfcheck.py` | LLM judge: does the result answer the question? | `self_check(q, sql, result)` |
| `catalog.py` | blessed metric SQL + strict intent router | `route_to_catalog(q)`, `catalog_sql(metric)` |
| `resolver.py` | follow-up → standalone question | `resolve_question(q, history)` |
| `clarify.py` | ambiguity check + tappable options | `check_ambiguity(q)` |
| `summary.py` | one-line plain-English answer (for the UI) | `summarize_answer(q, cols, rows)` |
| `pipeline.py` | **the orchestrator** | `answer_question(q, history)` |
| `eval_suite.py` | runs all 12 questions, scores answer + retrieval | run directly |
| `app.py` | Streamlit UI | `python -m streamlit run app.py` |
| `reference_queries.sql` | hand-verified SQL for the 12 eval questions | psql artifact |

Storage: our metadata lives in a dedicated **`insightagent`** schema (`insightagent.schema_index`: table_name, description, embedding `double precision[]`, dim, model). Kept separate from Pagila's `public` data tables.

---

## 6. Pagila data model & quirks — READ BEFORE WRITING SQL

The data does NOT match naive assumptions. These quirks were verified live and have already broken intuitive queries:

- **Rentals are not Jan–Jul.** `rental.rental_date` spans **2022-02-14 → 2022-08-24** with rentals ONLY in **Feb (182), May (1136), Jun (2331), Jul (6594), Aug (5801)**. There are **zero rentals in January, March, and April**. (This is why the eval's "Feb vs Jan" comparison was re-targeted to **July vs June**.)
- **Payments ARE Jan–Jul.** `payment` is smooth **2022-01-23 → 2022-07-27**, 16,049 rows, partitioned into 7 monthly tables `payment_p2022_01..07`. So rental_date and payment_date sit on **different timelines** — don't assume they align.
- **`payment` is a partitioned table.** Always query the parent `payment`; Postgres prunes partitions via the `payment_date` filter. Never target a `payment_p*` directly.
- **Store attribution goes through staff.** `payment` has **no** store column — reach store via `payment.staff_id → staff.store_id`. Same for rentals.
- **"Active customers" = `customer.active = 1` → 584.** The boolean `activebool` is `true` for ALL 599 customers (useless as a filter). Use the integer `active`.
- **Location/state is `address.district`** (e.g. `district = 'California'`), reached via `customer.address_id → address`.
- **Genre = `category`** via the link table `film_category` (e.g. Action, Comedy, Sports, Sci-Fi). **Cast = `actor`** via `film_actor`.
- **"Films never rented" needs `NOT EXISTS`** (or LEFT JOIN ... IS NULL): film → inventory → rental. Answer is **42** (films not in inventory + in-inventory-but-never-rented).
- **Session timezone is `Asia/Calcutta` (+05:30)**; month-boundary literals like `'2022-07-01'` are interpreted at +05:30, matching the partition bounds. Use half-open ranges: `d >= '2022-07-01' AND d < '2022-08-01'`.

15 logical tables: actor, address, category, city, country, customer, film, film_actor, film_category, inventory, language, payment, rental, staff, store.

---

## 7. Evaluation

`eval_suite.py` runs all 12 PRD questions through the live pipeline and scores two metrics **separately** (so failures are diagnosable: bad retrieval vs bad SQL).

- **Answer accuracy** — final value vs hand-verified ground truth. Counts exact; money/averages within ±0.01; Q12 passes iff the agent *clarifies*.
- **Retrieval accuracy** — did retrieval fetch the needed tables? Generate-path questions only (catalog + ambiguity skip retrieval → n/a).

**Current scores: answer 12/12, retrieval 7/8.** Ground truth:

| # | Question | Answer | Path |
|---|----------|--------|------|
| 1 | total revenue across all stores | 67,416.51 | catalog |
| 2 | how many active customers | 584 | catalog |
| 3 | average payment amount | 4.20 | catalog |
| 4 | R-rated films in Action category | 14 | generate |
| 5 | California customers with >30 rentals | 2 (Stewart 33, Johnston 31) | generate |
| 6 | average rental rate for Comedy films | 3.16 | generate |
| 7 | rentals in February 2022 | 182 | generate |
| 8 | film category with most revenue | Sports (5,314.21) | generate |
| 9 | films never rented | 42 | generate |
| 10 | rental volume July vs June 2022 | 6,594 vs 2,331 | generate |
| 11 | higher revenue: store 1 or 2 | store 2 (33,927.04) | generate |
| 12 | "What's our revenue?" | *clarifies (no number)* | clarification |

**The one retrieval miss (Q5):** `address` ranks #10 semantically (even `actor` outranks it for "customers in California"), so retrieval drops it. The answer is still correct because **generation isn't strictly confined to retrieved tables** — it used `address` from model knowledge and validation only checks tables are *real*, not *retrieved*. A robustness-vs-strictness trade-off we chose to keep (tightening it would make Q5 fail). Treat this as the canonical example of why the two metrics are measured separately.

---

## 8. PII policy (`pii.py`, enforced in validation)

A deliberate add beyond the PRD's deferred-governance scope. Classified by bare
column name:

- **SECRET** (`password`, `picture`) → rejected if referenced **anywhere**.
- **RESTRICTED** (`email`, `phone`, `address`, `address2`, `postal_code`) → rejected in SELECT **output**; allowed in WHERE/JOIN. `SELECT *` over a PII-bearing table is rejected. `COUNT(email)` is fine (counting ≠ leaking).
- **IDENTITY** (`first_name`, `last_name`) → **allowed but flagged** (a non-fatal warning). Deliberately not blocked so Q5 (customer names) still works.

Defense-in-depth: `generation.py`'s system prompt also tells the model to avoid PII output. Accepted residual gap: filtering by RESTRICTED PII still allows binary-search probing — could tighten to block-entirely later.

---

## 9. Key design decisions (and why)

- **No-pgvector fallback.** pgvector isn't available; at 3072 dims its ANN index wouldn't apply anyway (2000-dim limit), and the index is only 15 rows. So we store vectors in `double precision[]` and brute-force cosine in Python, behind a clean interface so pgvector can drop in later with no caller changes.
- **FK-bridge retrieval expansion.** Semantic top-k misses intermediate join tables the question never names (Q8 needs `rental` to connect payment↔inventory). The bridge rule adds a non-seed table **only if it connects two otherwise-disconnected pieces of the seed** in the FK graph — recovering bridges without dragging in hub tables. Naive "add all FK neighbors" over-expands badly in Pagila.
- **Strict catalog router.** A false route gives a confidently wrong answer; a miss just falls through to generation (which works). So when unsure → `none`.
- **Conservative clarifier.** Defaults to "all available data"; treats concrete metrics/entities ("active customers", "store 1 vs 2") as clear; only genuinely bare questions ("what's our revenue?") clarify. (The eval caught an earlier version over-clarifying Q2/Q11 — fixed.)
- **Cost ceiling = 1,000,000** planner units. Normal Pagila queries cost ~1–1,400; a `rental × rental` cross join costs ~2.27M. Huge margin, clean block.
- **Read-only everywhere at execution.** `conn.read_only = True` makes Postgres reject any write at the engine level — a real last line of defense independent of validation.

---

## 10. Conventions / how we work

- **Build ONE component at a time**, each small and testable, each with a `__main__` smoke test. Verify it before moving on. (This was the explicit working style.)
- **Test hard cases, not just easy ones** — deep join chains, injection attempts, plausible-but-wrong answers, PII edge cases.
- **stdlib-first:** `urllib` for both API clients (no SDKs), `psycopg3` for DB, `sqlglot` for SQL parsing.
- **Dataclass result objects** everywhere: `RetrievalResult`, `ValidationResult` (+`warnings`), `ExecutionResult`, `SelfCheckResult`, `Clarification`, `CostResult`, `PipelineResult`. Functions return rich results, not tuples.
- **Flag scope/assumptions** rather than silently expanding (the PII policy, the Q10 re-target, and the pgvector fallback were all surfaced as decisions).

---

## 11. Known limitations & deferred scope

From the PRD's "Deferred" list and the build:
- **Level 1 continuity only** (the resolver). No token-budgeted / long-context memory, no external memory store.
- **No stored-answer recall** — data changes, so answers are always recomputed live.
- **No MCP server, multi-tenancy, per-user data authorization, or Slack.**
- **No causal ("why did it drop?") or "is this normal?"** reasoning (need multi-turn memory + baselines).
- **Q5 retrieval gap** (address #10) — answer correct via model knowledge; see §7.
- **No `requirements.txt` / venv yet.** Everything runs on the global user Python.
- Single-user prototype; not hardened for concurrency or production.

---

## 12. Gotchas / footguns

- **Postgres is on port 5433, not 5432.** `psql` is not on PATH (use the full path).
- **`.env` password parsing must strip whitespace AND quotes** (the value had a leading space; embedding/LLM values are quoted).
- **Build the schema index first** — retrieval reads `insightagent.schema_index`; it's empty until `build_schema_index.py` has run.
- **psycopg3, not psycopg2** (`import psycopg`).
- **Streamlit env conflict:** Streamlit 1.57 required upgrading `starlette` 0.38.6 → 1.2.1, which **breaks `fastapi 0.115`'s `starlette<0.39` pin**. We don't use fastapi, but if other projects on this Python do, give InsightAgent its own virtualenv.
- **`gemini-embedding-2` works as-is** (don't "fix" it to `gemini-embedding-001`); it returns 3072-d unit-normalized vectors.
- The home directory appears to be a git repo; `.env` is protected by a local `.gitignore`.

---

## 13. Source documents (in `docs/`)

- `insightagent_v2_prd.md` — the product spec (problem, scope, the 12-question eval).
- `insightagent_v2_evaluation.md` — the standalone eval spec (questions + expected tables/columns). **Note:** its Q2 column hint still says `customer.activebool` for retrieval — the *answer* uses `active = 1` (584); worth reconciling.
- `insightagent_v2_lifecycle_mermaid.md` — the request lifecycle diagram (§4).
- `Schema.txt` — full Pagila DDL dump.
- `analytics_agent_ui_wireframe.html` — UI **layout reference only**; its SaaS/DAU example content does NOT apply (all content is Pagila).

---
*Built end-to-end, one verified component at a time. Answer accuracy 12/12,
retrieval 7/8. Every model step has a guard behind it.*
