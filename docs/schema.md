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
| done_date | date | conditional | required once `status = Done` — a Done task with no done_date fails validation (`inconsistent_status_date`) rather than passing silently |
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
| resolved_date | date | conditional | required once `status = Resolved` — same `inconsistent_status_date` check as tasks' `done_date` |

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
6. numeric fields (`hours_logged`, `planned_tasks`, `target_done`) are
   finite, non-negative numbers (`inf`/`nan` are rejected, not just
   negative values), and `planned_tasks`/`target_done` must be whole
   numbers
7. status/date consistency: a `tasks` row with `status = Done` must carry
   `done_date`; a `blockers` row with `status = Resolved` must carry
   `resolved_date`
8. `blockers.task_id` references a task that exists (tasks in the same
   sync batch count, so a task and its blocker can be submitted together)
9. the row's key isn't a duplicate of one already on disk or earlier in
   the same batch

A row fails on the *first* check it fails and is written to the
exceptions report with that category — it is never partially applied.
Every other row in the batch is still evaluated independently.

## Sheet-level checks, before any row is read

`sync.py` maps each sheet's columns by its **header row**, not by
position: a header row that isn't exactly the schema's columns (missing,
extra, or a duplicate column name) is rejected as one `invalid_schema`
exception for the whole sheet, rather than silently misreading values
into the wrong field (a reordered-but-complete header is fine — that's
the point of mapping by name). A sheet whose title isn't one of the five
expected data tabs, and isn't empty, is rejected as one
`unrecognised_sheet` exception rather than silently producing a
workbook with nothing accepted and nothing reported.

`refresh` (via `kpis.compute_kpis`) re-validates every row it reads from
`tasks.csv`/`blockers.csv`/`achievements.csv` against this same schema,
and refuses to run if a required CSV is missing or any row fails —
canonical CSVs are meant to only ever contain rows that already passed
`sync`, so this is a corruption/tamper check, not routine work.
