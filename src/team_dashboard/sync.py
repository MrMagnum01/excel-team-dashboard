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
  position -- a reordered-but-complete header still reads correctly,
  while a duplicated, missing, or extra header is rejected as one
  exception for the sheet rather than silently misreading values into
  the wrong field.
- **Batch commit, not a stream of appends -- staging and commit both.**
  All accepted rows for this run are staged into temporary files next to
  their real CSVs; nothing real is touched until every staged write has
  already succeeded (a bad row, an injected fault, a full disk during
  staging leaves every real file untouched, no cleanup needed). The
  commit phase that follows is not one atomic filesystem operation --
  a single rename() can't span several independent files -- so it is
  built as backup-then-swap-then-cleanup instead: every real file this
  batch changes is first moved aside with its own atomic rename, then
  the staged replacement is swapped into its place; if any step raises,
  every already-swapped file in this batch is put back from its backup
  before the error propagates. A fault anywhere during commit, not only
  during staging, therefore still leaves every canonical CSV, the
  exceptions report, and the inbox exactly as they were before this
  call, and a retry starts clean rather than replaying a partially
  committed batch as a false duplicate.
- **Durable batch-completion marker, written before archiving.** Once a
  batch's canonical CSVs have committed, this module writes one durable
  marker per input workbook -- keyed by the sha256 of that workbook's own
  bytes, under `data_dir/committed_batches/` -- *before* attempting to
  archive it. If archiving then fails (an injected fault, a permissions
  error, a full disk), the workbook stays in the inbox, but its marker
  already exists: a retry recognises it by content hash, does not
  re-parse or re-validate it (so its rows can never come back as a
  spurious `duplicate_key`), reports its rows as already committed, and
  simply finishes the archive step. The one case this doesn't cover is a
  hard-killed process (not an ordinary exception) landing in the narrow
  window between the commit finishing and the marker being written, or
  between the marker being written and the rename into `processed/` --
  see the README's "Limits" section for that residual, by-hand-
  recoverable window, the same class of caveat as the stale `.sync.lock`
  file below. A `.sync.lock` file in `data_dir` enforces the local
  single-writer-or-reader restriction this implies (see the README) --
  `kpis.compute_kpis` takes the same lock around its reads, so a refresh
  never observes this batch commit half-applied across the five tables.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from openpyxl import load_workbook

from . import csv_io, schema
from .input_workbook import NON_DATA_SHEETS, SHEET_TITLES
from .validation import EXCEPTIONS_COLUMNS, Exception_, validate_rows

# Tasks must be processed before blockers, so a blocker added in the same
# batch as its task can still be validated against a known task_id.
PROCESS_ORDER = [schema.TASKS, schema.BLOCKERS, schema.WEEKLY_UPDATES, schema.ACHIEVEMENTS, schema.KPI_TARGETS]

LOCK_NAME = ".sync.lock"

# Durable per-input-file "this batch already committed" markers. Keyed by
# the sha256 of the workbook's own bytes, written *after* the canonical
# CSVs (and the exceptions report) have committed but *before* that
# workbook is archived -- see `sync()`'s "batch-completion marker" phase
# below and the README's "Limits" section.
COMMITTED_BATCHES_DIR = "committed_batches"


class SyncInProgressError(RuntimeError):
    """Another `sync()` -- or a reader taking the same lock -- already
    holds the lock on this `data_dir`.

    This demo enforces a local single-writer-or-reader restriction instead
    of real concurrency control -- there is no SharePoint tenant here to
    provide that (see the README's "library/ stands in for..." section).
    `kpis.compute_kpis` takes this same lock around its reads (see
    `sync_lock` below) so a refresh can never observe a data directory
    mid-commit; it simply refuses, the same way a second concurrent
    `sync()` already did, rather than blocking or reading a partial
    snapshot. If a prior run crashed hard enough to skip its cleanup
    (killed, not an ordinary exception), the stale `.sync.lock` file must
    be removed by hand before the next run.
    """


@contextmanager
def sync_lock(data_dir: Path):
    """Acquire the local single-writer-or-reader lock on `data_dir`.

    Used by `sync()` itself and by `kpis.compute_kpis` (a reader): both
    hold the *same* lock, so a reader can never see `data_dir` partway
    through a `sync()` batch commit -- it either reads before the batch
    starts or after it (and its archive step) has fully finished, never a
    mix of old and new files across the five tables.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SyncInProgressError(
            f"{lock_path} already exists -- another sync() (or a reader) is using {data_dir} right now "
            "(local single-writer-or-reader restriction; see SyncInProgressError's docstring if this is stale)"
        )
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _content_hash(path: Path) -> str:
    """sha256 of the input workbook's own bytes -- the key a batch's
    "already committed" marker is filed under, so a byte-identical retry
    of the same input is recognised regardless of its filename."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _marker_path(data_dir: Path, content_hash: str) -> Path:
    return data_dir / COMMITTED_BATCHES_DIR / f"{content_hash}.json"


