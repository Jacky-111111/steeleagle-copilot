"""
Pipeline.

Glues LLM, prompt builder, and validator into a single
`translate(natural_language) -> Result` call.

Behaviour:
1. Build system + user prompts.
2. Ask the LLM.
3. Run the validator over `dsl_code`.
4. If errors: feed them back to the LLM with the original request, retry.
5. Stop after MAX_ATTEMPTS or on success.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from .llm import LLM, LLMResponse
from .prompt import build_system_prompt, build_user_prompt
from .validator import validate, to_mission_ir, ValidationError
from .compiler import compile_dsl


MAX_ATTEMPTS = 3   # User-confirmed: 3 attempts max.


@dataclass
class Attempt:
    """Record of one round trip to the LLM and the validator."""
    dsl_code: str
    notes: str
    errors: list[ValidationError] = field(default_factory=list)


@dataclass
class Result:
    ok: bool
    dsl_code: str
    mission_ir: dict[str, Any] | None
    notes: str
    attempts: list[Attempt]

    @property
    def n_attempts(self) -> int:
        return len(self.attempts)

    @property
    def final_errors(self) -> list[ValidationError]:
        return self.attempts[-1].errors if self.attempts else []


def translate(
    natural_language: str,
    llm: LLM,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> Result:
    system_prompt = build_system_prompt()
    attempts: list[Attempt] = []

    prior_error: str | None = None
    for _ in range(max_attempts):
        user_prompt = build_user_prompt(natural_language, prior_error=prior_error)
        rsp: LLMResponse = llm.complete(system_prompt, user_prompt)

        errors = validate(rsp.dsl_code)
        attempts.append(Attempt(
            dsl_code=rsp.dsl_code,
            notes=rsp.notes,
            errors=errors,
        ))

        if not errors:
            comp = compile_dsl(rsp.dsl_code)
            if comp.available and not comp.ok:
                # Real compiler rejected it; feed its error back and retry.
                attempts[-1].errors = [ValidationError(
                    None, f"real compiler error: {comp.error}")]
                prior_error = (
                    f"The SteelEagle compiler rejected the DSL:\n{comp.error}"
                )
                continue
            mission_ir = (comp.mission_json if comp.ok
                          else to_mission_ir(rsp.dsl_code))
            return Result(
                ok=True,
                dsl_code=rsp.dsl_code,
                mission_ir=mission_ir,
                notes=rsp.notes,
                attempts=attempts,
            )

        # Build feedback for the retry. Capping at 20 errors so we don't
        # blow up the prompt on catastrophically wrong output.
        bullets = "\n".join(f"- {e}" for e in errors[:20])
        prior_error = (
            f"Validation produced the following errors:\n{bullets}"
        )

    # All attempts exhausted, return the last (failing) one.
    last = attempts[-1]
    return Result(
        ok=False,
        dsl_code=last.dsl_code,
        mission_ir=None,
        notes=last.notes,
        attempts=attempts,
    )
