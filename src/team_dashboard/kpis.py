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
from .csv_io import SourceDataError
from .sync import sync_lock
from .teams import TEAMS
from .validation import validate_rows


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _load_required(data_dir: Path, table: schema.TableSchema, known_task_ids: set[str] | None = None) -> list[dict]:
    """Read `table`'s canonical CSV, refusing to proceed on a missing or
    invalid file rather than treating it as an empty/zero table.

    `refresh` is documented as reading a completed, validated snapshot (see
    README/docs/schema.md) -- these CSVs are meant to only ever contain
    rows that already passed `validate_rows` in `sync`, so re-validating
    them here is a corruption/tamper check, not routine work, and a clean
    canonical CSV always passes with zero exceptions.
    """
    path = data_dir / table.filename
    if not path.exists():
        raise SourceDataError(
            f"required source is missing: {path} -- refusing to build a dashboard against absent data "
            "(a missing file is not the same as zero real activity)"
        )
    rows = csv_io.read_rows(path, table)
    accepted, exceptions = validate_rows(table, rows, source=str(path), existing_keys=set(), known_task_ids=known_task_ids)
    if exceptions:
        detail = "; ".join(f"row {e.row_number} ({e.category}): {e.detail}" for e in exceptions[:5])
        more = f" (+{len(exceptions) - 5} more)" if len(exceptions) > 5 else ""
        raise SourceDataError(f"{path} failed schema validation on {len(exceptions)} row(s): {detail}{more}")
    return accepted


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
    achievements_this_week_rows: list[dict] = field(default_factory=list)
    weekly_done_trend: dict[str, int] = field(default_factory=dict)


def compute_kpis(data_dir: Path, as_of: date, num_weeks: int = 8, teams: list[str] | None = None) -> dict:
    """Return {"teams": {name: TeamKPIs}, "overall": TeamKPIs, "week_endings": [...]}."""
    team_names = teams if teams is not None else list(TEAMS.keys())

    # Read all three tables under the same lock `sync()` holds for its
    # entire batch commit (staging, commit, and archive) -- see
    # `sync.sync_lock`'s docstring. Without this, a refresh running
    # concurrently with a sync's multi-file commit could read some tables
    # from before the batch and others from after it: a snapshot that
    # never actually existed. With it, a refresh either sees the complete
    # state before this batch or the complete state after it, never a mix.
    with sync_lock(data_dir):
        tasks = _load_required(data_dir, schema.TASKS)
        known_task_ids = {row["task_id"] for row in tasks}
        blockers = _load_required(data_dir, schema.BLOCKERS, known_task_ids=known_task_ids)
        achievements = _load_required(data_dir, schema.ACHIEVEMENTS)

    windows = week_windows(as_of, num_weeks)
    week_endings = [w[1] for w in windows]

    result: dict[str, TeamKPIs] = {t: TeamKPIs() for t in team_names}
    for tk in result.values():
        tk.weekly_done_trend = {w.isoformat(): 0 for w in week_endings}

    for row in tasks:
        team = row["team"]
        if team not in result:
            continue
        # As-of snapshot policy: a row created after `as_of` did not exist
        # yet as of this snapshot, so it is excluded entirely rather than
        # counted into planned/done totals for a date it postdates -- see
        # "KPI definitions" in the README for why this isn't arbitrary
        # historical reconstruction from mutable current status.
        if _parse_date(row["created_date"]) > as_of:
            continue
        tk = result[team]
        planned_date = _parse_date(row["planned_date"])
        status = row["status"]
        done_date = _parse_date(row["done_date"]) if row.get("done_date") else None
        # A task's current `status` is mutable and describes *today*, not
        # necessarily the as-of snapshot date -- but its `done_date`, once
        # set, is an immutable fact about when it actually finished. A
        # `status=Done` row whose own `done_date` is still after `as_of`
        # had not finished yet as of this snapshot, so it must not count as
        # done for it (that would be counting a future event into a past
        # snapshot); this uses the row's own recorded date, not a claimed
        # reconstruction of what its status "must have been" back then.
        effective_done = status == "Done" and done_date is not None and done_date <= as_of
        tk.planned_total += 1
        if effective_done:
            tk.done_total += 1
            for start, end in windows:
                if start <= done_date <= end:
                    tk.weekly_done_trend[end.isoformat()] += 1
                    break
        elif planned_date < as_of:
            tk.overdue_total += 1
            tk.overdue_tasks.append(row)

    for row in blockers:
        team = row["team"]
        if team not in result:
            continue
        if _parse_date(row["raised_date"]) > as_of:
            continue  # not raised yet as of this snapshot -- see as-of policy above
        resolved_date = _parse_date(row["resolved_date"]) if row.get("resolved_date") else None
        # Same immutable-date-over-mutable-status principle as tasks above:
        # a `status=Resolved` blocker whose own `resolved_date` is still
        # after `as_of` had not been resolved yet as of this snapshot, so
        # it must still count as open for it.
        effective_open = row["status"] == "Open" or (resolved_date is not None and resolved_date > as_of)
        if not effective_open:
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
            result[team].achievements_this_week_rows.append(row)

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
        overall.achievements_this_week_rows.extend(tk.achievements_this_week_rows)
        for owner, n in tk.open_blockers_by_owner.items():
            overall.open_blockers_by_owner[owner] = overall.open_blockers_by_owner.get(owner, 0) + n
        for wk, n in tk.weekly_done_trend.items():
            overall.weekly_done_trend[wk] += n

    return {"teams": result, "overall": overall, "week_endings": week_endings}
