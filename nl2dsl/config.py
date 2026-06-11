"""
Minimal .env loader. No third-party dependency.

Looks for a `.env` file in the project root (next to pyproject.toml) and, as
a fallback, the current working directory. Lines are `KEY=VALUE`; `#`
comments and blank lines ignored; existing environment variables are NEVER
overwritten (real env always wins).

Usage:
    from .config import load_env
    load_env()                    # idempotent, safe to call many times
    key = os.environ.get("OPENAI_API_KEY")
"""

from __future__ import annotations
import os
from pathlib import Path

_LOADED = False


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not key:
        return None
    return key, value


def load_env() -> None:
    """Load .env once per process. Real environment variables take priority."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    candidates = [
        Path(__file__).resolve().parent.parent / ".env",  # project root
        Path.cwd() / ".env",                              # cwd fallback
    ]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            parsed = _parse_line(line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)  # never overwrite real env
        break
