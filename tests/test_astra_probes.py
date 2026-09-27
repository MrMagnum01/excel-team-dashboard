"""Astra's independent-review probes (2026-09-27), wired into the suite.

Source: `~/vault/40-sessions/2026-09-27-astra-excel-team-dashboard-probes.py`
and the accompanying `-review.md` / `-probes.json`. Each test below
reproduces one of Astra's nine observations and asserts the *fixed*
behaviour the review asked for -- only paths/fixtures were adapted from
the original probe script (it used `TemporaryDirectory()`/hardcoded
dates; here it's `tmp_path` plus this suite's `data_dir`/`known_totals`
fixtures), the assertions themselves encode the review's required
outcome, not the pre-fix one.

Kept in this order to match the review's findings list.

The re-review's follow-up probes (2026-09-27, commit 10d2fdb held) are
wired in at the end of this file, in the same style: source
`~/vault/40-sessions/2026-09-27-astra-excel-team-dashboard-rereview-probes.py`
and `-rereview.md`/`-rereview-probes.json`.
"""

from __future__ import annotations

from datetime import date

import pytest
from openpyxl import Workbook, load_workbook

from team_dashboard import csv_io, schema
from team_dashboard.dashboard import build_dashboards
from team_dashboard.input_workbook import SHEET_TITLES
from team_dashboard.kpis import compute_kpis
from team_dashboard.csv_io import SourceDataError
from team_dashboard.sync import sync
from team_dashboard.validation import validate_rows

TEAM = "Team Aurora"
OWNER = "Priya Nandan"
AS_OF = date(2026, 9, 21)


def _task(**kw):
    row = dict(
        task_id="T1", team=TEAM, owner=OWNER, title="Synthetic",
        status="Not Started", planned_date="2026-09-20", done_date="", created_date="2026-09-01",
    )
    row.update(kw)
    return row


# --- Finding: numeric/status/date validation incomplete (Medium) ----------


def test_infinite_hours_rejected():
    """`hours_logged='inf'` used to be accepted (`float('inf')` parses and
    is neither negative nor NaN). Finite-ness is now checked explicitly."""
    row = dict(update_id="U1", team=TEAM, member=OWNER, week_ending=AS_OF.isoformat(), summary="Synthetic", hours_logged="inf")
    accepted, exceptions = validate_rows(schema.WEEKLY_UPDATES, [row], source="probe", existing_keys=set())
    assert len(accepted) == 0
    assert len(exceptions) == 1
    assert exceptions[0].category == "invalid_number"


def test_done_task_without_done_date_rejected():
    """A `status=Done` task with a blank `done_date` used to pass silently."""
    accepted, exceptions = validate_rows(schema.TASKS, [_task(status="Done")], source="probe", existing_keys=set())
    assert len(accepted) == 0
    assert len(exceptions) == 1
    assert exceptions[0].category == "inconsistent_status_date"


def test_resolved_blocker_without_resolved_date_rejected():
    """Same conditional-date requirement, on the blockers side."""
    row = dict(
        blocker_id="B1", team=TEAM, task_id="T1", owner=OWNER, description="x",
        raised_date="2026-09-10", status="Resolved", resolved_date="",
    )
    accepted, exceptions = validate_rows(schema.BLOCKERS, [row], source="probe", existing_keys=set(), known_task_ids={"T1"})
    assert len(accepted) == 0
    assert exceptions[0].category == "inconsistent_status_date"


def test_non_integer_kpi_target_rejected():
    """`planned_tasks`/`target_done` count tasks; a fractional value is
    nonsensical even though it's a non-negative number."""
    row = dict(team=TEAM, week_ending=AS_OF.isoformat(), planned_tasks="4.5", target_done="3")
    accepted, exceptions = validate_rows(schema.KPI_TARGETS, [row], source="probe", existing_keys=set())
    assert len(accepted) == 0
    assert exceptions[0].category == "invalid_number"


# --- Finding: missing CSV sources become a plausible zero dashboard (High) -


