"""
Prompt builder.
 
Renders the SDK catalog into a compact reference and stitches it together
with few-shot examples and the user's natural-language request.
 
The system prompt is structured so the model has one clear job: emit JSON
with a `dsl_code` field. Any explanation goes in a separate `notes` field
so it never bleeds into the DSL itself.
"""
 
from __future__ import annotations
from pathlib import Path
from typing import Iterable
 
from .catalog import Entry, actions, events, declarable_datatypes
 
 
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
 
 
# -----------------------------------------------------------------------------
# Catalog rendering
# -----------------------------------------------------------------------------
def _render_entry(e: Entry) -> str:
    """One entry as a compact markdown block."""
    lines = [f"### `{e.name}` ({e.kind})", e.description]
    if e.params:
        lines.append("Parameters:")
        for p in e.params:
            req = "required" if p.required else "optional"
            extras = []
            if p.enum:
                extras.append(f"one of {p.enum}")
            if p.ref_kind:
                extras.append(f"must reference a {p.ref_kind}")
            extra_str = f" — {'; '.join(extras)}" if extras else ""
            desc = f" — {p.description}" if p.description else ""
            lines.append(f"  - `{p.name}` ({p.type}, {req}){extra_str}{desc}")
    else:
        lines.append("(no parameters)")
    return "\n".join(lines)
 
 
def _render_section(title: str, entries: Iterable[Entry]) -> str:
    body = "\n\n".join(_render_entry(e) for e in entries)
    return f"## {title}\n\n{body}"
 
 
def render_catalog() -> str:
    return "\n\n".join([
        _render_section("Available Datatypes (declare these in Data:)",
                        declarable_datatypes()),
        _render_section("Available Actions", actions()),
        _render_section("Available Events", events()),
    ])
 
 
# -----------------------------------------------------------------------------
# Few-shot examples
# -----------------------------------------------------------------------------
def load_examples() -> list[tuple[str, str]]:
    """Returns [(filename, content), ...] for each .dsl file in examples/."""
    out: list[tuple[str, str]] = []
    for path in sorted(EXAMPLES_DIR.glob("*.dsl")):
        out.append((path.name, path.read_text()))
    return out
 
 
def render_examples() -> str:
    pieces = []
    for name, content in load_examples():
        pieces.append(f"### Example: `{name}`\n```dsl\n{content.strip()}\n```")
    return "\n\n".join(pieces)
 
 
# -----------------------------------------------------------------------------
# Full prompts
# -----------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """\
You translate natural-language drone mission descriptions into SteelEagle DSL.
 
SteelEagle DSL is a finite-state-machine description language with four
stanzas in this exact order: `Data:`, `Actions:`, `Events:`, `Mission:`.
 
# Syntax rules
 
1. Each Data/Actions/Events line declares an instance:
   `ClassName instance_name(param = value, ...)`
   - `ClassName` must come from the catalog below.
   - `instance_name` is your chosen snake_case identifier; it is what the
     Mission stanza references.
   - Parameter values are: numbers, bare identifiers (for both string values
     AND references to earlier instances), arrays `[a, b]`, or `_` for None.
   - CRITICAL: quoted strings are NOT valid. Write `area = Rectangle`,
     NEVER `area = 'Rectangle'`. Identifiers cannot contain hyphens.
   - Nested objects (e.g. a Detection used by Track or DetectionFound) must
     be declared in `Data:` first and referenced by name. NEVER write an
     inline object like `location = Location(latitude = ..., ...)`. Instead
     declare `Location drop(latitude = ..., longitude = ..., altitude = ...)`
     in `Data:` and write `location = drop`. Do NOT use inline
     object syntax like `Location loc(40.4, -79.9, 8.0)` — the compiler
     rejects it even though it looks plausible.
   - Use `=` for parameters (`param = value`). A colon also parses, but
     always use `=` for consistency.
 
