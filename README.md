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
4. `sync` — reads every `.xlsx` dropped into `library/inbox/`, validates
   every row (required fields, dates, enums, team/member membership,
   non-negative numbers, blocker-references-a-real-task, no duplicates),
   appends the valid rows to the CSVs, and writes every rejected row to
   `library/exceptions_report.csv` with a category and detail — nothing is
   silently dropped. Processed workbooks are moved to
   `library/inbox/processed/` so a re-run can't double-apply them.
5. `refresh` — builds `library/dashboards/master-dashboard.xlsx` (all
   3 teams) and one distributed copy per team
   (`team-aurora-dashboard.xlsx`, etc.), all computed from the same five
   CSVs. Each has: a KPI table (done vs planned, done %, overdue,
   open blockers, achievements this week), an Overdue Tasks sheet, an
   Open Blockers sheet (sorted by age), an Achievements This Week sheet,
   and a native `openpyxl` line chart of tasks done per week.

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

**An `.xlsx` with a working Power Query connection cannot be authored
without Excel** — the connection is stored in a binary part
(`DataMashup`) that only Excel itself writes when you build or refresh a
query in its UI. No Python library, `openpyxl` included, can produce that
part. Claiming a script-generated "connected" workbook would be false.

So this repo ships the two things that are actually true and actually
verified:

- **`powerquery/*.pq`** — the M query text for each of the five tables,
  parameterised by a `FolderPath` parameter, with exact paste-in
  instructions in `powerquery/README.md`. You open Excel once, create the
  parameter, paste in each query, and you have a live Power-Query-backed
  workbook pointed at whatever folder you choose.
- **The Python `refresh` command** — the actually-working path with no
  Excel required, exercised by every test in this repo and by
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

31 tests: generator determinism and schema-shape checks; a **known-total
reconciliation** suite (`test_dashboard_kpis.py`) that checks the
generator's independently-tallied truth (`known_totals.json`) against both
`kpis.compute_kpis`'s recomputation from the CSVs *and* the literal values
written into the built dashboard workbooks -- per team and overall; a
failure test for every bad-input class `sync` rejects, plus an end-to-end
test running `sync()` over a real filled-in workbook with one row from
each class and checking every row is accounted for (accepted or rejected,
never both, never silently dropped); and subprocess smoke tests of the
full CLI pipeline.

This reconciliation suite caught a real bug during development: the
generator was originally bucketing "tasks done per week" by the week a
task was *planned* in, while the dashboard bucketed it by the week it was
*actually finished* (`done_date`) — the two disagreed whenever a task
finished the week after it was planned. Fixed by making the generator's
truth tally use the same done-date bucketing (`generator.py`, the
`weekly_done_trend` block) — this is exactly the kind of drift the
reconciliation check exists to catch.

## KPI definitions

- **Done vs planned**: `done_total` / `planned_total` per team, where
  `planned_total` is every task recorded for that team and `done_total` is
  the count with `status = Done`.
- **Overdue**: tasks with `status != Done` and `planned_date` before the
  as-of date.
- **Open blockers by age and owner**: every `blockers.csv` row with
  `status = Open`, with `age_days = as_of - raised_date`, listed per owner
  and sorted oldest-first in the dashboard's Open Blockers sheet.
- **Achievements this week**: `achievements.csv` rows whose `week_ending`
  equals the as-of date.
- **Weekly trend**: tasks done per week over the 8-week window, as a
  native `openpyxl` line chart (no image, no external charting library —
  it's a real Excel chart object you can click into and re-source).

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

## Target Upwork job types

This repo demonstrates the skill set for: **"Excel dashboard"**, **"team
KPI tracker"**, and **"Excel data validation / automation"** jobs.

## Role

Automation engineer — designed and directed the build (AI-assisted
coding). All data synthetic; no client work.
