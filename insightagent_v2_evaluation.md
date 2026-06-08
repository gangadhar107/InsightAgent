# 7. Evaluation

The system is evaluated against a hand-built test set of questions where the
correct answer is known in advance. For each question, the reference SQL is
written and verified by hand, and its result recorded as ground truth. The
agent sees only the question, never the reference SQL.

## What is measured

Accuracy is measured at two separate points, because a wrong answer can fail
in two different places:

- **Retrieval accuracy.** For each question, the tables it should use are
  known. We check whether retrieval actually fetched those tables. This
  isolates failures where the model never received the right schema.
- **Answer accuracy.** The agent's final answer is compared against the
  hand-verified ground-truth value. This measures end-to-end correctness.

Measuring both separately makes failures diagnosable: a wrong answer can be
traced to bad retrieval (wrong tables fetched) versus bad generation (right
tables, wrong SQL).

## Matching rules

- **Counts and whole numbers** must match exactly.
- **Averages, percentages, and money** allow a small rounding tolerance
  (within 0.01).
- **Ambiguity questions** are scored on behaviour, not value: pass if the
  agent asks a clarifying question, fail if it guesses an answer.

## Test set

The set is intentionally small (around 25 questions) because each requires
hand-verification; a small, fully-trusted set is enough to catch hallucination
and measure accuracy. It covers the question types the system targets.

Note: Pagila data spans January–July 2022. All time-based questions stay
inside that window; relative dates ("last month") return empty.

### Catalog metrics (predefined)

| # | Question | Tables / columns |
|---|----------|------------------|
| 1 | What is the total revenue across all stores? | payment.amount |
| 2 | How many active customers are there? | customer.activebool |
| 3 | What is the average payment amount? | payment.amount |

### Intersection questions (ad-hoc)

| # | Question | Tables / columns |
|---|----------|------------------|
| 4 | How many R-rated films are in the Action category? | film.rating, film_category, category.name |
| 5 | Which customers in California have made more than 30 rentals? | customer, address.district, rental |
| 6 | What is the average rental rate for Comedy films? | film.rental_rate, film_category, category.name |

### One-time questions (ad-hoc)

| # | Question | Tables / columns |
|---|----------|------------------|
| 7 | How many rentals happened in February 2022? | rental.rental_date |
| 8 | Which film category generated the most revenue? | payment → rental → inventory → film → film_category → category |
| 9 | How many films have never been rented? | film, inventory, rental |

### Before-and-after / comparison (ad-hoc)

| # | Question | Tables / columns |
|---|----------|------------------|
| 10 | How did rental volume in July 2022 compare to June 2022? | rental.rental_date |
| 11 | Which store had higher revenue, store 1 or store 2? | payment.amount → staff.store_id |

### Ambiguity test (should clarify, not answer)

| # | Question | Expected behaviour |
|---|----------|--------------------|
| 12 | What's our revenue? | No period/scope given — agent should ask which period or store |

## Notes on specific cases

- **Q11** — payment does not link to store directly; it links via
  staff.store_id (payment → staff → store). The reference SQL must use that
  join path.
- **Q9** — requires a NOT EXISTS / LEFT JOIN pattern; tests whether generation
  handles negation correctly.
- **Q5** — customer location is reached via customer → address (district holds
  the state, e.g. "California").
