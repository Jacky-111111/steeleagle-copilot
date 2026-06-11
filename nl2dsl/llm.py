"""
OpenAI client.

Single-purpose wrapper around the chat completions API. Forces JSON output
via response_format so the caller never has to parse markdown fences.

Decoupled from the rest of the pipeline behind a simple Protocol so tests
and offline development can substitute a fake LLM (see `FakeLLM`).
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    dsl_code: str
    notes: str
    raw: dict          # Full parsed JSON in case we add more fields later


class LLM(Protocol):
    """The contract the pipeline depends on. Anything fulfilling this works."""
    def complete(self, system: str, user: str) -> LLMResponse: ...


class OpenAILLM:
    """Real OpenAI client. Requires the `openai` package and an API key."""

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai package not installed; `pip install openai`"
            ) from e
        from .config import load_env
        load_env()  # pick up OPENAI_API_KEY from .env if present
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Put it in a .env file in the "
                "project root (OPENAI_API_KEY=sk-...) or export it."
            )
        self._client = OpenAI(api_key=key)
        self._model = model

    def complete(self, system: str, user: str) -> LLMResponse:
        rsp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        text = rsp.choices[0].message.content or "{}"
        data = json.loads(text)
        return LLMResponse(
            dsl_code=data.get("dsl_code", ""),
            notes=data.get("notes", ""),
            raw=data,
        )


class FakeLLM:
    """
    Deterministic fake for tests and offline demos.

    Construct with a list of canned responses; each `complete()` call pops
    the next one. Useful for testing the retry loop without an API key.
    """

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        if not self._responses:
            raise RuntimeError("FakeLLM out of canned responses")
        return self._responses.pop(0)
