"""Small CSV read/write/append helpers shared by generator, sync, and dashboard.

Every row is a plain dict keyed by the table's schema column names. Nothing
here is pandas — the whole project deliberately stays on the standard
library plus openpyxl, to keep the dependency set (and LICENSES.md) short.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .schema import TableSchema


def write_rows(path: Path, schema: TableSchema, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=schema.columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in schema.columns})


def read_rows(path: Path, schema: TableSchema) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def append_rows(path: Path, schema: TableSchema, rows: list[dict]) -> None:
    """Append validated rows to an existing (or not-yet-created) CSV.

    Always writes the full schema column order regardless of what order the
    existing file happens to have, so a header mismatch cannot silently
    shift a value into the wrong column.
    """
    existing = read_rows(path, schema)
    write_rows(path, schema, existing + rows)
