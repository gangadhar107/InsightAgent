# InsightAgent v2 — Product Requirements Document

| | |
|---|---|
| Author | Gangadhar |
| Status | Draft |
| Version | 2.0 (clean rebuild) |
| Database | Pagila (PostgreSQL) |

---

## 1. Problem Statement

In most enterprises, the people who most need data day-to-day — product
managers and business managers — cannot retrieve it themselves. They depend on
data analysts to write a query, pull the numbers, and send them back. This
creates two problems at once. The decision-makers wait, sometimes hours or
days, by which point the decision has often already been made on instinct. And
the analysts spend a disproportionate share of their time answering the same
repetitive, well-defined questions instead of doing the deeper analysis only
they can do.

This system gives non-technical users a way to ask questions in plain language
and get a direct, accurate answer, with a clarifying question when the request
is ambiguous and a visualization when it helps. By absorbing the repetitive
lookups, it shortens the path from question to answer for the business and
frees analysts to focus on higher-value work.

---

## 2. Why This Exists When Dashboards Already Do

Dashboards answer the questions that were anticipated when the dashboard was
built. The analyst gets asked everything else. With hundreds of dashboards in
place, five kinds of question still slip through and become an analyst ticket.
The core of this system handles the first three directly. The last two
describe where it extends.

### Handled by the core system

**The intersection question.** Dashboards show one metric, or a few pre-built
combinations. They almost never show arbitrary intersections. "What is the
average number of rentals in their first month for customers in California who
rented more than three R-rated films?" Someone built a dashboard for rentals
by region. Someone built one by film rating. Nobody built one for that
intersection, and nobody will, because the number of possible intersections is
effectively infinite. The agent constructs the query on the fly and answers it
in one ask.

**The one-time question.** Dashboards are built for recurring needs. But a
large share of real analytical work is one-off. "Last quarter we raised the
rental rate on our comedy titles — did rental volume for comedies fall
afterward?" Nobody built a dashboard for that, and building one now is wasted
effort since the question won't recur. The agent answers it without anyone
having to build and maintain a new view.

**The before-and-after question.** Dashboards show rolling windows — last 7
days, last 30, this month versus last. They rarely allow an arbitrary
comparison around a specific event date. "Did average rental duration change
after the Lethbridge store brought on new staff in May?" This almost always
goes to an analyst because the dashboard's fixed windows don't line up with the
event. The agent handles the specific pre-period versus post-period comparison
directly.

### Where the system extends (beyond this build's core)

**The "why" question.** A dashboard shows that rentals dropped 18% last
Tuesday. It cannot tell you why. Answering that means chaining questions — did
rentals fall across all stores or one? which category drove it? — which
requires the agent to carry context across turns. The single-shot core can
answer each link if asked explicitly; making the chain flow naturally is the
extension.

**The "is this normal?" question.** A dashboard shows a number but rarely says
whether it's good, bad, or expected. "Our film return rate is running at 4% —
is that high?" needs a baseline the raw number doesn't carry. The core verifies
that an answer correctly responds to the question asked; independently fetching
a baseline and judging whether a value is anomalous is a richer capability that
builds on top of it.

---

## 3. What It Does

From the user's side, the experience is a conversation. Someone opens the app
and types a question the same way they would message a colleague — "how many
rentals did the downtown store handle last week?" — and presses enter. A few
seconds later they get back three things together: the number, a chart when a
chart helps, and a one-line plain-English summary of the answer. No warehouse
login, no SQL, no ticket filed, no waiting on another person. If they want to
go deeper, they ask the next question.

When a question is clear enough to answer, the system answers it. When a
question is too vague to answer correctly, the system does not guess — it asks
one specific clarifying question first, then answers once the user responds.
For example, "what's our return rate?" might prompt "over what period?" before
the system commits to a number. This is deliberate: a confident answer to an
ambiguous question is worse than a quick clarifying question, because the user
can't see that the system guessed.

In short, it should feel like texting a data analyst who responds instantly and
never tires of the same questions — one who asks for clarification when needed
rather than handing back a wrong number.

---

## 4. Who This Is For

**Primary user — the data consumer.** A product manager, business manager, or
similar non-technical decision-maker who needs data regularly but has no SQL
knowledge and no warehouse access. What they care about: speed (an answer in
seconds, not a queue), trust (the number matches what the data team would give
them), and simplicity (ask in plain English, get a clear answer). They don't
care how the SQL was generated or what validation ran underneath. Success for
them is "I got the right number, fast, without asking anyone."

**Secondary user — the data analyst.** The person who currently fields the
repetitive requests and wants to stop. What they care about: canonical
definitions (the agent's number for a core metric matches the one they would
produce), auditability (queries are logged and inspectable), and graceful
handling of ambiguity. The system serves them by absorbing the repetitive
lookups — it assists analysts, it does not replace them.

**Tertiary user — the data or platform engineer.** The person who owns the
warehouse and has to be comfortable with an agent holding read access. What
they care about: safety (the agent can never write, update, or delete — only
read), correctness guards (bad queries caught before execution), and, at
production scale, access boundaries and cost control. This build's core
enforces read-only access, pre-execution query validation, and a cost guard;
broader governance (per-user data authorization) is recognized but sits beyond
the core scope.