def _write_marker(marker_path: Path, payload: dict) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_name(marker_path.name + f".tmp-{uuid.uuid4().hex}")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, marker_path)


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

    with sync_lock(data_dir):
        workbook_paths = sorted(
            p for p in inbox_dir.glob("*.xlsx") if p.is_file() and not p.name.startswith("~$")
        )

        # Split the inbox into workbooks this batch has never seen before
        # and ones whose *exact* bytes a prior `sync()` call already
        # committed but failed to archive (see the module docstring's
        # "durable batch-completion marker" section). The latter are
        # skipped from parsing/validation entirely -- their rows are
        # already in the canonical CSVs -- and only need archiving, again.
        content_hash_by_path = {p: _content_hash(p) for p in workbook_paths}
        already_committed_paths: list[Path] = []
        new_paths: list[Path] = []
        for p in workbook_paths:
            if _marker_path(data_dir, content_hash_by_path[p]).exists():
                already_committed_paths.append(p)
            else:
                new_paths.append(p)

        existing_keys = {t.name: _existing_keys(data_dir, t) for t in PROCESS_ORDER}
        known_task_ids = {row["task_id"] for row in csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)}

        accepted_by_table: dict[str, list[dict]] = {t.name: [] for t in PROCESS_ORDER}
        all_exceptions: list[Exception_] = []
        processed_workbook_paths: list[Path] = []
        accepted_counts_by_workbook: dict[Path, dict[str, int]] = {}

        for wb_path in new_paths:
            try:
                wb = load_workbook(wb_path, data_only=True)
            except Exception as exc:  # noqa: BLE001 - any of openpyxl's several "not a valid workbook" errors
                all_exceptions.append(
                    Exception_("workbook", wb_path.name, 0, "unreadable_workbook",
                               f"could not open as an .xlsx workbook ({exc.__class__.__name__}: {exc})", {})
                )
                continue  # left in the inbox untouched -- nothing was read, so nothing to retry-corrupt

            consumed_sheets: set[str] = set()
            this_wb_accepted = {t.name: 0 for t in PROCESS_ORDER}
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
                this_wb_accepted[table.name] += len(accepted)
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

            accepted_counts_by_workbook[wb_path] = this_wb_accepted
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
        # `os.replace` is atomic on a POSIX filesystem for a *single* file,
        # but this batch touches several independent files with no shared
        # transaction log, so "all of them or none" has to be built rather
        # than assumed. Backup-then-swap-then-cleanup: every real file is
        # first moved aside (an atomic rename that either fully succeeds or
        # changes nothing), then the staged replacement is swapped into its
        # place. If any step in this loop raises, every already-swapped
        # file in this batch is restored from its backup (or removed, if it
        # had no prior version) before the failure propagates -- so a fault
        # partway through commit, not only during staging, still leaves
        # every canonical CSV and the exceptions report exactly as they
        # were before this call. This is the local-single-writer-lock-
        # protected window this module's docstring refers to.
        renamed_away: dict[Path, Path] = {}  # real_path -> backup of its pre-batch content
        swapped_in: set[Path] = set()  # real_path -> this batch's staged content now in place
        try:
            for real_path, tmp_path in staged.items():
                if real_path.exists():
                    backup_path = real_path.with_name(real_path.name + f".backup-{batch_id}")
                    os.replace(real_path, backup_path)
                    renamed_away[real_path] = backup_path
                os.replace(tmp_path, real_path)
                swapped_in.add(real_path)
        except Exception:
            for real_path in reversed(list(staged.keys())):
                if real_path in renamed_away:
                    os.replace(renamed_away[real_path], real_path)
                elif real_path in swapped_in:
                    real_path.unlink(missing_ok=True)
            # Any staged tmp file not yet consumed by its own os.replace
            # above (the one that failed, and every one after it in
            # iteration order that was never reached) is leftover staging
            # residue, same as a staging-phase failure already cleans up.
            for tmp_path in staged.values():
                tmp_path.unlink(missing_ok=True)
            raise
        finally:
            for backup_path in renamed_away.values():
                backup_path.unlink(missing_ok=True)

        # --- batch-completion markers ------------------------------------
        # The canonical CSVs and the exceptions report have now committed.
        # Before touching the inbox at all, record one durable marker per
        # newly-processed workbook, keyed by its own content hash, so that
        # if the archive step below fails (an injected fault, a full disk,
        # a permissions error) a retry recognises this exact input as
        # already committed instead of re-validating it and rejecting its
        # own already-applied rows as `duplicate_key`.
        for wb_path in processed_workbook_paths:
            _write_marker(
                _marker_path(data_dir, content_hash_by_path[wb_path]),
                {
                    "source": wb_path.name,
                    "committed_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "accepted": accepted_counts_by_workbook[wb_path],
                },
            )

        # A workbook recognised by its marker as already committed still
        # needs its rows counted for this run's report -- as already
        # committed, never as a fresh `accepted` count (nothing of theirs
        # was touched this run) and never as a `duplicate_key` exception
        # (they were never re-validated at all).
        already_committed_by_table = {t.name: 0 for t in PROCESS_ORDER}
        for wb_path in already_committed_paths:
            marker = json.loads(_marker_path(data_dir, content_hash_by_path[wb_path]).read_text(encoding="utf-8"))
            for name, count in marker.get("accepted", {}).items():
                if name in already_committed_by_table:
                    already_committed_by_table[name] += count

        # --- archive phase ---------------------------------------------
        # Every workbook that contributed to this batch's commit -- freshly
        # processed just now, or already committed by an earlier run and
        # only now catching up on a previously failed archive step -- is
        # moved out of the inbox.
        to_archive = processed_workbook_paths + already_committed_paths
        if to_archive:
            processed_dir.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
            for wb_path in to_archive:
                wb_path.rename(processed_dir / f"{stamp}_{wb_path.name}")

        return {
            "accepted": {name: len(rows) for name, rows in accepted_by_table.items()},
            "already_committed": already_committed_by_table,
            "exceptions": len(all_exceptions),
            "workbooks_processed": len(to_archive),
        }
