# Power Query (M) queries — paste-in instructions

**These `.pq` files are the query text only.** An `.xlsx` with a *working*
Power Query connection embeds a binary blob (the `DataMashup` part) that
only Excel itself can write — it cannot be authored by a script outside
Excel. So this folder ships the M code as plain text, parameterised by a
folder path, for you to paste into Excel's Power Query editor by hand. The
actually-working, no-Excel-required path in this repo is the Python
`refresh` command (see the main README) — that's what builds the
`.xlsx` dashboards checked into `library/dashboards/` when you run the
demo.

## One-time setup (per workbook)

1. Open Excel. **Data → Get Data → Launch Power Query Editor.**
2. **Manage Parameters → New Parameter.**
   - Name: `FolderPath`
   - Type: **Text**
   - Current Value: the full path to your `library/data/` folder, with a
     trailing slash, e.g. `C:\demo\library\data\` or
     `/opt/demo/library/data/`.
3. For each `.pq` file in this folder (`tasks.pq`, `weekly_updates.pq`,
   `blockers.pq`, `achievements.pq`, `kpi_targets.pq`):
   - **Home → New Source → Blank Query.**
   - Open the **Advanced Editor** on the new blank query.
   - Delete the placeholder text, paste in the file's contents, **Done**.
   - Rename the query to match the file (e.g. `tasks`).
4. **Close & Load To…** a table or the data model, per query.
5. To point the workbook at a different folder later (a different team's
   data, or after regenerating the demo data), edit the `FolderPath`
   parameter's value — every query re-reads from wherever it now points.

## What each query does

- `tasks.pq`, `weekly_updates.pq`, `achievements.pq`, `kpi_targets.pq` —
  read the matching CSV, promote headers, and set column types (dates as
  `date`, `hours_logged`/`planned_tasks`/`target_done` as numbers).
- `blockers.pq` — same, plus an `age_days` column computed from
  `raised_date` for rows still `Open` (using `DateTime.LocalNow()` as
  "today", since Power Query has no concept of the demo's fixed as-of
  date — this will drift day to day, unlike the Python `refresh` path,
  which takes an explicit `--as-of` and is what the checked-in dashboards
  were built with).

## Why this isn't a ready-to-open connected workbook

Building an `.xlsx` with these queries already wired up requires Excel
(or the Power Query SDK, which is not free/open-source tooling) to
serialize the `DataMashup` binary part — there is no supported way to
write that part from Python/openpyxl. Claiming otherwise, or shipping a
fake "connected" file, would be dishonest about what this repo can
verify. What you get instead: exact, working M code you paste in once,
plus a Python pipeline that builds the same-shaped dashboards without
Excel at all, which is the path this repo's tests actually exercise.
