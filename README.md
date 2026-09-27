# excel-team-dashboard

A synthetic team-progress dashboard: five CSV tables as the source of
truth, an Excel input workbook with dropdown data validation for members
to submit new entries, a `sync` step that validates and appends those
entries (rejecting anything bad into a categorised exceptions report), and
a master + per-team Excel dashboard with KPIs and a native chart, all
built by a Python "refresh" step.

**Everything in this repo is synthetic.** Three fictional teams (Team
Aurora, Team Birch, Team Cedar), fictional members, fictional tasks,
blockers, updates and achievements, generated with a fixed random seed.
No code, data, or team structure here is copied from any client or
employer project.

## What it does

1. `generate` — builds a deterministic dataset of ~110 synthetic tasks,
   ~96 weekly updates, ~19 blockers, ~18 achievements and 24 weekly KPI
   targets across the 3 teams and 8 weeks, and writes it to five CSVs (see
   `docs/schema.md`). It also writes `known_totals.json`: the true KPI
   figures, tallied independently as the data is generated, used to check
   the dashboards against ground truth (see Testing below).
2. `input` — builds a blank member input workbook (`.xlsx`, via
   `openpyxl`) with dropdown data validation: team, status, and
   member/owner columns are dropdowns sourced from a hidden lookup sheet
   or an inline list, date columns are validated as real dates.
3. `sample-inbox` — builds one filled-in-looking input workbook for the
   demo: a mix of valid rows and one row from every bad-input class `sync`
   checks for, so the demo run actually shows rejections happening.
4. `sync` — reads every `.xlsx` dropped into `library/inbox/`, resolves
   each sheet's columns by its header row, not by position — a
   reordered-but-complete header still reads correctly, while a
   duplicated, missing, or extra header is rejected as one exception for
   the whole sheet rather than misread — validates every row (required
   fields, dates, enums, team/member membership, finite non-negative
   numbers, Done/Resolved rows carry their completion date,
   blocker-references-a-real-task, no duplicates), appends the valid rows
   to the CSVs, and writes every rejected row — including an
   unrecognised sheet or an unreadable workbook — to
   `library/exceptions_report.csv` with a category and detail. Nothing is
   silently dropped, and the batch commits as an all-or-nothing unit
   across both its staging and commit phases: every real file this batch
   changes is backed up before its replacement is swapped in, and a
   failure at any point restores every already-swapped file from its
   backup before the error is raised — a failure partway through, staging
   or commit, leaves every CSV, the exceptions report, and the inbox
   exactly as they were, so a retry starts clean instead of
   double-counting or wrongly rejecting a duplicate (see "Limits" for the
   one residual case this doesn't cover). A `.sync.lock` file in
   `library/data/` enforces a local single-writer restriction for the
   duration of one `sync` call. Processed workbooks are moved to
   `library/inbox/processed/` so a re-run can't double-apply them.
5. `refresh` — builds `library/dashboards/master-dashboard.xlsx` (all
   3 teams) and one distributed copy per team
   (`team-aurora-dashboard.xlsx`, etc.), all computed from the same five
   CSVs. It refuses to run — rather than silently producing a
   zero-activity dashboard — if a required CSV is missing or fails the
   same schema validation `sync` uses (see "KPI definitions" below). Each
   dashboard has: a KPI table (done vs planned, done %, overdue,
   open blockers, achievements this week), an Overdue Tasks sheet, an
   Open Blockers sheet (sorted by age), an Achievements This Week sheet,
   and a native `openpyxl` line chart of tasks done per week. Every cell
   is written as a literal value, including text that looks like a
   formula (`=...`, `+...`) — source titles/descriptions are untrusted
   input and are never allowed to become an executable cell.

## `library/` stands in for a SharePoint document library

**There is no SharePoint tenant here.** `library/` is a plain local folder
that stands in for where this would live in a real deployment: members'
filled-in workbooks would be dropped into a SharePoint document library,
and the dashboards would be published there too. This repo has no
SharePoint account to test against, so `library/` (`data/`, `inbox/`,
`dashboards/`) is a local folder doing the same job for the demo. Nothing
here calls the SharePoint or Microsoft Graph API. `library/` is generated
by `run_demo.sh` and is git-ignored, same as `data/`/`output/` in the
other demos in this account.

## Power Query: shipped as M code, not as a working connection

**This demo does not ship or test a connected Power Query workbook.** A
live Power Query connection is stored in a binary part (`DataMashup`)
that only Excel itself writes when you build or refresh a query in its
UI; `openpyxl`, the library used here, cannot write that part. Claiming a
script-generated "connected" workbook would be false for what's built
here.

So this repo ships one thing that's actually working and tested, and one
that's exact but **unverified in Excel**:

- **`powerquery/*.pq`** — the M query text for each of the five tables,
  parameterised by a `FolderPath` parameter, with exact paste-in
  instructions in `powerquery/README.md`. This text has not been pasted
  into or run inside Excel in this environment (no copy of Excel exists
  here to do that with) — it is **proposed and unverified**, not a
  guaranteed working connection, until someone runs the paste-in steps
  and confirms it.
- **The Python `refresh` command** — the actually-working, actually-tested
  path with no Excel required, exercised by every test in this repo and by
  `run_demo.sh`. It is what built the dashboards you'd find in
  `library/dashboards/` after running the demo.

If a client needs a genuinely live, self-refreshing Excel workbook wired
directly to a SharePoint library via Power Query, that's an Excel-side
setup task (or a Power Automate flow calling the Python refresh) — stated
here plainly as **proposed**, not built, because it needs a real SharePoint
tenant and a copy of Excel to verify, neither of which exists in this
environment.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## One-command run

```bash
./run_demo.sh
```

This generates the synthetic data, builds a blank input workbook template,
builds one filled-in sample submission (with deliberately bad rows), syncs
it, and refreshes the dashboards — all into `library/`, which is
git-ignored (generated, not source).

## CLI, step by step

```bash
export PYTHONPATH=src

python -m team_dashboard generate --out library/data --seed 7 --as-of 2026-09-21
python -m team_dashboard input --out library/input-workbook-template.xlsx
python -m team_dashboard sample-inbox --out library/inbox/priya-submission.xlsx --data library/data --as-of 2026-09-21
python -m team_dashboard sync --inbox library/inbox --data library/data --exceptions library/exceptions_report.csv
python -m team_dashboard refresh --data library/data --out library/dashboards --as-of 2026-09-21
```

`--as-of` is the fixed "today" the dashboard is built against — KPIs like
"overdue" and "this week's achievements" are date-relative, and using a
fixed date (rather than the wall clock) is what keeps the whole pipeline
deterministic and testable. A real deployment would pass today's date, or
schedule `refresh` to run daily.

## Tests

```bash
source .venv/bin/activate
export PYTHONPATH=src
pytest tests -v
```

53 tests: generator determinism and schema-shape checks; a **known-total
reconciliation** suite (`test_dashboard_kpis.py`) that checks the
generator's independently-tallied truth (`known_totals.json`) against both
`kpis.compute_kpis`'s recomputation from the CSVs *and* the literal values
written into the built dashboard workbooks -- per team and overall; a
failure test for every bad-input class `sync` rejects, plus an end-to-end
test running `sync()` over a real filled-in workbook with one row from
each class and checking every row is accounted for (accepted or rejected,
never both, never silently dropped); subprocess smoke tests of the
full CLI pipeline; and `test_astra_probes.py` — an independent reviewer's
(Astra) probes for source-validation and sync-integrity edge cases, in two
rounds. First round (reordered/duplicate/missing/extra headers, an
unrecognised sheet, an unreadable workbook, infinite/non-integer numeric
fields, a Done/Resolved row missing its completion date, a future-created
row, a formula-looking title, missing source CSVs, and an injected
staging-phase write failure). Second round, from the re-review of the
first round's fixes (an injected failure during the *commit* phase's own
renames, not just staging; a malformed canonical-CSV header read as a
plausible empty table instead of refused; reordered achievements.csv
columns read by position instead of by name; a future `done_date`/
`resolved_date` still counted as already done/resolved as of an earlier
snapshot). Each asserts the fixed behaviour rather than the bug it
originally found.

