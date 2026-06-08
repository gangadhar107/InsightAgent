"""
table_descriptions.py - InsightAgent v2 schema index source text (step 2, piece 2).

Plain-language, business-vocabulary descriptions of each Pagila table. These are
the *documents* that get embedded (task_type RETRIEVAL_DOCUMENT) and stored for
semantic schema retrieval. The text here is exactly what gets embedded, so edit
freely - wording drives match quality.

Scope: the 7 monthly payment_p2022_* partitions are folded into the single
'payment' entry, because the agent always queries the parent 'payment' table.
That gives 15 logical tables (not 21 physical relations).

Date ranges below were confirmed against the live data on 2026-06-08:
  * payment_date: 2022-01-23 .. 2022-07-27  (described as "January to July 2022")
  * rental_date:  2022-02-14 .. 2022-08-24  (described as "mid-February through August 2022")
"""
from __future__ import annotations

# table name -> description (each embedded as a RETRIEVAL_DOCUMENT)
TABLE_DESCRIPTIONS: dict[str, str] = {
    "actor": "Actors and actresses who appear in the films; each row is one performer with a first and last name. Connects to the movies they star in through film_actor, so this is what you use for cast questions like 'which films does an actor appear in' or 'how many actors are in a film'.",

    "address": "Street addresses used by customers, staff, and stores. Holds the street, the district (which holds the state or province, e.g. 'California'), plus postal code and phone. Each address belongs to a city (city_id references city) and is referenced by customer, staff, and store. This is how you find where a customer lives or where a store sits; for 'customers in California', filter address.district.",

    "category": "The genres a film can belong to: Action, Comedy, Drama, Sports, Sci-Fi, Animation, and so on (category_id, name). Films are tagged with a genre through film_category. Use this whenever a question names a genre or 'category of film'.",

    "city": "Cities (city_id, city name). Each city belongs to a country (country_id references country) and is referenced by address. Use it to roll customers, staff, or stores up to a city, or to bridge an address to its country.",

    "country": "Countries (country_id, country name). Referenced by city. The highest level of geography - group customers or stores by country via address to city to country.",

    "customer": "The people who rent films - the store's customers or members (name, email). Each has a home store (store_id references store) and a mailing address (address_id references address, whose district gives their state). The active and activebool flags mark whether a customer is still active, and create_date is when they signed up. Referenced by rental (what they rented) and payment (what they paid). Use for anything about members, active customers, or where customers are located.",

    "film": "The catalog of movies available to rent (title, description, release_year). Key business attributes: rental_rate (the price to rent the film), rental_duration (how many days the rental lasts), length (runtime in minutes), replacement_cost, and rating - the MPAA rating like G, PG, PG-13, R, or NC-17. Each film has a primary language (language_id references language). Connects to its cast through film_actor, its genre through film_category, and its physical copies through inventory. Use for titles, ratings, rental price, or - joined through film_category - genres.",

    "film_actor": "A linking table that records which actors appear in which films (actor_id references actor, film_id references film); each row is one actor-in-one-film pairing. It exists purely to connect actors and films (a many-to-many relationship), so you join through it for cast questions.",

    "film_category": "A linking table that assigns each film to a genre or category (film_id references film, category_id references category). This is the bridge for anything that combines a film with its genre, e.g. 'R-rated films in the Action category' or 'average rental rate for Comedy films'.",

    "inventory": "The physical copies of films stocked for rental (inventory_id). Each copy is a specific film (film_id references film) held at a specific store (store_id references store). Rentals point at an inventory copy, so inventory is the bridge between a film and the rentals or revenue it generated, and how you tell how many copies of a title a store holds.",

    "language": "The languages films are offered in, such as English (language_id, name). Referenced by film as both its language and original language. Use for questions like 'films in English'.",

    "payment": "The money customers paid for their rentals - this is the revenue table. Each payment records the amount paid and payment_date, and ties together the customer who paid (customer_id), the staff member who processed it (staff_id), and the specific rental it is for (rental_id). It is a partitioned table covering January to July 2022 (monthly slices payment_p2022_01 through payment_p2022_07), but you always query the single 'payment' table and let the date filter pick the months. Important: payment has no direct link to a store - to attribute revenue to a store you go through the staff member, staff.store_id. Use for revenue, sales, total or average amounts, and store or category revenue.",

    "rental": "Each time a customer takes out a film copy - the core activity table (rental_date, return_date). A rental is of a physical copy (inventory_id references inventory) by a customer (customer_id references customer), handled by a staff member (staff_id references staff), and can have a matching payment. Use for rental volume or counts, when films were rented, who rented, and rental duration (return_date minus rental_date). Rental activity in this dataset runs mid-February through August 2022.",

    "staff": "The store employees (name, email, username). Each staff member works at one store (store_id references store) and has an address. Staff are recorded on every rental they handle and every payment they process, which makes staff.store_id the only bridge from a payment to its store. Use for employee questions and to attribute rentals or revenue to a store.",

    "store": "The rental store locations - there are two, store 1 and store 2 (store_id). Each store has a manager (manager_staff_id references staff) and a physical address (address_id references address). Referenced by customer (home store), staff (workplace), and inventory (where each copy is stocked). Use for 'store 1 vs store 2' comparisons and anything that splits the business by store.",
}
