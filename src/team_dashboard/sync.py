"""Reads every member input workbook dropped into the inbox, validates every
row, appends the good ones to the canonical CSVs, and writes a categorised
exceptions report for the rest. Nothing is silently dropped.

`library/inbox/` stands in for the folder in a shared SharePoint document
library where members would drop their filled-in input workbooks -- see
the README for why this demo uses a local folder instead of a real
SharePoint tenant.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import load_workbook

from . import csv_io, schema
from .input_workbook import SHEET_TITLES
from .validation import EXCEPTIONS_COLUMNS, validate_rows

# Tasks must be processed before blockers, so a blocker added in the same
# batch as its task can still be validated against a known task_id.
PROCESS_ORDER = [schema.TASKS, schema.BLOCKERS, schema.WEEKLY_UPDATES, schema.ACHIEVEMENTS, schema.KPI_TARGETS]


def _normalize(value):
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def _extract_rows(ws, columns: list[str]) -> list[dict]:
    rows = []
    for r in range(2, ws.max_row + 1):
        values = [_normalize(ws.cell(row=r, column=c + 1).value) for c in range(len(columns))]
        if all(v == "" for v in values):
            continue
        rows.append(dict(zip(columns, values)))
    return rows


def _existing_keys(data_dir: Path, table: schema.TableSchema) -> set[tuple]:
    rows = csv_io.read_rows(data_dir / table.filename, table)
    if not table.key_fields:
        return set()
    return {tuple(row.get(f) for f in table.key_fields) for row in rows}


def sync(inbox_dir: Path, data_dir: Path, exceptions_path: Path) -> dict:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    processed_dir = inbox_dir / "processed"

    workbook_paths = sorted(
        p for p in inbox_dir.glob("*.xlsx") if p.is_file() and not p.name.startswith("~$")
    )

    existing_keys = {t.name: _existing_keys(data_dir, t) for t in PROCESS_ORDER}
    known_task_ids = {row["task_id"] for row in csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)}

    accepted_by_table: dict[str, list[dict]] = {t.name: [] for t in PROCESS_ORDER}
    all_exceptions = []

    for wb_path in workbook_paths:
        wb = load_workbook(wb_path, data_only=True)
        for table in PROCESS_ORDER:
            sheet_title = SHEET_TITLES[table.name]
            if sheet_title not in wb.sheetnames:
                continue
            raw_rows = _extract_rows(wb[sheet_title], table.columns)
            if not raw_rows:
                continue
            accepted, exceptions = validate_rows(
                table,
                raw_rows,
                source=f"{wb_path.name}:{sheet_title}",
                existing_keys=existing_keys[table.name],
                known_task_ids=known_task_ids if table.name == "blockers" else None,
            )
            accepted_by_table[table.name].extend(accepted)
            all_exceptions.extend(exceptions)
            if table.name == "tasks":
                known_task_ids.update(r["task_id"] for r in accepted)

    for table in PROCESS_ORDER:
        if accepted_by_table[table.name]:
            csv_io.append_rows(data_dir / table.filename, table, accepted_by_table[table.name])

    exceptions_path.parent.mkdir(parents=True, exist_ok=True)
    csv_io.write_rows(
        exceptions_path,
        schema.TableSchema(name="exceptions", filename=exceptions_path.name, columns=EXCEPTIONS_COLUMNS, required=[]),
        [e.as_report_row() for e in all_exceptions],
    )

    if workbook_paths:
        processed_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        for wb_path in workbook_paths:
            wb_path.rename(processed_dir / f"{stamp}_{wb_path.name}")

    return {
        "accepted": {name: len(rows) for name, rows in accepted_by_table.items()},
        "exceptions": len(all_exceptions),
        "workbooks_processed": len(workbook_paths),
    }
