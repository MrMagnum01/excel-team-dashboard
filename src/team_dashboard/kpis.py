"""Computes dashboard KPIs from the CSV tables.

Deliberately written without importing `generator.py`: the generator
tracks its own "true" totals as it fabricates data (see
`generator.TeamTruth`), and this module recomputes the same figures purely
from the CSVs on disk, the way the real dashboard refresh does. The two
being independently written is what makes the reconciliation test in
`tests/test_dashboard_kpis.py` meaningful rather than circular.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import csv_io, schema
from .teams import TEAMS


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def week_windows(as_of: date, num_weeks: int) -> list[tuple[date, date]]:
    endings = [as_of - timedelta(days=7 * (num_weeks - 1 - i)) for i in range(num_weeks)]
    return [(end - timedelta(days=6), end) for end in endings]


@dataclass
class TeamKPIs:
    planned_total: int = 0
    done_total: int = 0
    overdue_total: int = 0
    overdue_tasks: list[dict] = field(default_factory=list)
    open_blockers_total: int = 0
    open_blockers_by_owner: dict[str, int] = field(default_factory=dict)
    open_blockers: list[dict] = field(default_factory=list)
    achievements_this_week: int = 0
    weekly_done_trend: dict[str, int] = field(default_factory=dict)


def compute_kpis(data_dir: Path, as_of: date, num_weeks: int = 8, teams: list[str] | None = None) -> dict:
    """Return {"teams": {name: TeamKPIs}, "overall": TeamKPIs, "week_endings": [...]}."""
    team_names = teams if teams is not None else list(TEAMS.keys())

    tasks = csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)
    blockers = csv_io.read_rows(data_dir / schema.BLOCKERS.filename, schema.BLOCKERS)
    achievements = csv_io.read_rows(data_dir / schema.ACHIEVEMENTS.filename, schema.ACHIEVEMENTS)

    windows = week_windows(as_of, num_weeks)
    week_endings = [w[1] for w in windows]

    result: dict[str, TeamKPIs] = {t: TeamKPIs() for t in team_names}
    for tk in result.values():
        tk.weekly_done_trend = {w.isoformat(): 0 for w in week_endings}

    for row in tasks:
        team = row["team"]
        if team not in result:
            continue
        tk = result[team]
        planned_date = _parse_date(row["planned_date"])
        status = row["status"]
        tk.planned_total += 1
        if status == "Done":
            tk.done_total += 1
            if row.get("done_date"):
                dd = _parse_date(row["done_date"])
                for start, end in windows:
                    if start <= dd <= end:
                        tk.weekly_done_trend[end.isoformat()] += 1
                        break
        if status != "Done" and planned_date < as_of:
            tk.overdue_total += 1
            tk.overdue_tasks.append(row)

    for row in blockers:
        team = row["team"]
        if team not in result or row["status"] != "Open":
            continue
        tk = result[team]
        tk.open_blockers_total += 1
        tk.open_blockers_by_owner[row["owner"]] = tk.open_blockers_by_owner.get(row["owner"], 0) + 1
        raised = _parse_date(row["raised_date"])
        tk.open_blockers.append({**row, "age_days": (as_of - raised).days})

    for row in achievements:
        team = row["team"]
        if team not in result:
            continue
        if row["week_ending"] == as_of.isoformat():
            result[team].achievements_this_week += 1

    overall = TeamKPIs()
    overall.weekly_done_trend = {w.isoformat(): 0 for w in week_endings}
    for tk in result.values():
        overall.planned_total += tk.planned_total
        overall.done_total += tk.done_total
        overall.overdue_total += tk.overdue_total
        overall.overdue_tasks.extend(tk.overdue_tasks)
        overall.open_blockers_total += tk.open_blockers_total
        overall.open_blockers.extend(tk.open_blockers)
        overall.achievements_this_week += tk.achievements_this_week
        for owner, n in tk.open_blockers_by_owner.items():
            overall.open_blockers_by_owner[owner] = overall.open_blockers_by_owner.get(owner, 0) + n
        for wk, n in tk.weekly_done_trend.items():
            overall.weekly_done_trend[wk] += n

    return {"teams": result, "overall": overall, "week_endings": week_endings}