def test_missing_sources_refuse_refresh_instead_of_reporting_zero(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SourceDataError):
        build_dashboards(empty, tmp_path / "empty-out", AS_OF)


def test_missing_sources_refuse_kpi_computation(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SourceDataError):
        compute_kpis(empty, AS_OF)


# --- Finding: as-of label overstates KPI time semantics (Medium) ----------


def test_future_created_task_excluded_from_asof_snapshot(tmp_path):
    """A task created/planned/done after `as_of` did not exist yet as of
    this snapshot -- it must be excluded from planned/done entirely, not
    counted while its own weekly trend bucket (correctly) shows nothing."""
    data = tmp_path / "future"
    csv_io.write_rows(
        data / "tasks.csv", schema.TASKS,
        [_task(status="Done", done_date="2026-10-01", created_date="2026-10-01", planned_date="2026-10-02")],
    )
    csv_io.write_rows(data / "blockers.csv", schema.BLOCKERS, [])
    csv_io.write_rows(data / "achievements.csv", schema.ACHIEVEMENTS, [])
    k = compute_kpis(data, AS_OF)
    assert k["overall"].planned_total == 0
    assert k["overall"].done_total == 0
    assert sum(k["overall"].weekly_done_trend.values()) == 0


# --- Finding: input headers ignored / valid values silently reassigned (High)


def test_reordered_headers_are_still_read_correctly(tmp_path):
    inbox = tmp_path / "swapped-inbox"
    inbox.mkdir()
    data = tmp_path / "swapped-data"
    w = Workbook()
    s = w.active
    s.title = SHEET_TITLES["tasks"]
    cols = list(schema.TASKS.columns)
    i, j = cols.index("planned_date"), cols.index("created_date")
    cols[i], cols[j] = cols[j], cols[i]
    row = _task()
    s.append(cols)
    s.append([row[x] for x in cols])
    w.save(inbox / "swapped.xlsx")

    summary = sync(inbox, data, tmp_path / "swapped-exceptions.csv")
    got = csv_io.read_rows(data / "tasks.csv", schema.TASKS)

    assert summary["accepted"]["tasks"] == 1
    assert summary["exceptions"] == 0
    assert got[0]["planned_date"] == row["planned_date"] == "2026-09-20"
    assert got[0]["created_date"] == row["created_date"] == "2026-09-01"


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_malformed_header_rejected_not_misread(tmp_path, mutation):
    """Missing, extra, and duplicate headers must all be rejected as an
    exception rather than positionally misread (the review's explicit
    "test swapped, duplicate, missing and extra headers" ask)."""
    inbox = tmp_path / f"{mutation}-inbox"
    inbox.mkdir()
    data = tmp_path / f"{mutation}-data"
    cols = list(schema.TASKS.columns)
    if mutation == "missing":
        cols = [c for c in cols if c != "created_date"]
    elif mutation == "extra":
        cols = cols + ["unexpected_column"]
    elif mutation == "duplicate":
        cols = cols + ["task_id"]
    row = _task()
    w = Workbook()
    s = w.active
    s.title = SHEET_TITLES["tasks"]
    s.append(cols)
    s.append([row.get(c, "extra-value") for c in cols])
    w.save(inbox / "bad.xlsx")

    summary = sync(inbox, data, tmp_path / "exceptions.csv")
    assert summary["accepted"]["tasks"] == 0
    assert summary["exceptions"] == 1
    report = csv_io.read_rows(tmp_path / "exceptions.csv", schema.TableSchema(
        name="exceptions", filename="x", columns=["table", "source", "row_number", "category", "detail", "raw_row"], required=[]))
    assert report[0]["category"] == "invalid_schema"


# --- Finding: unknown sheets archived as successfully processed (High) ----


