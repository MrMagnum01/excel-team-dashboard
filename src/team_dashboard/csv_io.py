"""Small CSV read/write/append helpers shared by generator, sync, and dashboard.

Every row is a plain dict keyed by the table's schema column names. Nothing
here is pandas — the whole project deliberately stays on the standard
library plus openpyxl, to keep the dependency set (and LICENSES.md) short.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .schema import TableSchema


class SourceDataError(RuntimeError):
    """A required canonical CSV is missing or fails schema validation.

    Raised by callers (see `kpis.compute_kpis`) that must refuse to build a
    dashboard from incomplete or corrupt source data rather than silently
    treating an absent/invalid file as "zero activity".
    """


def write_rows(path: Path, schema: TableSchema, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=schema.columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in schema.columns})


def read_rows(path: Path, schema: TableSchema) -> list[dict]:
    """Read every data row of `path` as a dict keyed by `schema`'s columns.

    A missing file is treated as legitimately empty (the caller decides
    whether that's acceptable). A file that *exists* must have exactly
    `schema`'s columns in its header row -- as a set, so a reordered-but-
    complete header is fine, matching how `sync.py` reads workbook sheets
    -- or every row is refused before any is read: a wrong, mistyped, or
    truncated header (`not_a_task_header` instead of the schema's columns,
    say) must not be read as a quietly-empty, schema-correct table just
    because it happens to have zero data rows.
    """
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        if sorted(fieldnames) != sorted(schema.columns):
            raise SourceDataError(
                f"{path} header {fieldnames} does not exactly match expected columns "
                f"{schema.columns} (missing, extra, or duplicate column name) -- refusing to "
                "read rows from a table whose schema doesn't match, rather than treating a "
                "wrong header as zero real activity"
            )
        return [dict(row) for row in reader]


def append_rows(path: Path, schema: TableSchema, rows: list[dict]) -> None:
    """Append validated rows to an existing (or not-yet-created) CSV.

    Always writes the full schema column order regardless of what order the
    existing file happens to have, so a header mismatch cannot silently
    shift a value into the wrong column.
    """
    existing = read_rows(path, schema)
    write_rows(path, schema, existing + rows)
