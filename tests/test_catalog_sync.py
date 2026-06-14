"""
Catalog drift test.

Regenerates the catalog in memory from the installed `steeleagle_sdk` and
asserts it matches the committed `nl2dsl/catalog_data.json`. If the SDK is
upgraded and the cached catalog is not refreshed, this fails with a reminder
to run `tools/gen_catalog.py`.

Skips cleanly when the SDK is not installed (e.g. CI without the dependency).

Run directly:
    uv run python tests/test_catalog_sync.py
"""

from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _sdk_available() -> bool:
    try:
        from steeleagle_sdk.dsl import build_mission  # noqa: F401
        return True
    except Exception:
        return False


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_catalog", ROOT / "tools" / "gen_catalog.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_catalog_in_sync_with_sdk() -> None:
    if not _sdk_available():
        print("        (steeleagle_sdk not installed; skipping)")
        return
    gen = _load_generator()
    fresh = gen.build_catalog_dict()
    committed = json.loads((ROOT / "nl2dsl" / "catalog_data.json").read_text())
    if fresh != committed:
        raise AssertionError(
            "nl2dsl/catalog_data.json is out of sync with the installed "
            "steeleagle_sdk. Re-run: uv run python tools/gen_catalog.py")


ALL_TESTS = [v for k, v in globals().items() if k.startswith("test_")]


def main() -> int:
    failures: list[str] = []
    for t in ALL_TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
            failures.append(t.__name__)
        except Exception as e:
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
            failures.append(t.__name__)
    print()
    print(f"{len(ALL_TESTS) - len(failures)}/{len(ALL_TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