This reconciliation suite caught a real bug during development: the
generator was originally bucketing "tasks done per week" by the week a
task was *planned* in, while the dashboard bucketed it by the week it was
*actually finished* (`done_date`) — the two disagreed whenever a task
finished the week after it was planned. Fixed by making the generator's
truth tally use the same done-date bucketing (`generator.py`, the
`weekly_done_trend` block) — this is exactly the kind of drift the
reconciliation check exists to catch.

## KPI definitions

`compute_kpis` reads three of the five tables — `tasks.csv`,
`blockers.csv`, and `achievements.csv`. `weekly_updates.csv` and
`kpi_targets.csv` are not consumed by any KPI figure or dashboard sheet;
`sync` still validates and appends rows to both.

- **Done vs planned**: `done_total` / `planned_total` per team, where
  `planned_total` is every task recorded for that team (as of the
  snapshot; see below) and `done_total` is the count that had actually
  completed by the as-of date (see "effective status" below).
- **Overdue**: tasks that had not completed by the as-of date and whose
  `planned_date` is before it.
- **Open blockers by age and owner**: every blocker still open as of the
  as-of date (see "effective status" below), with
  `age_days = as_of - raised_date`, listed per owner and sorted
  oldest-first in the dashboard's Open Blockers sheet.
- **Achievements this week**: `achievements.csv` rows whose `week_ending`
  equals the as-of date; the same validated rows feed both the KPI count
  and the dashboard's Achievements This Week detail sheet (one read, not
  two, so the sheet can't disagree with the count or misread a
  reordered-but-valid header — see "Sheet-level checks" in
  `docs/schema.md`).