def test_unrecognised_sheet_produces_an_exception_not_silence(tmp_path):
    inbox = tmp_path / "unknown-inbox"
    inbox.mkdir()
    row = _task()
    w = Workbook()
    s = w.active
    s.title = "Task typo"
    s.append(schema.TASKS.columns)
    s.append([row[x] for x in schema.TASKS.columns])
    w.save(inbox / "unknown.xlsx")

    summary = sync(inbox, tmp_path / "unknown-data", tmp_path / "unknown-exceptions.csv")
    assert summary["exceptions"] == 1
    assert sum(summary["accepted"].values()) == 0
    # Still archived: the workbook *was* read successfully, it's the sheet
    # content that's unrecognised -- distinct from an unreadable file.
    assert len(list((inbox / "processed").glob("*.xlsx"))) == 1


# --- Finding: source text converted to executable workbook formulas (High) -


def test_formula_looking_title_is_stored_as_literal_text(tmp_path):
    data = tmp_path / "formula"
    csv_io.write_rows(data / "tasks.csv", schema.TASKS, [_task(title="=1+1")])
    csv_io.write_rows(data / "blockers.csv", schema.BLOCKERS, [])
    csv_io.write_rows(data / "achievements.csv", schema.ACHIEVEMENTS, [])
    out = build_dashboards(data, tmp_path / "formula-out", AS_OF)
    wb = load_workbook(out["master"], data_only=False)
    cell = wb["Overdue Tasks"].cell(2, 4)
    assert cell.data_type == "s"
    assert cell.value == "=1+1"


# --- Finding: multi-table sync is not an atomic/recoverable batch (High) --


def test_injected_failure_mid_batch_commits_nothing(tmp_path, monkeypatch):
    """A failure while staging one table must not leave an earlier table
    in the same batch committed -- the whole batch commits or none of it
    does, and the source workbook stays pending for a retry."""
    inbox = tmp_path / "partial-inbox"
    inbox.mkdir()
    data = tmp_path / "partial-data"
    w = Workbook()
    w.remove(w.active)
    rows = [
        (schema.TASKS, _task()),
        (schema.WEEKLY_UPDATES, dict(update_id="U1", team=TEAM, member=OWNER, week_ending=AS_OF.isoformat(), summary="Synthetic", hours_logged="1")),
    ]
    for tbl, row in rows:
        s = w.create_sheet(SHEET_TITLES[tbl.name])
        s.append(tbl.columns)
        s.append([row.get(c, "") for c in tbl.columns])
    w.save(inbox / "both.xlsx")

    orig_write_rows = csv_io.write_rows

    def injected(path, tbl, rows):
        if tbl.name == "weekly_updates":
            raise OSError("injected write failure")
        return orig_write_rows(path, tbl, rows)

    monkeypatch.setattr(csv_io, "write_rows", injected)
    # sync.py imported write_rows into its own namespace at module load
    # time (`from . import csv_io` -- it calls `csv_io.write_rows`, so
    # patching the module attribute above is what actually takes effect).
    with pytest.raises(OSError):
        sync(inbox, data, tmp_path / "partial-exceptions.csv")
    monkeypatch.undo()

    assert csv_io.read_rows(data / schema.TASKS.filename, schema.TASKS) == []
    assert csv_io.read_rows(data / schema.WEEKLY_UPDATES.filename, schema.WEEKLY_UPDATES) == []
    assert (inbox / "both.xlsx").exists()  # never archived -- nothing committed
    assert not (data / ".sync.lock").exists()  # lock released even on failure
    assert not list(data.glob("*.stage-*"))  # staging temp files cleaned up

    # Retry with the fault no longer injected must accept the task fresh,
    # not reject it as a duplicate of something that was never actually
    # committed the first time.
    retry = sync(inbox, data, tmp_path / "partial-exceptions.csv")
    assert retry["accepted"]["tasks"] == 1
    assert retry["accepted"]["weekly_updates"] == 1
    assert retry["exceptions"] == 0
    assert retry["workbooks_processed"] == 1


# --- Related, not a probe scenario itself: the fixes this review's High
# findings led to (malformed-workbook handling, single-writer lock).


