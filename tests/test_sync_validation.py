"""Failure tests for every bad-input class `sync` recognises (Astra's
publication checklist, item 2). Each class gets a unit test against
`validate_rows` directly, plus one end-to-end test that runs `sync()` over
a real filled-in workbook mixing valid rows with one of every bad class and
checks that every row is accounted for (accepted xor rejected, never both,
never neither).
"""

from __future__ import annotations

from datetime import date

import pytest

from team_dashboard import schema
from team_dashboard.validation import validate_rows

GOOD_TASK = {
    "task_id": "T-TEST-0001",
    "team": "Team Aurora",
    "owner": "Priya Nandan",
    "title": "Write the test plan",
    "status": "In Progress",
    "planned_date": "2026-09-20",
    "done_date": "",
    "created_date": "2026-09-15",
}


def _accept_reject(rows, table=schema.TASKS, known_task_ids=None):
    return validate_rows(table, rows, source="test", existing_keys=set(), known_task_ids=known_task_ids)


def test_valid_row_is_accepted():
    accepted, exceptions = _accept_reject([dict(GOOD_TASK)])
    assert len(accepted) == 1
    assert exceptions == []


def test_missing_required_field_rejected():
    bad = {**GOOD_TASK, "title": ""}
    accepted, exceptions = _accept_reject([bad])
    assert accepted == []
    assert len(exceptions) == 1
    assert exceptions[0].category == "missing_required_field"


def test_invalid_date_rejected():
    bad = {**GOOD_TASK, "planned_date": "09/20/2026"}
    accepted, exceptions = _accept_reject([bad])
    assert accepted == []
    assert exceptions[0].category == "invalid_date"


def test_invalid_enum_rejected():
    bad = {**GOOD_TASK, "status": "Sort Of Done"}
    accepted, exceptions = _accept_reject([bad])
    assert accepted == []
    assert exceptions[0].category == "invalid_enum"


def test_unknown_team_rejected():
    bad = {**GOOD_TASK, "team": "Team Nonexistent"}
    accepted, exceptions = _accept_reject([bad])
    assert accepted == []
    assert exceptions[0].category == "unknown_team"


def test_unknown_member_rejected():
    bad = {**GOOD_TASK, "owner": "Nobody Here"}
    accepted, exceptions = _accept_reject([bad])
    assert accepted == []
    assert exceptions[0].category == "unknown_member"


def test_duplicate_key_rejected():
    accepted, exceptions = _accept_reject([dict(GOOD_TASK), dict(GOOD_TASK)])
    assert len(accepted) == 1
    assert len(exceptions) == 1
    assert exceptions[0].category == "duplicate_key"


def test_duplicate_against_existing_on_disk_rejected():
    existing = {("T-TEST-0001",)}
    accepted, exceptions = validate_rows(
        schema.TASKS, [dict(GOOD_TASK)], source="test", existing_keys=existing, known_task_ids=None
    )
    assert accepted == []
    assert exceptions[0].category == "duplicate_key"


def test_invalid_number_rejected_for_hours_logged():
    bad_update = {
        "update_id": "U-TEST-0001",
        "team": "Team Aurora",
        "member": "Priya Nandan",
        "week_ending": "2026-09-21",
        "summary": "test",
        "hours_logged": "-5",
    }
    accepted, exceptions = _accept_reject([bad_update], table=schema.WEEKLY_UPDATES)
    assert accepted == []
    assert exceptions[0].category == "invalid_number"


def test_non_numeric_hours_logged_rejected():
    bad_update = {
        "update_id": "U-TEST-0002",
        "team": "Team Aurora",
        "member": "Priya Nandan",
        "week_ending": "2026-09-21",
        "summary": "test",
        "hours_logged": "forty",
    }
    accepted, exceptions = _accept_reject([bad_update], table=schema.WEEKLY_UPDATES)
    assert accepted == []
    assert exceptions[0].category == "invalid_number"


def test_unknown_task_id_rejected_for_blockers():
    bad_blocker = {
        "blocker_id": "B-TEST-0001",
        "team": "Team Aurora",
        "task_id": "T-DOES-NOT-EXIST",
        "owner": "Priya Nandan",
        "description": "blocked",
        "raised_date": "2026-09-19",
        "status": "Open",
        "resolved_date": "",
    }
    accepted, exceptions = _accept_reject([bad_blocker], table=schema.BLOCKERS, known_task_ids={"T-REAL-0001"})
    assert accepted == []
    assert exceptions[0].category == "unknown_task_id"


def test_first_failing_check_wins_and_nothing_is_dropped_silently():
    rows = [dict(GOOD_TASK), {**GOOD_TASK, "task_id": "T-TEST-0002", "title": ""}, {**GOOD_TASK, "task_id": "T-TEST-0003", "status": "Nope"}]
    accepted, exceptions = _accept_reject(rows)
    assert len(accepted) + len(exceptions) == len(rows)
    assert len(accepted) == 1
    assert {e.category for e in exceptions} == {"missing_required_field", "invalid_enum"}


# --- end-to-end: a real workbook through sync() ---


def _copy_data_dir(data_dir, dest):
    import shutil

    shutil.copytree(data_dir, dest)
    return dest


def test_sync_end_to_end_with_sample_inbox(data_dir, tmp_path):
    from team_dashboard import csv_io
    from team_dashboard.sample_inbox import build_sample_inbox_workbook
    from team_dashboard.sync import sync

    # sync() mutates the CSVs it's pointed at, so work on a private copy --
    # `data_dir` is a session fixture shared with the KPI reconciliation
    # tests and must not be changed out from under them.
    work_dir = _copy_data_dir(data_dir, tmp_path / "data")

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    build_sample_inbox_workbook(inbox / "priya.xlsx", work_dir, "2026-09-21")

    before_tasks = len(csv_io.read_rows(work_dir / schema.TASKS.filename, schema.TASKS))

    summary = sync(inbox, work_dir, tmp_path / "exceptions_report.csv")

    after_tasks = len(csv_io.read_rows(work_dir / schema.TASKS.filename, schema.TASKS))
    assert after_tasks == before_tasks + summary["accepted"]["tasks"]
    assert summary["accepted"]["tasks"] == 1
    assert summary["accepted"]["blockers"] == 1
    assert summary["accepted"]["weekly_updates"] == 1
    assert summary["accepted"]["achievements"] == 1
    assert summary["exceptions"] == 8  # every bad-input class in sample_inbox.py

    report_rows = csv_io.read_rows(
        tmp_path / "exceptions_report.csv",
        schema.TableSchema(name="exceptions", filename="x", columns=[
            "table", "source", "row_number", "category", "detail", "raw_row"
        ], required=[]),
    )
    categories = {r["category"] for r in report_rows}
    assert categories == {
        "missing_required_field", "invalid_enum", "invalid_date",
        "unknown_team", "unknown_member", "duplicate_key",
        "unknown_task_id", "invalid_number",
    }

    # The workbook was moved out of the inbox so a re-run can't double-apply it.
    assert not (inbox / "priya.xlsx").exists()
    assert list((inbox / "processed").glob("*priya.xlsx"))


def test_sync_is_idempotent_after_processing(data_dir, tmp_path):
    """Re-running sync with an empty inbox changes nothing and errors on nothing."""
    from team_dashboard.sync import sync

    work_dir = _copy_data_dir(data_dir, tmp_path / "data")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    summary = sync(inbox, work_dir, tmp_path / "exceptions_report.csv")
    assert summary["workbooks_processed"] == 0
    assert summary["exceptions"] == 0
