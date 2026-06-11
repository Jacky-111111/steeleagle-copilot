"""
SteelEagle SDK catalog.

v2: Corrected against the REAL steeleagle_sdk v3.1.0 source
(sdk/src/steeleagle_sdk/dsl/types/). Class names, parameter names, types,
and which parameters are required now match the real Pydantic models.

Key real-grammar facts (from dsl/grammar/dronedsl.lark):
- Values are bare NAME tokens, numbers, arrays, or `_` (None). NO quoted strings.
- NAME = [A-Za-z_][A-Za-z0-9_]*  (no hyphens).
- `Start <action>` in the Mission stanza takes NO colon.
- Nested objects must be pre-declared in Data: and referenced by name
  (inline datum syntax is positional-only; avoid it).

Still hardcoded; replace with runtime introspection of
steeleagle_sdk.dsl.types later.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


ParamType = Literal["float", "int", "str", "bool", "list", "ref"]


@dataclass
class Param:
    name: str
    type: ParamType
    required: bool = True
    description: str = ""
    enum: list[str] | None = None
    ref_kind: str | None = None


@dataclass
class Entry:
    name: str
    kind: Literal["data", "action", "event"]
    description: str
    params: list[Param] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Datatypes (steeleagle_sdk.dsl.types.datatypes)
# -----------------------------------------------------------------------------
DATATYPES: list[Entry] = [
    Entry(
        name="Waypoints",
        kind="data",
        description=(
            "Geolocation waypoints generated from a KML area name and a "
            "slicing algorithm."
        ),
        params=[
            Param("area", "str", required=True,
                  description="KML area name (bare identifier, no quotes)."),
            Param("alt", "float", required=True,
                  description="Altitude waypoints are visited at [m]."),
            Param("algo", "str", required=False,
                  enum=["edge", "survey", "corridor"],
                  description="edge follows points in order; survey/corridor "
                              "cover the enclosed area. Default: edge."),
            Param("spacing", "float", required=False,
                  description="Column spacing [m]. REQUIRED for survey/corridor."),
            Param("angle_degrees", "float", required=False,
                  description="Column angle [deg]. REQUIRED for survey/corridor."),
            Param("trigger_distance", "float", required=False,
                  description="Snapshot trigger distance [m]. REQUIRED for survey."),
        ],
    ),
    Entry(
        name="Location",
        kind="data",
        description="Global GPS position.",
        params=[
            Param("latitude", "float", required=False),
            Param("longitude", "float", required=False),
            Param("altitude", "float", required=False,
                  description="Above MSL or takeoff [m]."),
            Param("heading", "float", required=False, description="Degrees."),
        ],
    ),
    Entry(
        name="Velocity",
        kind="data",
        description="Velocity vector.",
        params=[
            Param("x_vel", "float", required=False, description="Forward m/s."),
            Param("y_vel", "float", required=False, description="Lateral m/s."),
            Param("z_vel", "float", required=False, description="Vertical m/s."),
            Param("angular_vel", "float", required=False,
                  description="Yaw rate deg/s."),
        ],
    ),
    Entry(
        name="Detection",
        kind="data",
        description=(
            "An object-detection filter. Declare one in Data: and reference "
            "it from Track actions and DetectionFound events."
        ),
        params=[
            Param("class_name", "str", required=False,
                  description="Class to match, e.g. person, car."),
            Param("score", "float", required=False,
                  description="Minimum confidence score 0-1."),
        ],
    ),
]


# -----------------------------------------------------------------------------
# Actions (steeleagle_sdk.dsl.types.actions, registered subset)
# -----------------------------------------------------------------------------
ACTIONS: list[Entry] = [
    Entry(
        name="TakeOff",
        kind="action",
        description="Take off to a relative altitude.",
        params=[
            Param("take_off_altitude", "float", required=True,
                  description="Take off height, relative altitude [m]."),
        ],
    ),
    Entry(
        name="Land",
        kind="action",
        description="Land at the current position.",
        params=[],
    ),
    Entry(
        name="Hold",
        kind="action",
        description="Hold/loiter at current position, cancelling movement.",
        params=[],
    ),
    Entry(
        name="Wait",
        kind="action",
        description="Hold position for a fixed duration.",
        params=[
            Param("duration", "float", required=True,
                  description="Seconds to wait (> 0)."),
        ],
    ),
    Entry(
        name="ReturnToHome",
        kind="action",
        description="Return to the launch position.",
        params=[],
    ),
    Entry(
        name="SetGlobalPosition",
        kind="action",
        description="Transit to a global position.",
        params=[
            Param("location", "ref", required=True, ref_kind="Location"),
            Param("max_velocity", "ref", required=False, ref_kind="Velocity"),
        ],
    ),
    Entry(
        name="Patrol",
        kind="action",
        description=(
            "Fly through waypoints generated from an area + slicing algorithm."
        ),
        params=[
            Param("waypoints", "ref", required=True, ref_kind="Waypoints"),
            Param("hover_time", "float", required=False,
                  description="Seconds to hover after each move (default 1.0)."),
            Param("max_velocity", "ref", required=False, ref_kind="Velocity"),
        ],
    ),
    Entry(
        name="Track",
        kind="action",
        description="Follow a detected object using vision-based control.",
        params=[
            Param("target", "ref", required=True, ref_kind="Detection",
                  description="Detection filter declared in Data:."),
            Param("leash_distance", "float", required=False,
                  description="Leash distance toward target [m] (default 10)."),
            Param("target_lost_duration", "float", required=False,
                  description="Seconds without detection before exiting "
                              "(default 10)."),
            Param("follow_speed", "float", required=False,
                  description="Max planar speed m/s (default 1.0)."),
        ],
    ),
]


# -----------------------------------------------------------------------------
# Events (steeleagle_sdk.dsl.types.events.singulars)
# -----------------------------------------------------------------------------
EVENTS: list[Entry] = [
    Entry(
        name="TimeReached",
        kind="event",
        description="Fires after a duration has elapsed.",
        params=[
            Param("duration", "float", required=True,
                  description="Seconds before firing."),
        ],
    ),
    Entry(
        name="BatteryReached",
        kind="event",
        description="Fires when battery percentage <= threshold.",
        params=[
            Param("threshold", "int", required=True,
                  description="Battery percentage 0-100."),
        ],
    ),
    Entry(
        name="DetectionFound",
        kind="event",
        description="Fires when a detection matches the target filter.",
        params=[
            Param("target", "ref", required=True, ref_kind="Detection",
                  description="Detection filter declared in Data:."),
        ],
    ),
]


RESERVED_EVENT_NAMES = {"done"}
STANZAS = ("Data", "Actions", "Events", "Mission")


def all_entries() -> list[Entry]:
    return DATATYPES + ACTIONS + EVENTS


def find(name: str, kind: str | None = None) -> Entry | None:
    for e in all_entries():
        if e.name == name and (kind is None or e.kind == kind):
            return e
    return None


def actions() -> list[Entry]:
    return ACTIONS


def events() -> list[Entry]:
    return EVENTS


def datatypes() -> list[Entry]:
    return DATATYPES
