"""
CLI entrypoint.

Usage:
    python -m nl2dsl.cli "fly to the warehouse and drop a package"
    python -m nl2dsl.cli --file request.txt --out mission.json
    python -m nl2dsl.cli --validate-only mission.dsl
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .llm import OpenAILLM
from .pipeline import translate
from .validator import validate, to_mission_ir


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nl2dsl")
    p.add_argument("request", nargs="?",
                   help="Natural language mission description.")
    p.add_argument("--file", type=Path,
                   help="Read request from a file instead of argv.")
    p.add_argument("--out", type=Path,
                   help="Write the compiled mission JSON to this path.")
    p.add_argument("--dsl-out", type=Path,
                   help="Write the raw DSL text to this path.")
    p.add_argument("--model", default="gpt-4o-mini",
                   help="OpenAI model name (default: gpt-4o-mini).")
    p.add_argument("--validate-only", type=Path,
                   help="Skip LLM; just validate the DSL file at this path.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print every retry attempt.")
    args = p.parse_args(argv)

    if args.validate_only:
        dsl_text = args.validate_only.read_text()
        errs = validate(dsl_text)
        if errs:
            print("Validation FAILED:", file=sys.stderr)
            for e in errs:
                print(f"  {e}", file=sys.stderr)
            return 1
        print("Validation OK.", file=sys.stderr)
        from .compiler import compile_dsl
        comp = compile_dsl(dsl_text)
        if comp.available and not comp.ok:
            print(f"Real compiler FAILED: {comp.error}", file=sys.stderr)
            return 1
        if comp.ok:
            print("Real compiler OK (steeleagle_sdk).", file=sys.stderr)
            ir = comp.mission_json
        else:
            print("steeleagle_sdk not installed; using placeholder IR.",
                  file=sys.stderr)
            ir = to_mission_ir(dsl_text)
        if args.out:
            args.out.write_text(json.dumps(ir, indent=2))
            print(f"Wrote {args.out}", file=sys.stderr)
        else:
            print(json.dumps(ir, indent=2))
        return 0

    if args.file:
        request = args.file.read_text()
    elif args.request:
        request = args.request
    else:
        p.error("provide REQUEST or --file or --validate-only")

    llm = OpenAILLM(model=args.model)
    result = translate(request, llm)

    if args.verbose:
        for i, att in enumerate(result.attempts, 1):
            print(f"--- attempt {i} ({len(att.errors)} errors) ---", file=sys.stderr)
            if att.errors:
                for e in att.errors[:10]:
                    print(f"  {e}", file=sys.stderr)

    if not result.ok:
        print(f"\nTranslation FAILED after {result.n_attempts} attempts.",
              file=sys.stderr)
        print("Final errors:", file=sys.stderr)
        for e in result.final_errors:
            print(f"  {e}", file=sys.stderr)
        print("\nLast DSL attempt:", file=sys.stderr)
        print(result.dsl_code, file=sys.stderr)
        return 2

    # Success!
    if args.dsl_out:
        args.dsl_out.write_text(result.dsl_code)
        print(f"Wrote DSL to {args.dsl_out}", file=sys.stderr)
    if args.out:
        args.out.write_text(json.dumps(result.mission_ir, indent=2))
        print(f"Wrote mission JSON to {args.out}", file=sys.stderr)

    # If no output paths given, print to stdout for piping.
    if not args.dsl_out and not args.out:
        print("=== DSL ===")
        print(result.dsl_code)
        print("\n=== mission.json ===")
        print(json.dumps(result.mission_ir, indent=2))
        if result.notes:
            print("\n=== notes ===")
            print(result.notes)

    return 0


if __name__ == "__main__":
    sys.exit(main())