- **Weekly trend**: tasks done per week over the 8-week window, as a
  native `openpyxl` line chart (no image, no external charting library —
  it's a real Excel chart object you can click into and re-source).
- **As-of snapshot policy (no time travel)**: a task or blocker whose
  `created_date`/`raised_date` is after the dashboard's `--as-of` date is
  excluded from that snapshot entirely — planned/done/overdue/open-blocker
  totals, not just the weekly trend chart. Without this, a row dated in
  the future relative to the snapshot could be counted into "current"
  totals while its own trend bucket (correctly) showed nothing, which is
  an inconsistent read of "as of" rather than a supported historical
  reconstruction from mutable current status.
- **Effective status uses the row's own recorded date, not its current
  (mutable) status label**: `status` describes the row *today*, but a
  `done_date`/`resolved_date` is an immutable fact about when completion
  actually happened. A `status = Done` task whose `done_date` is after
  `as_of`, or a `status = Resolved` blocker whose `resolved_date` is after
  `as_of`, had not completed yet as of that snapshot — it counts as still
  open/not-done for that snapshot instead (and, for a task, as overdue if
  its `planned_date` had also already passed). This reads the row's own
  date field directly; it is not a claimed reconstruction of what the
  row's status "must have been" at an earlier point in time from history
  that isn't recorded anywhere.
- **Refresh reads a validated snapshot, not just whatever's on disk**:
  `refresh` re-validates every row against the same schema `sync` uses
  before computing anything, and refuses to run (raising
  `SourceDataError`) if a required CSV is missing, has the wrong header,
  or any row fails — never silently substituting a zero-activity
  dashboard for absent, mis-headed, or corrupt source data. A
  header-only file with the correct columns is still a legitimate empty
  table.

KPI cells in the dashboard are **plain computed values**, not live Excel
formulas — they're written by the Python `refresh` step reading the CSVs,
not recalculated by Excel. A cell showing `27` is exactly what
`kpis.compute_kpis` returned at build time; re-running `refresh` after
`sync` picks up new data and rebuilds the values.

## Project layout

```
src/team_dashboard/
  teams.py           fictional team/member registry
  schema.py           column names, required fields, enums, date fields, per table
  csv_io.py            read/write/append CSV helpers (no pandas)
  generator.py         builds the deterministic dataset + known_totals.json
  validation.py         row-level validation used by sync (every bad-input class)
  input_workbook.py     builds the blank member input workbook (dropdowns)
  sample_inbox.py        builds one filled demo submission (good rows + every bad class)
  sync.py                validates inbox workbooks, appends, writes exceptions report
  kpis.py                 recomputes KPIs from the CSVs (independent of generator's truth)
  dashboard.py             builds master + per-team dashboard workbooks + native chart
  cli.py                    generate / input / sample-inbox / sync / refresh subcommands
docs/schema.md          full CSV column reference
powerquery/*.pq         M query text per table, paste-in instructions in powerquery/README.md
tests/                  pytest suite (see Tests above)
LICENSES.md             every open-source library used and its licence
```

## Limits (stated plainly)

- No real SharePoint integration — `library/` is a local stand-in, as
  described above. Wiring this to an actual SharePoint document library
  (via Power Automate, Graph API, or a synced OneDrive folder) is
  **proposed**, not built.
- No working Power-Query-connected `.xlsx` is shipped, for the reason
  above — the M code and paste-in instructions are shipped instead.
- KPI values in the dashboards are computed-and-written, not live Excel
  formulas; re-run `refresh` to pick up new data.
- The member-input dropdown for "owner"/"member" lists every member
  across all teams, not just the selected team's roster — Excel data
  validation lists can't easily filter by another cell's value without a
  named-range-per-team setup, which was left out to keep the workbook
  simple. `sync` still rejects a member/team mismatch (`unknown_member`).
- Duplicate detection is per sync run's inbox plus whatever is already on
  disk — it is not a separate append-only audit log of every submission
  ever made.
- 3 fictional teams / 4 members each / 8 weeks of history is the demo
  scale; nothing in the code hardcodes those numbers except the generator.
- `sync`'s single-writer lock (`library/data/.sync.lock`) is a local file
  that a hard-killed process (not an ordinary exception) can leave behind;
  a stale lock has to be removed by hand before the next run. This is
  the "local single-writer restriction" this demo relies on instead of
  real concurrent-write handling — there is no SharePoint tenant here to
  need that against.
- `sync`'s batch commit makes each `sync()` call all-or-nothing for any
  ordinary exception during staging or commit (backup-then-swap-then-
  cleanup rolls back every already-applied rename in the batch — see
  `sync.py`'s module docstring), but it is not a durable transaction log
  across a hard-killed process (not an ordinary exception) between two of
  those renames: that can leave a stray `*.backup-<batch-id>` file next to
  its real CSV, which must be restored over it by hand before the next
  `sync` run — the same class of by-hand-recoverable caveat as the stale
  `.sync.lock` file above, and an equally narrow window (a handful of fast
  local renames), not a claim that no window exists at all.

## Target Upwork job types

This repo demonstrates the skill set for: **"Excel dashboard"**, **"team
KPI tracker"**, and **"Excel data validation / automation"** jobs.

## Role

Built with AI-assisted coding, including an independent AI review pass
that found and required fixes for the source-validation and sync-integrity
gaps described above (see `tests/test_astra_probes.py`). All data
synthetic; no client work.