2. Stanza structure (enforced by the grammar):
   - Order is fixed: `Data:`, `Actions:`, `Events:`, `Mission:`.
   - `Actions:` and `Mission:` are REQUIRED. `Data:` and `Events:` may be
     omitted entirely when a mission needs no data objects or no events
     (e.g. a simple take-off-then-land mission needs neither).
   - In `Mission:`, the `Start` line comes first, immediately after the
     `Mission:` header, then the `During` blocks follow.
 
3. The Mission stanza:
   - `Start <action_name>` declares the initial state (NO colon after
     Start). EXACTLY ONE.
   - `During <action_name>:` opens a block of transitions for that action.
   - Each transition line: `<event_name> -> <action_name>`
   - ALL transition lines MUST live inside a `During` block. Never put a
     transition in the Data:, Actions:, or Events: stanza.
   - The reserved event `done` fires when the action finishes naturally.
   - Every action used as a transition target MUST be declared in `Actions:`.
   - Every event used as a transition trigger MUST be declared in `Events:`
     (except `done`, which is reserved).
   - There is NO `end`, `stop`, or terminal state. A mission "ends" by
     transitioning into a terminal action such as `Land` or `ReturnToHome`
     (which you must declare in Actions:). Never write `-> end`.
   - Every action you declare MUST be reachable from Start through some chain
     of transitions. Do NOT declare actions you never transition into. If you
     declare `Land`, wire it in (e.g. `During return_to_home: done -> land`).
   - To express "after N seconds/minutes", add a `TimeReached` event and use
     it as a transition trigger on the relevant `During` block. Do NOT add a
     standalone `Wait` action to "represent" elapsed time.
 
4. Comments start with `#` and run to the end of the line.
 
# Catalog
 
{catalog}
 
# Few-shot examples
 
{examples}
 
# Formal grammar reference (authoritative)
 
This is the structural grammar (EBNF). The catalog above is the source of
truth for class names and parameters; this is for structure only. `_NL` is a
newline; `?` means optional; `*` means zero-or-more.
 
```
start: data_block? actions_block events_block? mission_block
data_block:    "Data:"    _NL (datum_decl)+
actions_block: "Actions:" _NL (action_decl)+
events_block:  "Events:"  _NL (event_decl)+
mission_block: "Mission:" _NL mission_start during_block*
 
datum_decl:   NAME NAME body?       // ClassName instance_name(args)
action_decl:  NAME NAME body?
event_decl:   NAME NAME body?
body:         "(" [attr ("," attr)*] ")"
attr:         NAME "=" value
value:        NUMBER | NAME | array | "_"      // NAME = bare identifier; "_" = None
array:        "[" [value ("," value)*] "]"
 
mission_start: "Start" NAME                    // no colon
during_block:  "During" NAME ":" _NL (transition_rule)+
transition_rule: NAME "->" NAME                // event_name -> action_name
```
 
# Output format
 
Respond with a single JSON object, no markdown fences:
 
{{
  "dsl_code": "<the complete DSL file as a single string>",
  "notes": "<one-paragraph explanation of your design decisions for the user>"
}}
 
If the user's request is ambiguous or impossible given the catalog, still
emit your best-effort DSL and explain the assumptions or limitations in
`notes`. Do NOT invent class names that aren't in the catalog.
"""
 
 
def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        catalog=render_catalog(),
        examples=render_examples(),
    )
 
 
def build_user_prompt(natural_language: str, prior_error: str | None = None) -> str:
    """User message. On retry, `prior_error` carries the validator feedback."""
    if prior_error:
        return (
            f"Your previous DSL output failed validation:\n\n"
            f"```\n{prior_error}\n```\n\n"
            f"Re-emit the corrected DSL for the ORIGINAL request below. "
            f"Address every error listed above.\n\n"
            f"Original request:\n{natural_language}"
        )
    return f"Mission request:\n{natural_language}"