def test_malformed_workbook_reported_not_fatal(tmp_path):
    """A corrupt/non-xlsx file dropped in the inbox must not crash the
    whole batch or silently vanish -- it gets a categorised exception and
    is left in place (unreadable, so nothing to safely archive)."""
    inbox = tmp_path / "corrupt-inbox"
    inbox.mkdir()
    (inbox / "corrupt.xlsx").write_bytes(b"not a zip file at all")
    data = tmp_path / "corrupt-data"
    summary = sync(inbox, data, tmp_path / "corrupt-exceptions.csv")
    assert summary["exceptions"] == 1
    assert summary["workbooks_processed"] == 0
    assert (inbox / "corrupt.xlsx").exists()
    report = csv_io.read_rows(tmp_path / "corrupt-exceptions.csv", schema.TableSchema(
        name="exceptions", filename="x", columns=["table", "source", "row_number", "category", "detail", "raw_row"], required=[]))
    assert report[0]["category"] == "unreadable_workbook"


def test_concurrent_sync_is_refused_by_the_local_lock(tmp_path):
    from team_dashboard.sync import SyncInProgressError

    data = tmp_path / "locked-data"
    data.mkdir()
    (data / ".sync.lock").write_text("12345")
    with pytest.raises(SyncInProgressError):
        sync(tmp_path / "inbox", data, tmp_path / "exceptions.csv")
    # A refused run must not remove a lock file it didn't create itself.
    assert (data / ".sync.lock").exists()


# ============================================================================
# Re-review probes (2026-09-27, held commit 10d2fdb) -- each reproduces one
# remaining finding from the re-review and asserts the behaviour the fix in
# this commit now guarantees.
# ============================================================================


def _init_empty_tables(data_dir):
    for tbl in schema.ALL_TABLES:
        csv_io.write_rows(data_dir / tbl.filename, tbl, [])


# --- Re-review finding 1 (High): commit-phase failure was not all-or-nothing


def test_commit_phase_failure_leaves_every_table_untouched(tmp_path, monkeypatch):
    """The original probe injected a failure into the *second* `os.replace`
    call of a real `sync()` run (not a mocked staging write): the first
    table's rename had already committed by the time the second one raised.
    Before this commit that left `tasks.csv` updated and `weekly_updates.csv`
    not, with the source workbook still pending -- so a retry re-submitted
    the already-committed task and it came back as a spurious `duplicate_key`.
    The commit phase must now back out its own already-applied renames on
    failure, exactly like the staging phase already did.
    """
    import team_dashboard.sync as sync_module

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    data = tmp_path / "data"
    _init_empty_tables(data)

    w = Workbook()
    w.remove(w.active)
    rows = [
        (schema.TASKS, _task()),
        (schema.WEEKLY_UPDATES, dict(update_id="U1", team=TEAM, member=OWNER, week_ending=AS_OF.isoformat(), summary="Synthetic", hours_logged="1")),
    ]
    for tbl, row in rows:
        s = w.create_sheet(SHEET_TITLES[tbl.name])
        s.append(tbl.columns)
        s.append([row.get(c, "") for c in tbl.columns])
    w.save(inbox / "both.xlsx")

    real_replace = sync_module.os.replace
    calls = 0

    def fail_second(a, b):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second commit-phase rename failure")
        return real_replace(a, b)

    monkeypatch.setattr(sync_module.os, "replace", fail_second)
    with pytest.raises(OSError):
        sync(inbox, data, tmp_path / "exceptions.csv")
    monkeypatch.undo()

    assert csv_io.read_rows(data / schema.TASKS.filename, schema.TASKS) == []
    assert csv_io.read_rows(data / schema.WEEKLY_UPDATES.filename, schema.WEEKLY_UPDATES) == []
    assert (inbox / "both.xlsx").exists()  # never archived -- nothing committed
    assert not (data / ".sync.lock").exists()  # lock released even on failure
    assert not list(data.glob("*.backup-*"))  # rollback cleaned up its own backups
    assert not list(data.glob("*.stage-*"))

    # A clean retry must accept both rows fresh, with no false duplicate --
    # nothing from the failed attempt was ever actually committed.
    retry = sync(inbox, data, tmp_path / "exceptions.csv")
    assert retry["accepted"]["tasks"] == 1
    assert retry["accepted"]["weekly_updates"] == 1
    assert retry["exceptions"] == 0
    assert retry["workbooks_processed"] == 1


