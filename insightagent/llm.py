"""
llm.py - InsightAgent v2 chat-LLM client (step 3).

A thin wrapper over the chat LLM configured in .env (LLM_PROVIDER / LLM_API_KEY /
LLM_MODEL). One job: send a prompt, get text back. Reused by SQL generation, the
self-check, and the follow-up resolver, so they never deal with HTTP directly.

Currently implements the Anthropic Messages API. Stdlib only (urllib); no SDK.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


_cfg = _load_env()
_PROVIDER = _cfg.get("LLM_PROVIDER", "").lower()
_API_KEY = _cfg.get("LLM_API_KEY", "")
_MODEL = _cfg.get("LLM_MODEL", "")

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"


def complete(prompt: str, system: str | None = None, max_tokens: int = 1024,
             temperature: float = 0.0) -> str:
    """Send a single user prompt and return the model's text reply.

    temperature defaults to 0.0 (deterministic) - the right choice for SQL
    generation and checks. Raises RuntimeError with the API message on failure.
    """
    if not _API_KEY:
        raise RuntimeError("LLM_API_KEY is empty - set it in .env")
    if _PROVIDER != "anthropic":
        raise RuntimeError(f"llm.py currently supports provider 'anthropic', not '{_PROVIDER}'")

    body: dict = {
        "model": _MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    req = urllib.request.Request(
        _ANTHROPIC_URL, data=json.dumps(body).encode("utf-8"), method="POST"
    )
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", _API_KEY)
    req.add_header("anthropic-version", _ANTHROPIC_VERSION)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"LLM API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM API unreachable: {e.reason}") from e

    # Anthropic returns content as a list of blocks; concatenate the text ones.
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


if __name__ == "__main__":
    reply = complete(
        "Reply with exactly the word: pong",
        system="You are a terse health check. Reply with a single word.",
        max_tokens=16,
    )
    print(f"provider = {_PROVIDER}")
    print(f"model    = {_MODEL}")
    print(f"reply    = {reply!r}")
