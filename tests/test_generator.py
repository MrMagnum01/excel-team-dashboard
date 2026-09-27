from __future__ import annotations

import csv
from datetime import date

from team_dashboard import csv_io, generator, schema
from team_dashboard.teams import TEAM_NAMES


def test_generator_is_deterministic(tmp_path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    t1 = generator.generate(out1, seed=7, as_of=date(2026, 9, 21))
    t2 = generator.generate(out2, seed=7, as_of=date(2026, 9, 21))
    assert t1 == t2
    for table in schema.ALL_TABLES:
        assert (out1 / table.filename).read_text() == (out2 / table.filename).read_text()


def test_different_seed_changes_output(tmp_path):
    t1 = generator.generate(tmp_path / "a", seed=7, as_of=date(2026, 9, 21))
    t2 = generator.generate(tmp_path / "b", seed=8, as_of=date(2026, 9, 21))
    assert t1 != t2


def test_all_five_csvs_written_with_correct_headers(data_dir):
    for table in schema.ALL_TABLES:
        path = data_dir / table.filename
        assert path.exists()
        with path.open() as f:
            header = next(csv.reader(f))
        assert header == table.columns


def test_csvs_are_non_trivial(data_dir):
    tasks = csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)
    weekly_updates = csv_io.read_rows(data_dir / schema.WEEKLY_UPDATES.filename, schema.WEEKLY_UPDATES)
    blockers = csv_io.read_rows(data_dir / schema.BLOCKERS.filename, schema.BLOCKERS)
    kpi_targets = csv_io.read_rows(data_dir / schema.KPI_TARGETS.filename, schema.KPI_TARGETS)
    assert len(tasks) > 50
    assert len(weekly_updates) == len(TEAM_NAMES) * 4 * 8  # 4 members/team, 8 weeks
    assert len(blockers) > 0
    assert len(kpi_targets) == len(TEAM_NAMES) * 8


def test_every_task_team_is_registered(data_dir):
    tasks = csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)
    for row in tasks:
        assert row["team"] in TEAM_NAMES


def test_every_blocker_references_a_real_task(data_dir):
    tasks = csv_io.read_rows(data_dir / schema.TASKS.filename, schema.TASKS)
    blockers = csv_io.read_rows(data_dir / schema.BLOCKERS.filename, schema.BLOCKERS)
    task_ids = {r["task_id"] for r in tasks}
    for row in blockers:
        assert row["task_id"] in task_ids


def test_only_fictional_team_names_used():
    assert "Team Aurora" in TEAM_NAMES
    assert "Team Birch" in TEAM_NAMES
    for name in TEAM_NAMES:
        assert name.startswith("Team ")