# --- Re-review finding 2 (Medium): malformed CSV header read as zero activity


def test_malformed_csv_header_refuses_instead_of_reading_zero_rows(tmp_path):
    """A `tasks.csv` whose header is `not_a_task_header` (not the schema's
    columns) used to parse as a legitimate, merely-empty table --
    `compute_kpis` returned `planned_total=0` instead of refusing. A
    correct header-only (zero data rows) table must still be accepted."""
    data = tmp_path / "bad-header"
    _init_empty_tables(data)
    (data / "tasks.csv").write_text("not_a_task_header\n")
    with pytest.raises(SourceDataError):
        compute_kpis(data, AS_OF)


def test_correct_header_only_table_is_still_legitimately_empty(tmp_path):
    data = tmp_path / "empty-but-correct"
    _init_empty_tables(data)  # every table gets its real header, zero rows
    result = compute_kpis(data, AS_OF)
    assert result["overall"].planned_total == 0


# --- Re-review finding 3 (Medium): reordered achievements.csv columns
# corrupted the detail sheet


def test_reordered_achievement_csv_columns_map_by_name_in_detail_sheet(tmp_path):
    data = tmp_path / "reordered"
    _init_empty_tables(data)
    cols = list(reversed(schema.ACHIEVEMENTS.columns))
    row = dict(achievement_id="A1", team=TEAM, member=OWNER, week_ending=AS_OF.isoformat(), description="Synthetic achievement")
    import csv as csv_module

    with (data / "achievements.csv").open("w", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerow(row)

    result = build_dashboards(data, tmp_path / "dash", AS_OF)
    ws = load_workbook(result["master"])["Achievements This Week"]
    headers = [c.value for c in ws[1]]
    values = [c.value for c in ws[2]]
    assert headers == ["achievement_id", "team", "member", "week_ending", "description"]
    assert dict(zip(headers, values)) == row


# --- Re-review finding 4 (Medium): future completion/resolution still
# counted as already done/resolved as of a snapshot before it happened


def test_future_done_date_not_counted_done_but_task_is_overdue(tmp_path):
    """A task created 2026-09-01, planned 2026-09-20, marked `Done` with
    `done_date=2026-10-01` must not count as done as of 2026-09-21 -- its
    own completion date says it hadn't finished yet by then. Since its
    planned date has already passed and it wasn't done yet, it is overdue
    as of this snapshot instead."""
    data = tmp_path / "future-done"
    _init_empty_tables(data)
    csv_io.write_rows(data / "tasks.csv", schema.TASKS, [_task(status="Done", done_date="2026-10-01")])
    k = compute_kpis(data, AS_OF)
    assert k["overall"].done_total == 0
    assert sum(k["overall"].weekly_done_trend.values()) == 0
    assert k["overall"].overdue_total == 1


def test_future_resolved_date_blocker_still_counts_as_open(tmp_path):
    """Same principle on the blockers side: a blocker raised 2026-09-10,
    marked `Resolved` with `resolved_date` after the as-of date, was not
    actually resolved yet as of that snapshot."""
    data = tmp_path / "future-resolved"
    _init_empty_tables(data)
    csv_io.write_rows(data / "tasks.csv", schema.TASKS, [_task()])
    blocker = dict(
        blocker_id="B1", team=TEAM, task_id="T1", owner=OWNER, description="x",
        raised_date="2026-09-10", status="Resolved", resolved_date="2026-10-01",
    )
    csv_io.write_rows(data / "blockers.csv", schema.BLOCKERS, [blocker])
    k = compute_kpis(data, AS_OF)
    assert k["overall"].open_blockers_total == 1
