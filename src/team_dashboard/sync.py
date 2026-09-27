"""Reads every member input workbook dropped into the inbox, validates every
row, appends the good ones to the canonical CSVs, and writes a categorised
exceptions report for the rest. Nothing is silently dropped.

`library/inbox/` stands in for the folder in a shared SharePoint document
library where members would drop their filled-in input workbooks -- see
the README for why this demo uses a local folder instead of a real
SharePoint tenant.

Two properties this module is written to hold, beyond per-row validation:

- **Header-driven, not position-driven.** Every sheet's columns are
  resolved by matching its header row against the schema, not by column
  position -- a reordered, duplicated, missing, or extra header is
  rejected as an exception rather than silently misreading values into
  the wrong field.
- **Batch commit, not a stream of appends.** All accepted rows for this
  run are staged into temporary files next to their real CSVs; the real
  files are only touched by a fast run of atomic renames after every
  staged write has already succeeded. A failure anywhere during staging
  (a bad row, an injected fault, a full disk) leaves every canonical CSV,
  the exceptions report, and the inbox exactly as they were before this
  call -- there is no partially-applied batch to reconcile, and a retry
  starts clean. A `.sync.lock` file in `data_dir` enforces the local
  single-writer restriction this implies (see the README).
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

from openpyxl import load_workbook

from . import csv_io, schema
from .input_workbook import NON_DATA_SHEETS, SHEET_TITLES
from .validation import EXCEPTIONS_COLUMNS, Exception_, validate_rows

# Tasks must be processed before blockers, so a blocker added in the same
# batch as its task can still be validated against a known task_id.
PROCESS_ORDER = [schema.TASKS, schema.BLOCKERS, schema.WEEKLY_UPDATES, schema.ACHIEVEMENTS, schema.KPI_TARGETS]

LOCK_NAME = ".sync.lock"


class SyncInProgressError(RuntimeError):
    """Another `sync()` already holds the lock on this `data_dir`.

    This demo enforces a local single-writer restriction instead of real
    concurrency control -- there is no SharePoint tenant here to provide
    that (see the README's "library/ stands in for..." section). If a
    prior run crashed hard enough to skip its cleanup (killed, not an
    ordinary exception), the stale `.sync.lock` file must be removed by
    hand before the next run.
    """


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


def _is_blank_cell(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _header_row(ws) -> list[str]:
    """The non-blank header cell values in row 1, in column order."""
    headers = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if _is_blank_cell(v):
            continue
        headers.append(str(v).strip())
    return headers


def _column_map(ws, table: schema.TableSchema) -> dict[str, int] | None:
    """Map column name -> 1-based sheet column index, from the header row.

    Returns None if the header row does not contain *exactly* the
    schema's columns: a duplicate header name, a missing column, or an
    extra/unrecognised column all make positional extraction unsafe, so
    the caller must reject the sheet rather than guess. A reordered but
    otherwise complete and unambiguous header row is fine -- that's the
    whole point of mapping by name instead of by position.
    """
    seen: dict[str, list[int]] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if _is_blank_cell(v):
            continue
        seen.setdefault(str(v).strip(), []).append(c)
    if any(len(cols) > 1 for cols in seen.values()):
        return None  # duplicate header name
    if set(seen.keys()) != set(table.columns):
        return None  # missing and/or extra/unrecognised columns
    return {name: cols[0] for name, cols in seen.items()}


def _extract_rows(ws, table: schema.TableSchema, column_map: dict[str, int]) -> list[dict]:
    rows = []
    for r in range(2, ws.max_row + 1):
        row = {col: _normalize(ws.cell(row=r, column=column_map[col]).value) for col in table.columns}
        if all(v == "" for v in row.values()):
            continue
        rows.append(row)
    return rows


def _sheet_has_data_rows(ws) -> bool:
    for r in range(2, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            if not _is_blank_cell(ws.cell(row=r, column=c).value):
                return True
    return False


def _existing_keys(data_dir: Path, table: schema.TableSchema) -> set[tuple]:
    rows = csv_io.read_rows(data_dir / table.filename, table)
    if not table.key_fields:
        return set()
    return {tuple(row.get(f) for f in table.key_fields) for row in rows}


def sync(inbox_dir: Path, data_dir: Path, exceptions_path: Path) -> dict:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    processed_dir = inbox_dir / "processed"

    lock_path = data_dir / LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SyncInProgressError(
            f"{lock_path} already exists -- another sync() is writing to {data_dir} right now "
            "(local single-writer restriction; see SyncInProgressError's docstring if this is stale)"
        )
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)

    try:
        workbook_paths = sorted(
            p for p in inbox_dir.glob("*.xlsx") if p.is_file() and not p.name.startswith("~$")
        )

        existing_keys = {t.name: _existing_keys(data_dir, t) for t in PROCESS_ORDER}
        known_task_ids = {row["task_id"] for row in csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)}

        accepted_by_table: dict[str, list[dict]] = {t.name: [] for t in PROCESS_ORDER}
        all_exceptions: list[Exception_] = []
        processed_workbook_paths: list[Path] = []

        for wb_path in workbook_paths:
            try:
                wb = load_workbook(wb_path, data_only=True)
            except Exception as exc:  # noqa: BLE001 - any of openpyxl's several "not a valid workbook" errors
                all_exceptions.append(
                    Exception_("workbook", wb_path.name, 0, "unreadable_workbook",
                               f"could not open as an .xlsx workbook ({exc.__class__.__name__}: {exc})", {})
                )
                continue  # left in the inbox untouched -- nothing was read, so nothing to retry-corrupt

            consumed_sheets: set[str] = set()
            for table in PROCESS_ORDER:
                sheet_title = SHEET_TITLES[table.name]
                if sheet_title not in wb.sheetnames:
                    continue
                consumed_sheets.add(sheet_title)
                ws = wb[sheet_title]
                column_map = _column_map(ws, table)
                if column_map is None:
                    all_exceptions.append(
                        Exception_(table.name, f"{wb_path.name}:{sheet_title}", 0, "invalid_schema",
                                   f"header row {_header_row(ws)} does not exactly match expected columns "
                                   f"{table.columns} (missing, extra, or duplicate column name)", {})
                    )
                    continue
                raw_rows = _extract_rows(ws, table, column_map)
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

            # Every non-empty sheet that isn't a known data tab or one of
            # the workbook's own non-data sheets (Start Here, Lists) is an
            # unrecognised submission -- e.g. a mistyped tab name -- and
            # must show up in the exceptions report, not vanish as a
            # workbook that was "processed" with nothing accepted or
            # rejected.
            for sheet_name in wb.sheetnames:
                if sheet_name in consumed_sheets or sheet_name in NON_DATA_SHEETS:
                    continue
                if _sheet_has_data_rows(wb[sheet_name]):
                    all_exceptions.append(
                        Exception_("workbook", f"{wb_path.name}:{sheet_name}", 0, "unrecognised_sheet",
                                   f"sheet {sheet_name!r} is not one of the expected tabs "
                                   f"{sorted(SHEET_TITLES.values())} and was not processed", {})
                    )

            processed_workbook_paths.append(wb_path)

        # --- staging phase -----------------------------------------------
        # Build every changed file's full new content in a temp file next
        # to its target. Nothing real is touched until every write below
        # has already succeeded.
        batch_id = uuid.uuid4().hex
        staged: dict[Path, Path] = {}
        try:
            for table in PROCESS_ORDER:
                if not accepted_by_table[table.name]:
                    continue
                real_path = data_dir / table.filename
                existing_rows = csv_io.read_rows(real_path, table)
                tmp_path = real_path.with_name(real_path.name + f".stage-{batch_id}")
                csv_io.write_rows(tmp_path, table, existing_rows + accepted_by_table[table.name])
                staged[real_path] = tmp_path

            exceptions_path.parent.mkdir(parents=True, exist_ok=True)
            exceptions_tmp = exceptions_path.with_name(exceptions_path.name + f".stage-{batch_id}")
            csv_io.write_rows(
                exceptions_tmp,
                schema.TableSchema(name="exceptions", filename=exceptions_path.name, columns=EXCEPTIONS_COLUMNS, required=[]),
                [e.as_report_row() for e in all_exceptions],
            )
            staged[exceptions_path] = exceptions_tmp
        except Exception:
            # Staging failed partway through: remove whatever temp files
            # did get written so nothing but this batch's intended targets
            # is left behind, then re-raise. No real file has been touched
            # yet, so the canonical CSVs, the exceptions report and the
            # inbox are exactly as they were before this call.
            for tmp_path in staged.values():
                tmp_path.unlink(missing_ok=True)
            raise

        # --- commit phase --------------------------------------------------
        # `os.replace` is atomic on a POSIX filesystem; running every
        # replace back-to-back with no other I/O between them is what
        # "commit" means for a set of plain files with no shared
        # transaction log. This is the local-single-writer-lock-protected
        # window this module's docstring refers to.
        for real_path, tmp_path in staged.items():
            os.replace(tmp_path, real_path)

        # --- archive phase ---------------------------------------------
        # Only workbooks that were actually read (not ones that failed to
        # even open) get moved out of the inbox, and only after the batch
        # they contributed to has committed.
        if processed_workbook_paths:
            processed_dir.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
            for wb_path in processed_workbook_paths:
                wb_path.rename(processed_dir / f"{stamp}_{wb_path.name}")

        return {
            "accepted": {name: len(rows) for name, rows in accepted_by_table.items()},
            "exceptions": len(all_exceptions),
            "workbooks_processed": len(processed_workbook_paths),
        }
    finally:
        lock_path.unlink(missing_ok=True)
