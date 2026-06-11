"""
Real-LLM evaluation harness.

Runs a fixed suite of natural-language mission requests through the full
pipeline (LLM -> static validator -> real compiler -> retry loop) and
reports:
  - pass rate (first-try and within-3-attempts)
  - error categories encountered
  - token usage and estimated cost
  - all failing DSL outputs saved to eval_results/ for manual review

Usage (from project root, with OPENAI_API_KEY in .env):
    python tools/eval_real_llm.py
    python tools/eval_real_llm.py --model gpt-4o          # stronger model
    python tools/eval_real_llm.py --only easy             # subset
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nl2dsl.pipeline import translate
from nl2dsl.compiler import sdk_available

# -----------------------------------------------------------------------------
# Test missions. Three tiers:
#   easy   — single capability, no events
#   medium — 2-3 states, one event
#   hard   — multi-state FSM, multiple events, survey params, Detection refs
# -----------------------------------------------------------------------------
MISSIONS: list[dict] = [
    # --- easy ---
    {"id": "e1", "tier": "easy",
     "request": "Take off to 10 meters, then land."},
    {"id": "e2", "tier": "easy",
     "request": "Take off to 20 meters, hold position for 60 seconds, then land."},
    {"id": "e3", "tier": "easy",
     "request": "起飞到15米，原地等待30秒，然后返航。"},
    {"id": "e4", "tier": "easy",
     "request": "Fly to latitude 40.4433, longitude -79.9436 at 12 meters "
                "altitude, then return home."},

    # --- medium ---
    {"id": "m1", "tier": "medium",
     "request": "Take off to 15 meters and patrol the area named Rectangle "
                "along its edges. If the battery drops to 40 percent, "
                "return home."},
    {"id": "m2", "tier": "medium",
     "request": "Take off to 10 meters, wait 2 minutes, then go to the "
                "delivery point at lat 40.444, lon -79.945, altitude 8. "
                "After arriving, wait 30 seconds and come back home."},
    {"id": "m3", "tier": "medium",
     "request": "起飞后在名为 Campus 的区域边缘巡逻，电量低于35%就返航降落。"},
    {"id": "m4", "tier": "medium",
     "request": "Patrol the SearchZone area at 20 meters. After 5 minutes "
                "of total mission time, return to home."},

    # --- hard ---
    {"id": "h1", "tier": "hard",
     "request": "Take off to 15 meters, patrol the Rectangle area on its "
                "edges. If you see a person, start tracking them; if you "
                "lose them, go back to patrolling. Return home when the "
                "battery hits 50 percent."},
    {"id": "h2", "tier": "hard",
     "request": "Survey the area called FieldA at 25 meters with 10 meter "
                "spacing between survey columns at 0 degrees, triggering a "
                "snapshot every 5 meters. If a car is detected with "
                "confidence above 0.7, track it. Battery below 30 means "
                "land immediately."},
    {"id": "h3", "tier": "hard",
     "request": "无人机起飞到20米，在名为 Harbor 的区域沿边巡逻。看到船(boat)就"
                "跟踪，跟丢了回去继续巡逻。任意时刻电量到40%立刻返航。"},
    {"id": "h4", "tier": "hard",
     "request": "Take off to 12 meters and patrol PathOne as a corridor "
                "with 8 meter spacing at 90 degrees. When a person is "
                "found, hold position for 20 seconds, then resume the "
                "patrol. At 45 percent battery, return home and land."},
]

# Pricing per 1M tokens (June 2026; update as needed)
PRICING = {
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.00},
}


class MeteredOpenAILLM:
    """OpenAILLM wrapper that counts tokens across calls."""

    def __init__(self, model: str):
        from nl2dsl.llm import OpenAILLM
        self._inner = OpenAILLM(model=model)
        self.model = model
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(self, system: str, user: str):
        import json as _json
        from nl2dsl.llm import LLMResponse
        rsp = self._inner._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        if rsp.usage:
            self.prompt_tokens += rsp.usage.prompt_tokens
            self.completion_tokens += rsp.usage.completion_tokens
        data = _json.loads(rsp.choices[0].message.content or "{}")
        return LLMResponse(
            dsl_code=data.get("dsl_code", ""),
            notes=data.get("notes", ""),
            raw=data,
        )

    @property
    def est_cost_usd(self) -> float:
        p = PRICING.get(self.model)
        if not p:
            return 0.0
        return (self.prompt_tokens * p["in"]
                + self.completion_tokens * p["out"]) / 1e6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--only", choices=["easy", "medium", "hard"],
                    help="Run only one tier.")
    args = ap.parse_args()

    if not sdk_available():
        print("WARNING: steeleagle_sdk not importable — the real compiler "
              "stage will be SKIPPED. Results are static-validation only.\n")

    missions = [m for m in MISSIONS
                if not args.only or m["tier"] == args.only]

    out_dir = Path(__file__).resolve().parent.parent / "eval_results"
    out_dir.mkdir(exist_ok=True)

    llm = MeteredOpenAILLM(model=args.model)
    rows = []
    t0 = time.time()

    for m in missions:
        print(f"[{m['id']}] ({m['tier']}) {m['request'][:60]}...")
        result = translate(m["request"], llm)
        status = "PASS" if result.ok else "FAIL"
        print(f"        {status} in {result.n_attempts} attempt(s)")

        error_msgs = [str(e) for a in result.attempts for e in a.errors]
        rows.append({
            "id": m["id"], "tier": m["tier"], "ok": result.ok,
            "attempts": result.n_attempts, "errors": error_msgs,
        })

        # Save every result (DSL + notes + errors) for review
        (out_dir / f"{m['id']}_{status}.json").write_text(json.dumps({
            "request": m["request"],
            "ok": result.ok,
            "attempts": [
                {"dsl": a.dsl_code, "notes": a.notes,
                 "errors": [str(e) for e in a.errors]}
                for a in result.attempts
            ],
            "mission_json": result.mission_ir,
        }, ensure_ascii=False, indent=2))

    dt = time.time() - t0

    # ---- Report ----
    n = len(rows)
    n_pass = sum(r["ok"] for r in rows)
    n_first = sum(r["ok"] and r["attempts"] == 1 for r in rows)
    print("\n" + "=" * 60)
    print(f"Model: {args.model}   Missions: {n}   Wall time: {dt:.0f}s")
    print(f"Pass within {3} attempts : {n_pass}/{n} ({100*n_pass/n:.0f}%)")
    print(f"Pass on first attempt    : {n_first}/{n} ({100*n_first/n:.0f}%)")
    for tier in ("easy", "medium", "hard"):
        sub = [r for r in rows if r["tier"] == tier]
        if sub:
            p = sum(r["ok"] for r in sub)
            print(f"  {tier:<7}: {p}/{len(sub)}")
    print(f"Tokens: {llm.prompt_tokens} in / {llm.completion_tokens} out"
          f"   est. cost: ${llm.est_cost_usd:.3f}")
    fails = [r for r in rows if not r["ok"]]
    if fails:
        print("\nFailures (see eval_results/*.json for full DSL):")
        for r in fails:
            first_err = r["errors"][-1] if r["errors"] else "?"
            print(f"  {r['id']}: {first_err[:100]}")
    print(f"\nPer-mission details saved to {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
