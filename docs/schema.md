# CSV schema

Five CSV tables are the single source of truth for every dashboard. They
live in `library/data/` (see the README for what `library/` stands in
for). The rules below are enforced in code by `src/team_dashboard/schema.py`
and `src/team_dashboard/validation.py` — this file documents them, it does
not define them a second time.

All dates are `YYYY-MM-DD`. All tables are UTF-8 CSV with a header row.

## tasks.csv

| Column | Type | Required | Notes |
|---|---|---|---|
| task_id | string | yes | unique key; free text, e.g. `T-AUR-0001` |
| team | enum | yes | must be a registered team name |
| owner | string | yes | must be a member of `team` |
| title | string | yes | |
| status | enum | yes | `Not Started`, `In Progress`, `Blocked`, `Done` |
| planned_date | date | yes | the date the task was due |
| done_date | date | no | set once `status = Done` (not enforced as required — a task can be marked Done before the date is backfilled, which is itself a data-quality signal, not something to silently reject) |
| created_date | date | yes | |

## weekly_updates.csv

| Column | Type | Required | Notes |
|---|---|---|---|
| update_id | string | yes | unique key |
| team | enum | yes | |
| member | string | yes | must belong to `team` |
| week_ending | date | yes | the Sunday (or chosen week-end day) the update covers |
| summary | string | yes | free text |
| hours_logged | number >= 0 | yes | |

## blockers.csv

| Column | Type | Required | Notes |
|---|---|---|---|
| blocker_id | string | yes | unique key |
| team | enum | yes | |
| task_id | string | yes | must exist in `tasks.csv` |
| owner | string | yes | must belong to `team` |
| description | string | yes | |
| raised_date | date | yes | |
| status | enum | yes | `Open`, `Resolved` |
| resolved_date | date | no | |

## achievements.csv

| Column | Type | Required | Notes |
|---|---|---|---|
| achievement_id | string | yes | unique key |
| team | enum | yes | |
| member | string | yes | must belong to `team` |
| week_ending | date | yes | |
| description | string | yes | |

## kpi_targets.csv

| Column | Type | Required | Notes |
|---|---|---|---|
| team | enum | yes | |
| week_ending | date | yes | unique key is (team, week_ending) |
| planned_tasks | integer >= 0 | yes | the team's own weekly plan target, set independently of what `tasks.csv` ends up recording |
| target_done | integer >= 0 | yes | |

## Validation order (what `sync.py` checks, in order, per row)

1. required fields present
2. dates parse as `YYYY-MM-DD`
3. enum fields hold an allowed value
4. `team` is a registered team
5. `owner`/`member` belongs to that team
6. numeric fields (`hours_logged`, `planned_tasks`, `target_done`) are non-negative numbers
7. `blockers.task_id` references a task that exists (tasks in the same
   sync batch count, so a task and its blocker can be submitted together)
8. the row's key isn't a duplicate of one already on disk or earlier in
   the same batch

A row fails on the *first* check it fails and is written to the
exceptions report with that category — it is never partially applied.
Every other row in the batch is still evaluated independently.
