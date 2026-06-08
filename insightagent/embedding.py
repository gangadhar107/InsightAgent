"""
embedding.py - InsightAgent v2 embedding client (step 2, piece 1).

A thin wrapper over Google's Gemini embedding API with exactly one job:
turn text into a vector. It is used in two places later:
  * embedding table descriptions  -> task_type "RETRIEVAL_DOCUMENT"
  * embedding the user's question -> task_type "RETRIEVAL_QUERY"

Keeping it isolated means the rest of the pipeline never has to know how
embeddings are produced - it just calls embed_text().

Config is read from .env (EMBEDDING_API_KEY, EMBEDDING_MODEL).
No third-party dependencies: uses only the standard library.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"


def _load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE per line, ignoring blank lines and
    '#' comments, stripping surrounding whitespace and quotes."""
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        cfg[key.strip()] = val.strip().strip('"').strip("'")
    return cfg


_cfg = _load_env()
_API_KEY = _cfg.get("EMBEDDING_API_KEY", "")
_MODEL = _cfg.get("EMBEDDING_MODEL", "gemini-embedding-001")


def embed_text(text: str, task_type: str | None = None) -> list[float]:
    """Embed a single string and return its vector as a list of floats.

    task_type tunes the embedding for how it will be used; Gemini supports
    'RETRIEVAL_DOCUMENT' (stored content) and 'RETRIEVAL_QUERY' (a search
    query), among others. Pass None for a generic embedding.

    Raises RuntimeError (with the API's message) on any failure.
    """
    if not _API_KEY:
        raise RuntimeError("EMBEDDING_API_KEY is empty - set it in .env")
    if not text or not text.strip():
        raise ValueError("embed_text received empty text")

    payload: dict = {
        "model": f"models/{_MODEL}",
        "content": {"parts": [{"text": text}]},
    }
    if task_type:
        payload["taskType"] = task_type

    req = urllib.request.Request(
        _API_ENDPOINT.format(model=_MODEL),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-goog-api-key", _API_KEY)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"embedding API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"embedding API unreachable: {e.reason}") from e

    return data["embedding"]["values"]


if __name__ == "__main__":
    # Smoke test: embed one sample the way we will embed real descriptions,
    # and report the dimension so we can confirm it matches our storage size.
    sample = ("rental: one row per film rental by a customer, with rental_date, "
              "return_date, the inventory copy rented, and the staff member.")
    vec = embed_text(sample, task_type="RETRIEVAL_DOCUMENT")
    norm = sum(x * x for x in vec) ** 0.5
    print(f"model      = {_MODEL}")
    print(f"dimension  = {len(vec)}")
    print(f"first5     = {[round(x, 5) for x in vec[:5]]}")
    print(f"L2 norm    = {norm:.5f}  (~1.0 => already unit-normalized)")
