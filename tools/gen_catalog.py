"""
Catalog generator.

Introspects the installed `steeleagle_sdk` DSL registry and writes a cached
catalog to `nl2dsl/catalog_data.json`. At runtime `nl2dsl.catalog` loads that
JSON, so the package never has to import the SDK to know which Actions/Events/
Datatypes exist or what parameters they take.

Run this whenever the SDK is upgraded:

    uv run python tools/gen_catalog.py

A drift test (`tests/test_catalog_sync.py`) regenerates the catalog in memory
and asserts it matches the committed JSON, so an out-of-date catalog fails CI.

NOTE: conditional-required rules (e.g. Waypoints `algo = survey` needs
`spacing`/`angle_degrees`/`trigger_distance`) live in an imperative Pydantic
`@model_validator` and are NOT introspectable from the field schema. Those are
hand-maintained in `nl2dsl/catalog.py :: CONDITIONAL_REQUIRED` and are
intentionally not part of this generated file.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from typing import Any

OUT_PATH = Path(__file__).resolve().parent.parent / "nl2dsl" / "catalog_data.json"


def _build() -> dict[str, Any]:
    from steeleagle_sdk.dsl.compiler import loader, registry
    from steeleagle_sdk.dsl.types.base import Datatype as DslDatatype

    loader.load_all()  # populate the registry via @register_* decorators

    def map_type(ann: Any) -> tuple[str, list[str] | None, str | None]:
        """Map a Pydantic field annotation to (param_type, enum, ref_kind)."""
        origin = typing.get_origin(ann)
        if origin is typing.Literal:
            return "str", [str(a) for a in typing.get_args(ann)], None

        args = typing.get_args(ann)
        # Strip the None arm of Optional[...] / `X | None`.
        arms = [a for a in args if a is not type(None)] if args else [ann]

        # Literal nested inside Optional[...]
        for a in arms:
            if typing.get_origin(a) is typing.Literal:
                return "str", [str(x) for x in typing.get_args(a)], None
        # Reference to another declared datatype instance.
        for a in arms:
            if isinstance(a, type) and issubclass(a, DslDatatype):
                return "ref", None, a.__name__
        # Primitives.
        for a in arms:
            if a is float:
                return "float", None, None
            if a is int:
                return "int", None, None
            if a is bool:
                return "bool", None, None
            if a is str:
                return "str", None, None
            if a is list or typing.get_origin(a) is list:
                return "list", None, None
        # Enums and other exotic annotations: stay permissive (no strict check).
        return "any", None, None

    def clean_doc(cls: type) -> str:
        doc = (cls.__doc__ or "").strip()
        return " ".join(doc.split())

    def jsonable_default(field: Any) -> Any:
        if field.is_required():
            return None
        d = field.default
        return d if isinstance(d, (int, float, str, bool)) else None

    def entry(cls: type, kind: str) -> dict[str, Any]:
        params = []
        for name, f in cls.model_fields.items():
            ptype, enum, ref_kind = map_type(f.annotation)
            params.append({
                "name": name,
                "type": ptype,
                "required": bool(f.is_required()),
                "description": (f.description or "").strip(),
                "enum": enum,
                "ref_kind": ref_kind,
                "default": jsonable_default(f),
            })
        return {
            "name": cls.__name__,
            "kind": kind,
            "description": clean_doc(cls),
            "params": params,
        }

    actions = sorted((entry(c, "action") for c in set(registry._ACTIONS.values())),
                     key=lambda e: e["name"])
    events = sorted((entry(c, "event") for c in set(registry._EVENTS.values())),
                    key=lambda e: e["name"])
    datatypes = sorted((entry(c, "data") for c in set(registry._DATA.values())),
                       key=lambda e: e["name"])

    # Datatypes a user actually declares in `Data:` are exactly those referenced
    # by some Action/Event field. Derive automatically (no hand-maintenance).
    declarable: set[str] = set()
    for e in (*actions, *events):
        for p in e["params"]:
            if p["ref_kind"]:
                declarable.add(p["ref_kind"])

    return {
        "actions": actions,
        "events": events,
        "datatypes": datatypes,
        "declarable_datatypes": sorted(declarable),
    }


def build_catalog_dict() -> dict[str, Any]:
    """Public entry point used by both the CLI and the drift test."""
    return _build()


def main() -> int:
    data = build_catalog_dict()
    OUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT_PATH}")
    print(f"  actions={len(data['actions'])} events={len(data['events'])} "
          f"datatypes={len(data['datatypes'])} "
          f"declarable={len(data['declarable_datatypes'])}")
    print(f"  declarable datatypes: {data['declarable_datatypes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
