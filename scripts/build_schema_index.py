"""
build_schema_index.py - InsightAgent v2 schema index builder (step 2, piece 2).

A re-runnable job: embed each plain-language table description from
table_descriptions.py and store the vectors in Postgres, so the agent can later
fetch the most relevant tables for a question by semantic similarity.

pgvector is not available here, so vectors live in a plain double precision[]
column and cosine similarity is computed in Python at query time (piece 3). The
retrieval interface stays identical if we later swap in pgvector.

Run:  python build_schema_index.py   (safe to re-run; upserts by table_name)
"""
from __future__ import annotations

from pathlib import Path

import psycopg

from insightagent.embedding import embed_text
from insightagent.table_descriptions import TABLE_DESCRIPTIONS

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# Informational tag stored alongside each row; the real model is in embedding.py/.env.
_MODEL_TAG = "gemini-embedding-2"


def _load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def _conn_string(cfg: dict[str, str]) -> str:
    return (
        f"host={cfg['DB_HOST']} port={cfg['DB_PORT']} dbname={cfg['DB_NAME']} "
        f"user={cfg['DB_USER']} password={cfg['DB_PASSWORD']}"
    )


DDL = """
CREATE SCHEMA IF NOT EXISTS insightagent;

CREATE TABLE IF NOT EXISTS insightagent.schema_index (
    table_name  text PRIMARY KEY,
    description text NOT NULL,
    embedding   double precision[] NOT NULL,
    dim         integer NOT NULL,
    model       text NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
"""

UPSERT = """
INSERT INTO insightagent.schema_index (table_name, description, embedding, dim, model, updated_at)
VALUES (%(table_name)s, %(description)s, %(embedding)s, %(dim)s, %(model)s, now())
ON CONFLICT (table_name) DO UPDATE SET
    description = EXCLUDED.description,
    embedding   = EXCLUDED.embedding,
    dim         = EXCLUDED.dim,
    model       = EXCLUDED.model,
    updated_at  = now();
"""


def main() -> None:
    cfg = _load_env()
    items = sorted(TABLE_DESCRIPTIONS.items())
    print(f"Embedding {len(items)} table descriptions and storing them...\n")

    with psycopg.connect(_conn_string(cfg)) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

        for i, (table_name, description) in enumerate(items, 1):
            vector = [float(x) for x in embed_text(description, task_type="RETRIEVAL_DOCUMENT")]
            with conn.cursor() as cur:
                cur.execute(UPSERT, {
                    "table_name": table_name,
                    "description": description,
                    "embedding": vector,
                    "dim": len(vector),
                    "model": _MODEL_TAG,
                })
            conn.commit()
            print(f"  [{i:2d}/{len(items)}] {table_name:<14} dim={len(vector)}")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*),
                       min(array_length(embedding, 1)),
                       max(array_length(embedding, 1)),
                       count(DISTINCT model)
                FROM insightagent.schema_index;
            """)
            rows, min_dim, max_dim, models = cur.fetchone()

    print(f"\nStored {rows} rows | dims [{min_dim}..{max_dim}] | distinct models={models}")
    print("Schema index ready in insightagent.schema_index.")


if __name__ == "__main__":
    main()
