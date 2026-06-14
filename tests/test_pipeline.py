"""
End-to-end tests using FakeLLM.

Goals:
  1. Validator correctly accepts the canonical example DSLs.
  2. Validator catches a representative set of LLM mistakes.
  3. Pipeline retries on validation failure and stops at success.
  4. Pipeline gives up after MAX_ATTEMPTS.
"""

from __future__ import annotations
import sys
from pathlib import Path

# Allow running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nl2dsl.validator import validate, to_mission_ir, normalize_dsl
from nl2dsl.pipeline import translate
from nl2dsl.llm import FakeLLM, LLMResponse


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _assert_valid(name: str, dsl: str) -> None:
    errs = validate(dsl)
    if errs:
        msg = f"\n  ".join(str(e) for e in errs)
        raise AssertionError(f"[{name}] expected no errors, got:\n  {msg}")


def _assert_error_matching(name: str, dsl: str, substring: str) -> None:
    errs = validate(dsl)
    if not any(substring in str(e) for e in errs):
        joined = "\n  ".join(str(e) for e in errs) or "(no errors)"
        raise AssertionError(
            f"[{name}] expected an error containing {substring!r}, got:\n  {joined}"
        )


# -----------------------------------------------------------------------------
# Validator: canonical examples should pass
# -----------------------------------------------------------------------------
def test_examples_validate() -> None:
    for path in sorted(EXAMPLES.glob("*.dsl")):
        _assert_valid(path.name, path.read_text())


# -----------------------------------------------------------------------------
# Validator: representative LLM mistakes
# -----------------------------------------------------------------------------
def test_unknown_class() -> None:
    dsl = """
Data:
Actions:
    TakOff t(take_off_altitude = 10.0)
Events:
Mission:
    Start t
"""
    _assert_error_matching("unknown_class", dsl, "unknown class `TakOff`")


def test_missing_required_param() -> None:
    dsl = """
Data:
Actions:
    TakeOff t()
Events:
Mission:
    Start t
"""
    _assert_error_matching("missing_param", dsl,
                           "missing required parameter `take_off_altitude`")


def test_wrong_type() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = high)
Events:
Mission:
    Start t
"""
    _assert_error_matching("wrong_type", dsl, "expects a float")


def test_quoted_string_rejected() -> None:
    dsl = """
Data:
    Waypoints wp(alt = 5.0, area = 'Zone', algo = edge)
Actions:
    Patrol p(waypoints = wp)
Events:
Mission:
    Start p
"""
    _assert_error_matching("quoted_string", dsl, "quoted strings are not supported")


def test_start_colon_rejected() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = 5.0)
Events:
Mission:
    Start: t
"""
    _assert_error_matching("start_colon", dsl, "takes no colon")


def test_undeclared_ref() -> None:
    dsl = """
Data:
Actions:
    Patrol p(waypoints = ghost_path)
Events:
Mission:
    Start p
"""
    _assert_error_matching("undeclared_ref", dsl,
                           "references undeclared name `ghost_path`")


def test_ref_wrong_kind() -> None:
    dsl = """
Data:
    Location wrong(latitude = 1.0, longitude = 2.0, altitude = 3.0)
Actions:
    Patrol p(waypoints = wrong)
Events:
Mission:
    Start p
"""
    _assert_error_matching("ref_wrong_kind", dsl,
                           "expects a Waypoints")


def test_missing_start() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = 5.0)
Events:
Mission:
    During t:
        done -> t
"""
    _assert_error_matching("missing_start", dsl, "missing `Start:`")


def test_start_undeclared_action() -> None:
    dsl = """
Data:
Actions:
Events:
Mission:
    Start ghost
"""
    _assert_error_matching("start_undeclared", dsl,
                           "is not declared in the Actions stanza")


def test_unknown_event_in_transition() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = 5.0)
    Hold h()
Events:
Mission:
    Start t
    During t:
        done -> h
        mystery_event -> h
"""
    _assert_error_matching("unknown_event", dsl,
                           "unknown event `mystery_event`")


def test_unreachable_action() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = 5.0)
    Hold h()
    Land l()
