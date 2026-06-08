-- =====================================================================
-- InsightAgent v2 — Reference SQL for the 12 evaluation questions (PRD section 7)
-- Database: Pagila (PostgreSQL). These are the hand-verified ground-truth
-- queries the agent will later be graded against.
--
-- Run with:
--   psql -h localhost -p 5433 -U postgres -d pagila -f reference_queries.sql
--
-- Verified data reality (matters for time-based Q7 / Q10):
--   * rental_date spans 2022-02-14 .. 2022-08-24. Rentals exist only in Feb,
--     May, Jun, Jul, Aug -- Jan/Mar/Apr have ZERO rentals.
--   * Q7 (Feb) is a partial month: data starts Feb 14, so 182 is correct.
--   * Q10 uses July vs June (both fully populated) per the updated eval spec.
--   * session timezone is Asia/Calcutta (+05:30); month-boundary literals
--     below are interpreted at +05:30, matching the partitions.
-- =====================================================================


\echo '=== Q1 (Catalog): Total revenue across all stores ==='
SELECT SUM(amount) AS total_revenue
FROM payment;


\echo ''
\echo '=== Q2 (Catalog): How many active customers are there? ==='
-- "Active" = the integer flag active = 1 (584 of 599).
-- activebool is true for ALL 599, so it cannot be the intended flag.
SELECT COUNT(*) AS active_customers
FROM customer
WHERE active = 1;


\echo ''
\echo '=== Q3 (Catalog): Average payment amount ==='
SELECT AVG(amount)            AS avg_payment_amount,
       ROUND(AVG(amount), 2)  AS avg_payment_rounded
FROM payment;


\echo ''
\echo '=== Q4 (Intersection): How many R-rated films are in the Action category? ==='
SELECT COUNT(*) AS r_rated_action_films
FROM film f
JOIN film_category fc ON fc.film_id = f.film_id
JOIN category      c  ON c.category_id = fc.category_id
WHERE f.rating = 'R'
  AND c.name = 'Action';


\echo ''
\echo '=== Q5 (Intersection): California customers with more than 30 rentals ==='
-- Location via customer -> address.district (PRD join note).
SELECT c.customer_id,
       c.first_name,
       c.last_name,
       COUNT(r.rental_id) AS rental_count
FROM customer c
JOIN address a ON a.address_id = c.address_id
JOIN rental  r ON r.customer_id = c.customer_id
WHERE a.district = 'California'
GROUP BY c.customer_id, c.first_name, c.last_name
HAVING COUNT(r.rental_id) > 30
ORDER BY rental_count DESC;


\echo ''
\echo '=== Q6 (Intersection): Average rental rate for Comedy films ==='
SELECT AVG(f.rental_rate)           AS avg_rental_rate,
       ROUND(AVG(f.rental_rate), 2) AS avg_rental_rate_rounded
FROM film f
JOIN film_category fc ON fc.film_id = f.film_id
JOIN category      c  ON c.category_id = fc.category_id
WHERE c.name = 'Comedy';


\echo ''
\echo '=== Q7 (One-time): How many rentals happened in February 2022? ==='
SELECT COUNT(*) AS feb_2022_rentals
FROM rental
WHERE rental_date >= '2022-02-01'
  AND rental_date <  '2022-03-01';


\echo ''
\echo '=== Q8 (One-time): Which film category generated the most revenue? ==='
-- Revenue path: payment -> rental -> inventory -> film_category -> category.
-- Winner is row 1; top 5 shown for transparency / tie-checking.
SELECT c.name        AS category,
       SUM(p.amount) AS revenue
FROM payment p
JOIN rental        r  ON r.rental_id = p.rental_id
JOIN inventory     i  ON i.inventory_id = r.inventory_id
JOIN film_category fc ON fc.film_id = i.film_id
JOIN category      c  ON c.category_id = fc.category_id
GROUP BY c.name
ORDER BY revenue DESC
LIMIT 5;


\echo ''
\echo '=== Q9 (One-time): How many films have never been rented? ==='
-- NOT EXISTS pattern (PRD join note). Counts films whose inventory copies
-- have zero rentals, plus films with no inventory at all.
SELECT COUNT(*) AS never_rented_films
FROM film f
WHERE NOT EXISTS (
    SELECT 1
    FROM inventory i
    JOIN rental r ON r.inventory_id = i.inventory_id
    WHERE i.film_id = f.film_id
);


\echo ''
\echo '=== Q10 (Comparison): Rental volume July 2022 vs June 2022 ==='
SELECT
  COUNT(*) FILTER (WHERE rental_date >= '2022-06-01' AND rental_date < '2022-07-01') AS jun_2022,
  COUNT(*) FILTER (WHERE rental_date >= '2022-07-01' AND rental_date < '2022-08-01') AS jul_2022
FROM rental
WHERE rental_date >= '2022-06-01'
  AND rental_date <  '2022-08-01';


\echo ''
\echo '=== Q11 (Comparison): Which store had higher revenue, store 1 or store 2? ==='
-- payment has no direct store link; reach store via payment -> staff.store_id (PRD note).
SELECT s.store_id,
       SUM(p.amount) AS revenue
FROM payment p
JOIN staff s ON s.staff_id = p.staff_id
GROUP BY s.store_id
ORDER BY s.store_id;


\echo ''
\echo '=== Q12 (Ambiguity): What is our revenue?  -- NO reference SQL by design ==='
\echo 'Ground truth is behavioural: the agent must CLARIFY (which period? which store?)'
\echo 'rather than return a number. Scored pass if it asks, fail if it guesses.'
