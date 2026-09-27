"""Builds the member input workbook: one openpyxl .xlsx with dropdown data
validation, so a team member can add new tasks/updates/blockers/achievements
without typing free-text team names or statuses that `sync.py` would then
have to guess at.

This workbook is filled out by hand (in Excel or LibreOffice) and dropped
into `library/inbox/`, the local stand-in for a SharePoint document
library. `sync.py` reads every workbook there and validates each row.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .schema import ALL_TABLES, TableSchema
from .teams import ALL_MEMBERS, TEAM_NAMES

BLANK_ROWS = 200
SHEET_TITLES = {
    "tasks": "New Tasks",
    "weekly_updates": "New Weekly Updates",
    "blockers": "New Blockers",
    "achievements": "New Achievements",
    "kpi_targets": "New KPI Targets",
}

# Sheets the input workbook ships that are not a data table -- `sync.py`
# must not treat these (or their absence) as an unrecognised submission.
NON_DATA_SHEETS = {"Start Here", "Lists"}


def _add_lists_sheet(wb: Workbook):
    ws = wb.create_sheet("Lists")
    ws["A1"] = "Teams"
    ws["B1"] = "Members"
    for i, team in enumerate(TEAM_NAMES, start=2):
        ws.cell(row=i, column=1, value=team)
    for i, member in enumerate(ALL_MEMBERS, start=2):
        ws.cell(row=i, column=2, value=member)
    ws.sheet_state = "hidden"
    return ws


def _add_instructions_sheet(wb: Workbook):
    ws = wb.create_sheet("Start Here", 0)
    ws["A1"] = "Team progress input workbook"
    ws["A1"].font = Font(bold=True, size=14)
    lines = [
        "",
        "Fill in one row per new item on each tab below. Leave the ID column blank",
        "unless you're correcting a prior submission -- if you leave it blank, use",
        "your initials plus a running number (e.g. PN-1) so it stays unique.",
        "",
        "Dates go in YYYY-MM-DD format. Team, status and member columns are",
        "dropdowns -- please pick from the list rather than typing.",
        "",
        "When done, save this file into the library/inbox/ folder (the local",
        "stand-in for the shared SharePoint library) and run the sync step.",
        "Rows that don't validate are never silently dropped -- they show up",
        "in the exceptions report instead, with the reason.",
    ]
    for i, line in enumerate(lines, start=2):
        ws.cell(row=i, column=1, value=line)
    ws.column_dimensions["A"].width = 90
    return ws


def _sheet_for_table(wb: Workbook, table: TableSchema, lists_sheet_name: str = "Lists"):
    ws = wb.create_sheet(SHEET_TITLES[table.name])
    header_font = Font(bold=True)
    for col_idx, col_name in enumerate(table.columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        ws.column_dimensions[get_column_letter(col_idx)].width = max(14, len(col_name) + 2)
    ws.freeze_panes = "A2"

    last_row = BLANK_ROWS + 1

    for col_idx, col_name in enumerate(table.columns, start=1):
        col_letter = get_column_letter(col_idx)
        cell_range = f"{col_letter}2:{col_letter}{last_row}"

        if col_name == "team":
            dv = DataValidation(type="list", formula1=f"={lists_sheet_name}!$A$2:$A${1 + len(TEAM_NAMES)}", allow_blank=True)
            dv.error = "Pick a registered team from the dropdown."
            dv.errorTitle = "Unknown team"
        elif col_name in ("owner", "member"):
            dv = DataValidation(type="list", formula1=f"={lists_sheet_name}!$B$2:$B${1 + len(ALL_MEMBERS)}", allow_blank=True)
            dv.error = "Pick a team member from the dropdown."
            dv.errorTitle = "Unknown member"
        elif col_name in table.enum_fields:
            allowed = table.enum_fields[col_name]
            dv = DataValidation(type="list", formula1='"' + ",".join(allowed) + '"', allow_blank=True)
            dv.error = f"Must be one of: {', '.join(allowed)}."
            dv.errorTitle = "Invalid value"
        elif col_name in table.date_fields:
            dv = DataValidation(type="date", operator="between", formula1="2020-01-01", formula2="2035-12-31", allow_blank=True)
            dv.error = "Enter a real date between 2020-01-01 and 2035-12-31 (format YYYY-MM-DD)."
            dv.errorTitle = "Invalid date"
        else:
            continue

        dv.showErrorMessage = True
        ws.add_data_validation(dv)
        dv.add(cell_range)

    return ws


def build_input_workbook(path: Path) -> None:
    """Build a blank member input workbook with dropdown validation for every table."""
    wb = Workbook()
    wb.remove(wb.active)  # drop the default blank sheet
    _add_instructions_sheet(wb)
    lists_ws = _add_lists_sheet(wb)
    for table in ALL_TABLES:
        _sheet_for_table(wb, table, lists_sheet_name=lists_ws.title)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
