"""Single source of truth for the five CSV tables.

Used by the generator, the member input workbook, the sync step, and the
dashboard refresh, so all four agree on column order, required fields,
enum values, date fields, and duplicate keys. Full column docs live in
`docs/schema.md` (kept in sync with this file by hand — this module is
what the code actually enforces).
"""

from __future__ import annotations

from dataclasses import dataclass, field

TASK_STATUSES = ["Not Started", "In Progress", "Blocked", "Done"]
BLOCKER_STATUSES = ["Open", "Resolved"]

DATE_FMT = "%Y-%m-%d"


@dataclass(frozen=True)
class TableSchema:
    name: str
    filename: str
    columns: list[str]
    required: list[str]
    date_fields: list[str] = field(default_factory=list)
    enum_fields: dict[str, list[str]] = field(default_factory=dict)
    key_fields: tuple[str, ...] = ()  # duplicate-detection key (row rejected if it repeats)
    team_field: str = "team"


TASKS = TableSchema(
    name="tasks",
    filename="tasks.csv",
    columns=["task_id", "team", "owner", "title", "status", "planned_date", "done_date", "created_date"],
    required=["task_id", "team", "owner", "title", "status", "planned_date", "created_date"],
    date_fields=["planned_date", "done_date", "created_date"],
    enum_fields={"status": TASK_STATUSES},
    key_fields=("task_id",),
)

WEEKLY_UPDATES = TableSchema(
    name="weekly_updates",
    filename="weekly_updates.csv",
    columns=["update_id", "team", "member", "week_ending", "summary", "hours_logged"],
    required=["update_id", "team", "member", "week_ending", "summary", "hours_logged"],
    date_fields=["week_ending"],
    key_fields=("update_id",),
)

BLOCKERS = TableSchema(
    name="blockers",
    filename="blockers.csv",
    columns=["blocker_id", "team", "task_id", "owner", "description", "raised_date", "status", "resolved_date"],
    required=["blocker_id", "team", "task_id", "owner", "description", "raised_date", "status"],
    date_fields=["raised_date", "resolved_date"],
    enum_fields={"status": BLOCKER_STATUSES},
    key_fields=("blocker_id",),
)

ACHIEVEMENTS = TableSchema(
    name="achievements",
    filename="achievements.csv",
    columns=["achievement_id", "team", "member", "week_ending", "description"],
    required=["achievement_id", "team", "member", "week_ending", "description"],
    date_fields=["week_ending"],
    key_fields=("achievement_id",),
)

KPI_TARGETS = TableSchema(
    name="kpi_targets",
    filename="kpi_targets.csv",
    columns=["team", "week_ending", "planned_tasks", "target_done"],
    required=["team", "week_ending", "planned_tasks", "target_done"],
    date_fields=["week_ending"],
    key_fields=("team", "week_ending"),
)

ALL_TABLES: list[TableSchema] = [TASKS, WEEKLY_UPDATES, BLOCKERS, ACHIEVEMENTS, KPI_TARGETS]

TABLES_BY_NAME: dict[str, TableSchema] = {t.name: t for t in ALL_TABLES}
