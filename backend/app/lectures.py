"""Cairo University lecture timetable (OAAS Phase 6 use case).

A small Faculty of Computers & Artificial Intelligence demo: assign each
**section** to one **day × period × room**, with the instructor fixed on the
section. Hard rules prevent double-booking a room or an instructor and keep
enrollment inside room capacity. The goal prefers morning periods.

Sized so CP-SAT / HiGHS prove an optimum quickly: four sections, two days,
two periods, two rooms. Every section can sit in a morning slot, so the
proven objective is 0 (no afternoon assignments).
"""

from __future__ import annotations

from typing import Any

CAIRO_UNIVERSITY_LECTURES = "cairo_university_lectures"

_INDEX = ["section", "day", "period", "room"]
_ASSIGN = {"var": "assign", "index": ["s", "d", "p", "r"]}


def _sum(body: dict[str, Any], over: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sum": body, "over": over}


def build_ir() -> dict[str, Any]:
    return {
        "version": 1,
        "sets": ["section", "instructor", "day", "period", "room"],
        "relationships": ["taught_by"],
        "parameters": {"late": {"index": ["period"]}},
        "variables": {
            "assign": {"index": _INDEX, "domain": "binary"},
        },
        "constraints": [
            {
                "id": "c_once",
                "note": "each section meets exactly once in the week",
                "forall": [{"index": "s", "set": "section"}],
                "left": _sum(
                    _ASSIGN,
                    [
                        {"index": "d", "set": "day"},
                        {"index": "p", "set": "period"},
                        {"index": "r", "set": "room"},
                    ],
                ),
                "relation": "=",
                "right": {"const": 1},
                "severity": "hard",
            },
            {
                "id": "c_room",
                "note": "a room holds at most one section in a slot",
                "forall": [
                    {"index": "d", "set": "day"},
                    {"index": "p", "set": "period"},
                    {"index": "r", "set": "room"},
                ],
                "left": _sum(_ASSIGN, [{"index": "s", "set": "section"}]),
                "relation": "<=",
                "right": {"const": 1},
                "severity": "hard",
            },
            {
                "id": "c_instructor",
                "note": "an instructor teaches at most one section in a slot",
                "forall": [
                    {"index": "i", "set": "instructor"},
                    {"index": "d", "set": "day"},
                    {"index": "p", "set": "period"},
                ],
                "left": _sum(
                    _ASSIGN,
                    [
                        {
                            "index": "s",
                            "set": "section",
                            "via": {"rel": "taught_by", "to": "i"},
                        },
                        {"index": "r", "set": "room"},
                    ],
                ),
                "relation": "<=",
                "right": {"const": 1},
                "severity": "hard",
            },
            {
                "id": "c_capacity",
                "note": "enrollment fits the room",
                "forall": [
                    {"index": "s", "set": "section"},
                    {"index": "d", "set": "day"},
                    {"index": "p", "set": "period"},
                    {"index": "r", "set": "room"},
                ],
                "left": {
                    "mul": [
                        {"attr": {"of": "s", "name": "enrollment"}},
                        _ASSIGN,
                    ]
                },
                "relation": "<=",
                "right": {"attr": {"of": "r", "name": "capacity"}},
                "severity": "hard",
            },
        ],
        "objective": {
            "sense": "minimize",
            "terms": [
                {
                    "id": "o_morning",
                    "weight": 1,
                    "expression": _sum(
                        {
                            "mul": [
                                {"par": "late", "index": ["p"]},
                                _ASSIGN,
                            ]
                        },
                        [
                            {"index": "s", "set": "section"},
                            {"index": "d", "set": "day"},
                            {"index": "p", "set": "period"},
                            {"index": "r", "set": "room"},
                        ],
                    ),
                }
            ],
        },
    }


def build_seed() -> dict[str, Any]:
    """FCAI-sized toy: Giza campus labels, Arabic-friendly person names."""
    return {
        "note": (
            "Cairo University — Faculty of Computers & Artificial Intelligence "
            "(demo). Four weekly sections; instructors are fixed on each section."
        ),
        "entity_types": [
            {
                "name": "section",
                "role": "task",
                "colour": "#0f766e",
                "attributes": [
                    {
                        "name": "enrollment",
                        "data_type": "integer",
                        "unit": "students",
                        "required": True,
                    },
                    {"name": "course_code", "data_type": "text", "required": True},
                ],
            },
            {
                "name": "instructor",
                "role": "agent",
                "colour": "#2563eb",
                "attributes": [
                    {"name": "full_name", "data_type": "text", "required": True},
                ],
            },
            {
                "name": "day",
                "role": "time",
                "colour": "#0d9488",
                "attributes": [],
            },
            {
                "name": "period",
                "role": "time",
                "colour": "#d97706",
                "attributes": [
                    {"name": "starts_at", "data_type": "time", "required": True},
                    {"name": "ends_at", "data_type": "time", "required": True},
                ],
            },
            {
                "name": "room",
                "role": "resource",
                "colour": "#7c3aed",
                "attributes": [
                    {
                        "name": "capacity",
                        "data_type": "integer",
                        "unit": "seats",
                        "required": True,
                    },
                ],
            },
        ],
        "relationship_types": [
            {
                "name": "taught_by",
                "from": "section",
                "to": "instructor",
                "cardinality": "many_to_one",
                "is_hierarchy": False,
                "colour": "#16a34a",
            },
        ],
        "parameters": [
            {"name": "late", "index": ["period"], "default_value": 0, "unit": ""},
        ],
        "entities": [
            {
                "type": "instructor",
                "key": "nour",
                "label": "Dr Nour Hassan",
                "sort_order": 0,
                "attrs": {"full_name": "Nour Hassan"},
            },
            {
                "type": "instructor",
                "key": "karim",
                "label": "Dr Karim Farid",
                "sort_order": 1,
                "attrs": {"full_name": "Karim Farid"},
            },
            {
                "type": "day",
                "key": "sun",
                "label": "Sunday",
                "sort_order": 0,
                "attrs": {},
            },
            {
                "type": "day",
                "key": "mon",
                "label": "Monday",
                "sort_order": 1,
                "attrs": {},
            },
            {
                "type": "period",
                "key": "morning",
                "label": "Morning (09:00–11:00)",
                "sort_order": 0,
                "attrs": {"starts_at": "09:00", "ends_at": "11:00"},
            },
            {
                "type": "period",
                "key": "afternoon",
                "label": "Afternoon (13:00–15:00)",
                "sort_order": 1,
                "attrs": {"starts_at": "13:00", "ends_at": "15:00"},
            },
            {
                "type": "room",
                "key": "hall_a",
                "label": "Hall A (Main)",
                "sort_order": 0,
                "attrs": {"capacity": 80},
            },
            {
                "type": "room",
                "key": "room_b",
                "label": "Room B",
                "sort_order": 1,
                "attrs": {"capacity": 40},
            },
            {
                "type": "section",
                "key": "cs101_a",
                "label": "CS101 Group A",
                "sort_order": 0,
                "attrs": {"enrollment": 70, "course_code": "CS101"},
            },
            {
                "type": "section",
                "key": "cs101_b",
                "label": "CS101 Group B",
                "sort_order": 1,
                "attrs": {"enrollment": 35, "course_code": "CS101"},
            },
            {
                "type": "section",
                "key": "math201_a",
                "label": "MATH201 Group A",
                "sort_order": 2,
                "attrs": {"enrollment": 30, "course_code": "MATH201"},
            },
            {
                "type": "section",
                "key": "phys101_a",
                "label": "PHYS101 Group A",
                "sort_order": 3,
                "attrs": {"enrollment": 25, "course_code": "PHYS101"},
            },
        ],
        "relationships": [
            {"type": "taught_by", "from": ["section", "cs101_a"], "to": ["instructor", "nour"]},
            {"type": "taught_by", "from": ["section", "math201_a"], "to": ["instructor", "nour"]},
            {"type": "taught_by", "from": ["section", "cs101_b"], "to": ["instructor", "karim"]},
            {"type": "taught_by", "from": ["section", "phys101_a"], "to": ["instructor", "karim"]},
        ],
        "parameter_values": [
            {"parameter": "late", "entities": [["period", "morning"]], "value": 0},
            {"parameter": "late", "entities": [["period", "afternoon"]], "value": 1},
        ],
    }
