"""Fictional team/member registry used throughout the demo.

All names invented for this repo. Any resemblance to a real team, company,
or person is coincidental.
"""

from __future__ import annotations

TEAMS: dict[str, list[str]] = {
    "Team Aurora": [
        "Priya Nandan",
        "Oskar Lindqvist",
        "Mei Fujimori",
        "Diego Salcedo",
    ],
    "Team Birch": [
        "Hana Vogt",
        "Tomas Kowalczyk",
        "Amara Osei",
        "Liu Wenjing",
    ],
    "Team Cedar": [
        "Sofia Bergman",
        "Kwame Asante",
        "Noor Haidari",
        "Ines Pardal",
    ],
}

TEAM_NAMES: list[str] = list(TEAMS.keys())

ALL_MEMBERS: list[str] = [m for members in TEAMS.values() for m in members]


def team_for_member(member: str) -> str | None:
    for team, members in TEAMS.items():
        if member == team:
            continue
        if member in members:
            return team
    return None