Events:
Mission:
    Start t
    During t:
        done -> h
"""
    _assert_error_matching("unreachable", dsl,
                           "`l` is declared but unreachable")


def test_enum_value() -> None:
    dsl = """
Data:
    Waypoints wp(alt = 5.0, area = X, algo = spiral)
Actions:
    TakeOff t(take_off_altitude = 5.0)
    Patrol p(waypoints = wp)
Events:
Mission:
    Start t
    During t:
        done -> p
"""
    _assert_error_matching("enum", dsl, "must be one of")

def test_transition_outside_mission() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = 5.0)
    ReturnToHome rth()
Events:
    done -> rth
Mission:
    Start t
"""
    _assert_error_matching("transition_misplaced", dsl,
                           "must go inside a `During")


def test_invented_end_state() -> None:
    dsl = """
Data:
Actions:
    TakeOff t(take_off_altitude = 5.0)
Events:
Mission:
    Start t
    During t:
        done -> end
"""
    _assert_error_matching("invented_end", dsl, "NO terminal/end state")


# -----------------------------------------------------------------------------
# Normalization / auto-fixes (the e1/e2 failure modes)
# -----------------------------------------------------------------------------
def test_empty_stanzas_autofixed() -> None:
    # The exact shape gpt-4o-mini produced for "take off then land": empty
    # Data + Events stanzas, no trailing newline. Must validate cleanly and
    # report the fixes it applied.
    dsl = ("Data:\nActions:\n    TakeOff t(take_off_altitude = 10.0)\n"
           "    Land l()\nEvents:\nMission:\n    Start t\n    During t:\n"
           "        done -> l")
    fixed, fixes = normalize_dsl(dsl)
    assert "Data:" not in fixed and "Events:" not in fixed, fixed
    assert fixed.endswith("\n")
    assert any("Data" in f for f in fixes), fixes
    assert any("Events" in f for f in fixes), fixes
    assert any("newline" in f for f in fixes), fixes
    if validate(dsl):
        raise AssertionError(f"expected no errors after auto-fix, got: "
                             f"{[str(e) for e in validate(dsl)]}")


def test_trailing_newline_autofixed() -> None:
    fixed, fixes = normalize_dsl("Actions:\n    Land l()\nMission:\n    Start l")
    assert fixed.endswith("\n")
    assert any("newline" in f for f in fixes), fixes


def test_populated_stanzas_not_dropped() -> None:
    # A non-empty Events stanza must survive normalization.
    dsl = ("Data:\n    Detection d(class_name = person)\nActions:\n"
           "    Track t(target = d)\nEvents:\n    DetectionFound f(target = d)\n"
           "Mission:\n    Start t\n")
    fixed, fixes = normalize_dsl(dsl)
    assert "Data:" in fixed and "Events:" in fixed, fixed
    assert fixes == [], fixes


def test_inline_object_rejected() -> None:
    # e4 failure mode: model writes an inline object instead of declaring it
    # in Data: and referencing by name. Must give an actionable message.
    dsl = """
Actions:
    SetGlobalPosition fly_to(location = Location(latitude = 40.4433, longitude = -79.9436, altitude = 12.0))
    ReturnToHome return_home()
Mission:
    Start fly_to
    During fly_to:
        done -> return_home
"""
    _assert_error_matching("inline_object", dsl, "inline objects are not supported")


def test_stanza_out_of_order() -> None:
    # m4 attempt-3 failure mode: Events before Actions. Must produce a clear
    # message instead of the cryptic Lark "Unexpected COLON".
    dsl = """
Data:
    Detection d(class_name = person)
Events:
    DetectionFound f(target = d)
Actions:
    Track t(target = d)
Mission:
    Start t
"""
    _assert_error_matching("stanza_order", dsl, "out of order")


def test_conditional_required_survey_missing() -> None:
    dsl = """
Data:
    Waypoints wp(alt = 20.0, area = SearchZone, algo = survey)
Actions:
    Patrol p(waypoints = wp)
Events:
Mission:
    Start p
"""
    _assert_error_matching("survey_missing", dsl, "with `algo = survey` requires")


