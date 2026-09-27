"""Row-level validation shared by `sync.py`.

Every rejected row gets exactly one categorised exception (the first check
it fails) and is never appended to a CSV. Nothing is silently dropped: a
row is either accepted or it shows up in the exceptions report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from .schema import TableSchema
from .teams import TEAMS


@dataclass
class Exception_:
    table: str
    source: str
    row_number: int
    category: str
    detail: str
    raw_row: dict

    def as_report_row(self) -> dict:
        return {
            "table": self.table,
            "source": self.source,
            "row_number": self.row_number,
            "category": self.category,
            "detail": self.detail,
            "raw_row": json.dumps(self.raw_row, default=str, sort_keys=True),
        }


EXCEPTIONS_COLUMNS = ["table", "source", "row_number", "category", "detail", "raw_row"]


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_rows(
    table: TableSchema,
    rows: list[dict],
    *,
    source: str,
    existing_keys: set[tuple],
    known_task_ids: set[str] | None = None,
) -> tuple[list[dict], list[Exception_]]:
    """Validate `rows` for `table`. Returns (accepted, exceptions).

    `existing_keys` is mutated (accepted rows' keys are added to it) so that
    duplicates *within the same batch* are also caught, not just duplicates
    against what's already on disk.
    """
    accepted: list[dict] = []
    exceptions: list[Exception_] = []

    for i, raw in enumerate(rows, start=1):
        row = {col: raw.get(col, "") for col in table.columns}

        # 1. required fields present
        missing = [f for f in table.required if _is_blank(row.get(f))]
        if missing:
            exceptions.append(
                Exception_(table.name, source, i, "missing_required_field", f"missing: {', '.join(missing)}", raw)
            )
            continue

        # 2. dates parse
        bad_date = None
        for f in table.date_fields:
            val = row.get(f)
            if _is_blank(val):
                continue
            try:
                date.fromisoformat(str(val))
            except ValueError:
                bad_date = f
                break
        if bad_date:
            exceptions.append(
                Exception_(table.name, source, i, "invalid_date", f"{bad_date}={row.get(bad_date)!r} is not YYYY-MM-DD", raw)
            )
            continue

        # 3. enums valid
        bad_enum = None
        for f, allowed in table.enum_fields.items():
            val = row.get(f)
            if _is_blank(val):
                continue
            if val not in allowed:
                bad_enum = (f, val, allowed)
                break
        if bad_enum:
            f, val, allowed = bad_enum
            exceptions.append(
                Exception_(table.name, source, i, "invalid_enum", f"{f}={val!r} not in {allowed}", raw)
            )
            continue

        # 4. team must be a registered team
        if "team" in table.columns and row.get("team") not in TEAMS:
            exceptions.append(
                Exception_(table.name, source, i, "unknown_team", f"team={row.get('team')!r} is not registered", raw)
            )
            continue

        # 5. owner/member must belong to that team, when present
        member_field = "owner" if "owner" in table.columns else ("member" if "member" in table.columns else None)
        if member_field:
            person = row.get(member_field)
            team = row.get("team")
            if not _is_blank(person) and team in TEAMS and person not in TEAMS[team]:
                exceptions.append(
                    Exception_(
                        table.name, source, i, "unknown_member",
                        f"{member_field}={person!r} is not a member of {team!r}", raw,
                    )
                )
                continue

        # 6. numeric fields must parse as non-negative numbers
        numeric_fields = [f for f in ("hours_logged", "planned_tasks", "target_done") if f in table.columns]
        bad_numeric = None
        for f in numeric_fields:
            val = row.get(f)
            try:
                num = float(val)
                if num < 0 or num != num:  # NaN check
                    raise ValueError
            except (TypeError, ValueError):
                bad_numeric = (f, val)
                break
        if bad_numeric:
            f, val = bad_numeric
            exceptions.append(
                Exception_(table.name, source, i, "invalid_number", f"{f}={val!r} is not a non-negative number", raw)
            )
            continue

        # 7. blockers must reference a real task
        if table.name == "blockers" and known_task_ids is not None:
            if row.get("task_id") not in known_task_ids:
                exceptions.append(
                    Exception_(table.name, source, i, "unknown_task_id", f"task_id={row.get('task_id')!r} not found in tasks.csv", raw)
                )
                continue

        # 8. no duplicates (against disk + this batch)
        key = tuple(row.get(f) for f in table.key_fields)
        if table.key_fields and key in existing_keys:
            exceptions.append(
                Exception_(table.name, source, i, "duplicate_key", f"key {table.key_fields}={key} already exists", raw)
            )
            continue

        if table.key_fields:
            existing_keys.add(key)
        accepted.append(row)

    return accepted, exceptions