---

## 5. Scope

### In scope (core build)

- Plain-English question → SQL → executed answer with chart and summary
- Catalog routing for known metrics; semantic retrieval for everything else
- SQL validation (read-only, real tables/columns) and self-check
- Cost guard: EXPLAIN-based check that blocks ruinously expensive queries
  before execution
- Clarification when vague, with tappable options (predefined for common
  dimensions like time period, LLM fallback for unusual cases)
- Level 1 continuity: rewrite each follow-up into a standalone question using
  recent history

### Deferred (later)

- Long-context / token-budgeted memory and any external memory system
- Stored-answer recall (data changes, so answers must be recomputed live;
  similarity matching can't guarantee the precision data queries require)
- MCP server, multi-tenancy, per-user data authorization
- Slack integration, proactive alerts
- Causal-chain ("why") and is-this-normal questions (require multi-turn memory
  and richer comparative reasoning)

---

## 6. How It Works

A user question flows through a pipeline where each stage that depends on the
model is followed immediately by a check that catches the model's mistakes. The
core principle: never trust the model's output without a guard right behind it.

**Two phases.** Once, ahead of time: each table and its key columns are
described, each description is embedded, and the vectors stored in an index —
a searchable map of the database. Then, per question, the live pipeline runs:

1. **Resolve question** — rewrite the incoming message into a standalone
   question using recent history (so a follow-up like "what about the downtown
   store?" becomes complete). Runs first, so later stages only clarify what is
   genuinely missing.
2. **Ambiguity check** — if still too vague, ask a clarifying question with
   tappable options instead of guessing; the answer re-enters at the resolve
   step.
3. **Catalog vs retrieval** — if the question matches a known metric, use its
   fixed catalog SQL. Otherwise, embed the question, retrieve the most relevant
   tables, and generate SQL from only those tables.
4. **Validate SQL** — reject anything not read-only or referencing unknown
   tables/columns; on failure, retry generation once.
5. **Cost guard** — run EXPLAIN; block queries whose estimated cost exceeds a
   ceiling.
6. **Execute** — run the validated query.
7. **Self-check** — verify the result actually answers the question asked.
8. **Return answer** — number, chart, and one-line summary.

After the answer, the conversation loops: the next question re-enters the
pipeline with the now-longer history available to the resolve step.

Design note: catalog SQL is trusted (human-written), so it flows through
validation and execution for a single execution path but skips the self-check.

---

## 7. Evaluation

The system is evaluated against a hand-built test set of questions where the
correct answer is known in advance. For each question, the reference SQL is
written and verified by hand and its result recorded as ground truth. The agent
sees only the question.

### What is measured

- **Retrieval accuracy** — did retrieval fetch the tables the question should
  use? Isolates failures where the model never received the right schema.
- **Answer accuracy** — does the final answer match the hand-verified
  ground-truth value? Measures end-to-end correctness.

Measuring both separately makes a failure diagnosable: bad retrieval (wrong
tables) versus bad generation (right tables, wrong SQL).

### Matching rules

- Counts and whole numbers must match exactly.
- Averages, percentages, and money allow a small rounding tolerance (±0.01).
- Ambiguity questions are scored on behaviour: pass if the agent clarifies,
  fail if it guesses.

### Test set

Around 25 hand-verified questions covering the targeted question types. Pagila
data spans January–July 2022, so all time-based questions stay inside that
window.

| # | Question | Type |
|---|----------|------|
| 1 | What is the total revenue across all stores? | Catalog |
| 2 | How many active customers are there? | Catalog |
| 3 | What is the average payment amount? | Catalog |
| 4 | How many R-rated films are in the Action category? | Intersection |
| 5 | Which customers in California have made more than 30 rentals? | Intersection |
| 6 | What is the average rental rate for Comedy films? | Intersection |
| 7 | How many rentals happened in February 2022? | One-time |
| 8 | Which film category generated the most revenue? | One-time |
| 9 | How many films have never been rented? | One-time |
| 10 | How did rental volume in July 2022 compare to June 2022? | Comparison |
| 11 | Which store had higher revenue, store 1 or store 2? | Comparison |
| 12 | What's our revenue? | Ambiguity (should clarify) |

Join notes for reference SQL: Q11 reaches store via payment → staff.store_id
(payment has no direct store link); Q9 needs a NOT EXISTS / LEFT JOIN pattern;
Q5 reaches location via customer → address.district.

---

## Appendix — Enterprise scaling (interview reference, not built)

Not in scope, kept for discussion. Going from this single-user prototype to an
enterprise SaaS product changes five things: (1) multi-tenancy with data
isolation enforced at the database layer; (2) per-tenant schema indexing and
metrics catalogs, making customer onboarding a core feature; (3) a stateless,
containerized, concurrent service (where the deferred async/Docker work lives);
(4) cost control via caching and query guards; (5) observability and audit
trails. The honest framing: these were deliberately deferred because this is a
single-user prototype, and the design choices reflect that stage.