def test_conditional_required_survey_satisfied() -> None:
    dsl = """
Data:
    Waypoints wp(alt = 20.0, area = SearchZone, algo = survey, spacing = 10.0, angle_degrees = 0.0, trigger_distance = 5.0)
Actions:
    Patrol p(waypoints = wp)
Events:
Mission:
    Start p
"""
    _assert_valid("survey_satisfied", dsl)


def test_empty_stanza_example_compiles() -> None:
    from nl2dsl.compiler import compile_dsl, sdk_available
    if not sdk_available():
        print("        (steeleagle_sdk not installed; skipping)")
        return
    dsl = ("Data:\nActions:\n    TakeOff t(take_off_altitude = 10.0)\n"
           "    Land l()\nEvents:\nMission:\n    Start t\n    During t:\n"
           "        done -> l")
    res = compile_dsl(dsl)
    assert res.ok, f"expected compile success after auto-fix, got: {res.error}"


# -----------------------------------------------------------------------------
# Mission IR
# -----------------------------------------------------------------------------
def test_mission_ir_shape() -> None:
    dsl = (EXAMPLES / "patrol.dsl").read_text()
    ir = to_mission_ir(dsl)
    assert set(ir) == {"data", "actions", "events", "mission"}, ir.keys()
    assert ir["mission"]["start"] == "take_off"
    patrol_blk = next(b for b in ir["mission"]["during"]
                      if b["action"] == "patrol")
    assert len(patrol_blk["transitions"]) == 3, patrol_blk


def test_real_compiler_examples() -> None:
    from nl2dsl.compiler import compile_dsl, sdk_available
    if not sdk_available():
        print("        (steeleagle_sdk not installed; skipping)")
        return
    for path in sorted(EXAMPLES.glob("*.dsl")):
        res = compile_dsl(path.read_text())
        assert res.ok, f"{path.name}: {res.error}"
        assert res.mission_json and "actions" in res.mission_json


# -----------------------------------------------------------------------------
# Pipeline: retry on failure, succeed on later attempt
# -----------------------------------------------------------------------------
def test_pipeline_succeeds_first_try() -> None:
    good = (EXAMPLES / "delivery.dsl").read_text()
    llm = FakeLLM([LLMResponse(dsl_code=good, notes="ok", raw={})])
    result = translate("deliver a package", llm)
    assert result.ok, [str(e) for e in result.final_errors]
    assert result.n_attempts == 1
    assert result.mission_ir is not None


def test_pipeline_retries_then_succeeds() -> None:
    # First response: an obviously broken DSL.
    bad = """
Data:
Actions:
    TakOff t(take_off_altitude = 5.0)
Events:
Mission:
    Start t
"""
    good = (EXAMPLES / "delivery.dsl").read_text()
    llm = FakeLLM([
        LLMResponse(dsl_code=bad, notes="", raw={}),
        LLMResponse(dsl_code=good, notes="fixed", raw={}),
    ])
    result = translate("deliver a package", llm)
    assert result.ok, [str(e) for e in result.final_errors]
    assert result.n_attempts == 2, result.n_attempts
    # Second call should include the validator feedback in its user prompt:
    second_user = llm.calls[1][1]
    assert "Validation produced the following errors" in second_user, second_user
    assert "unknown class `TakOff`" in second_user, second_user


def test_pipeline_gives_up() -> None:
    bad = """
Data:
Actions:
    TakOff t(take_off_altitude = 5.0)
Events:
Mission:
"""
    # Three bad responses in a row.
    llm = FakeLLM([
        LLMResponse(dsl_code=bad, notes="", raw={}),
        LLMResponse(dsl_code=bad, notes="", raw={}),
        LLMResponse(dsl_code=bad, notes="", raw={}),
    ])
    result = translate("any mission", llm)
    assert not result.ok
    assert result.n_attempts == 3
    assert result.mission_ir is None
    assert len(result.final_errors) > 0


# -----------------------------------------------------------------------------
# Test runner
# -----------------------------------------------------------------------------
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
