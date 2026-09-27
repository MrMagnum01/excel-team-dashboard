"""Builds the deterministic synthetic dataset the whole demo runs on.

Everything is fabricated: fictional teams (`teams.py`), fictional tasks,
fictional blockers, fictional weekly updates and achievements. Given the
same seed and as-of date, this produces byte-identical CSVs every time.

While it generates the raw rows, it *independently* tallies the KPI truth
(planned/done/overdue counts, open-blocker counts, this-week achievements,
weekly done trend) into `known_totals.json`. That tally is written by
straightforward accumulation as rows are created — it does not call into
`kpis.py` — so the test suite's reconciliation check
(`tests/test_dashboard_kpis.py`) is a real cross-check between two
independently written code paths, not a tautology.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import csv_io, schema
from .teams import TEAMS

NUM_WEEKS = 8
DEFAULT_SEED = 7
DEFAULT_AS_OF = date(2026, 9, 21)

BLOCKER_REASONS = [
    "awaiting design sign-off",
    "waiting on vendor API access",
    "blocked by an upstream task",
    "waiting on stakeholder feedback",
    "infra dependency not ready",
    "waiting on a security review",
]

TASK_TITLE_VERBS = ["Build", "Design", "Migrate", "Document", "Refactor", "Test", "Ship", "Investigate"]
TASK_TITLE_NOUNS = [
    "the onboarding flow",
    "the weekly export job",
    "the reporting API",
    "the client-facing dashboard",
    "the notification service",
    "the data validation layer",
    "the access-control rules",
    "the release pipeline",
]

UPDATE_SUMMARIES = [
    "Made steady progress on assigned tasks, no new risks.",
    "Finished the planned items early, picked up a stretch task.",
    "Slower week due to a dependency delay; flagged as a blocker.",
    "Paired with a teammate to unblock a shared task.",
    "Focused on cleanup and documentation this week.",
]

ACHIEVEMENT_DESCRIPTIONS = [
    "Shipped the v2 onboarding flow ahead of schedule.",
    "Closed out the quarterly audit checklist.",
    "Cut pipeline latency by roughly a third.",
    "Completed the security training rollout for the team.",
    "Delivered the client demo a week early.",
    "Resolved the longest-standing open blocker.",
]


def _week_windows(as_of: date, num_weeks: int) -> list[tuple[date, date]]:
    """Return `num_weeks` (start, end) windows, 7 days each, ending at as_of."""
    endings = [as_of - timedelta(days=7 * (num_weeks - 1 - i)) for i in range(num_weeks)]
    windows = []
    for end in endings:
        start = end - timedelta(days=6)
        windows.append((start, end))
    return windows


@dataclass
class TeamTruth:
    planned_total: int = 0
    done_total: int = 0
    overdue_total: int = 0
    open_blockers_total: int = 0
    open_blockers_by_owner: dict[str, int] = field(default_factory=dict)
    achievements_this_week: int = 0
    weekly_done_trend: dict[str, int] = field(default_factory=dict)


def generate(out_dir: Path, seed: int = DEFAULT_SEED, as_of: date = DEFAULT_AS_OF) -> dict:
    rng = random.Random(seed)
    windows = _week_windows(as_of, NUM_WEEKS)
    week_endings = [w[1] for w in windows]

    tasks: list[dict] = []
    blockers: list[dict] = []
    weekly_updates: list[dict] = []
    achievements: list[dict] = []
    kpi_targets: list[dict] = []

    truth: dict[str, TeamTruth] = {team: TeamTruth() for team in TEAMS}
    for t in truth.values():
        t.weekly_done_trend = {w.isoformat(): 0 for w in week_endings}

    task_seq = 1
    blocker_seq = 1
    update_seq = 1
    achievement_seq = 1

    for team, members in TEAMS.items():
        code = "".join(w[0] for w in team.split())[:3].upper()
        base_weekly_target = rng.randint(4, 6)

        for week_idx, (week_start, week_end) in enumerate(windows):
            weeks_ago = (len(windows) - 1) - week_idx
            num_tasks = rng.randint(3, 6)

            # --- kpi_targets.csv: a goal set independently of what actually happens
            planned_target = max(1, base_weekly_target + rng.choice([-1, 0, 0, 1]))
            target_done = max(1, round(planned_target * 0.8))
            kpi_targets.append(
                {
                    "team": team,
                    "week_ending": week_end.isoformat(),
                    "planned_tasks": planned_target,
                    "target_done": target_done,
                }
            )

            for _ in range(num_tasks):
                owner = rng.choice(members)
                planned_date = week_start + timedelta(days=rng.randint(0, 6))
                created_date = planned_date - timedelta(days=rng.randint(1, 5))

                if weeks_ago >= 3:
                    status = rng.choices(
                        ["Done", "Blocked", "In Progress"], weights=[80, 10, 10]
                    )[0]
                elif weeks_ago >= 1:
                    status = rng.choices(
                        ["Done", "Blocked", "In Progress", "Not Started"],
                        weights=[55, 20, 15, 10],
                    )[0]
                else:
                    status = rng.choices(
                        ["Done", "Blocked", "In Progress", "Not Started"],
                        weights=[20, 20, 40, 20],
                    )[0]

                done_date = ""
                if status == "Done":
                    dd = planned_date + timedelta(days=rng.randint(0, 4))
                    if dd > as_of:
                        dd = as_of
                    done_date = dd.isoformat()

                task_id = f"T-{code}-{task_seq:04d}"
                task_seq += 1
                title = f"{rng.choice(TASK_TITLE_VERBS)} {rng.choice(TASK_TITLE_NOUNS)}"

                tasks.append(
                    {
                        "task_id": task_id,
                        "team": team,
                        "owner": owner,
                        "title": title,
                        "status": status,
                        "planned_date": planned_date.isoformat(),
                        "done_date": done_date,
                        "created_date": created_date.isoformat(),
                    }
                )

                tt = truth[team]
                tt.planned_total += 1
                if status == "Done":
                    tt.done_total += 1
                    # Bucket by the week the task was actually *finished*
                    # (done_date), not the week it was planned in -- a task
                    # planned near a week boundary can finish the week
                    # after. This must match kpis.compute_kpis exactly.
                    dd = date.fromisoformat(done_date)
                    for w_start, w_end in windows:
                        if w_start <= dd <= w_end:
                            tt.weekly_done_trend[w_end.isoformat()] += 1
                            break
                if status != "Done" and planned_date < as_of:
                    tt.overdue_total += 1

                # --- blockers.csv: only tasks that were (or are) blocked get one
                blocker_row = None
                if status == "Blocked":
                    raised_date = planned_date + timedelta(days=rng.randint(0, 3))
                    if raised_date > as_of:
                        raised_date = as_of
                    blocker_row = {
                        "blocker_id": f"B-{blocker_seq:04d}",
                        "team": team,
                        "task_id": task_id,
                        "owner": owner,
                        "description": f"Blocked: {rng.choice(BLOCKER_REASONS)}.",
                        "raised_date": raised_date.isoformat(),
                        "status": "Open",
                        "resolved_date": "",
                    }
                    tt.open_blockers_total += 1
                    tt.open_blockers_by_owner[owner] = tt.open_blockers_by_owner.get(owner, 0) + 1
                elif status in ("Done", "In Progress") and rng.random() < 0.2:
                    raised_date = planned_date + timedelta(days=rng.randint(0, 2))
                    resolved_date = raised_date + timedelta(days=rng.randint(1, 5))
                    if resolved_date > as_of:
                        resolved_date = as_of
                    blocker_row = {
                        "blocker_id": f"B-{blocker_seq:04d}",
                        "team": team,
                        "task_id": task_id,
                        "owner": owner,
                        "description": f"Blocked: {rng.choice(BLOCKER_REASONS)}.",
                        "raised_date": raised_date.isoformat(),
                        "status": "Resolved",
                        "resolved_date": resolved_date.isoformat(),
                    }

                if blocker_row is not None:
                    blockers.append(blocker_row)
                    blocker_seq += 1

            # --- weekly_updates.csv: every member files one update per week
            for member in members:
                weekly_updates.append(
                    {
                        "update_id": f"U-{update_seq:04d}",
                        "team": team,
                        "member": member,
                        "week_ending": week_end.isoformat(),
                        "summary": rng.choice(UPDATE_SUMMARIES),
                        "hours_logged": round(rng.uniform(20.0, 42.0), 1),
                    }
                )
                update_seq += 1

            # --- achievements.csv: not every team has one every week
            if rng.random() < 0.45:
                for _ in range(rng.randint(1, 2)):
                    member = rng.choice(members)
                    achievements.append(
                        {
                            "achievement_id": f"A-{achievement_seq:04d}",
                            "team": team,
                            "member": member,
                            "week_ending": week_end.isoformat(),
                            "description": rng.choice(ACHIEVEMENT_DESCRIPTIONS),
                        }
                    )
                    achievement_seq += 1
                    if week_end == as_of:
                        truth[team].achievements_this_week += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_io.write_rows(out_dir / schema.TASKS.filename, schema.TASKS, tasks)
    csv_io.write_rows(out_dir / schema.WEEKLY_UPDATES.filename, schema.WEEKLY_UPDATES, weekly_updates)
    csv_io.write_rows(out_dir / schema.BLOCKERS.filename, schema.BLOCKERS, blockers)
    csv_io.write_rows(out_dir / schema.ACHIEVEMENTS.filename, schema.ACHIEVEMENTS, achievements)
    csv_io.write_rows(out_dir / schema.KPI_TARGETS.filename, schema.KPI_TARGETS, kpi_targets)

    overall = TeamTruth()
    overall.weekly_done_trend = {w.isoformat(): 0 for w in week_endings}
    for tt in truth.values():
        overall.planned_total += tt.planned_total
        overall.done_total += tt.done_total
        overall.overdue_total += tt.overdue_total
        overall.open_blockers_total += tt.open_blockers_total
        overall.achievements_this_week += tt.achievements_this_week
        for owner, n in tt.open_blockers_by_owner.items():
            overall.open_blockers_by_owner[owner] = overall.open_blockers_by_owner.get(owner, 0) + n
        for wk, n in tt.weekly_done_trend.items():
            overall.weekly_done_trend[wk] += n

    known_totals = {
        "seed": seed,
        "as_of": as_of.isoformat(),
        "week_endings": [w.isoformat() for w in week_endings],
        "teams": {team: vars(tt) for team, tt in truth.items()},
        "overall": vars(overall),
    }
    (out_dir / "known_totals.json").write_text(json.dumps(known_totals, indent=2, sort_keys=True) + "\n")
    return known_totals
