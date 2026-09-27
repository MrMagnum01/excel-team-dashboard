"""Subprocess smoke tests of the CLI itself, end to end through `run_demo.sh`'s
four steps: generate -> input -> sample-inbox -> sync -> refresh."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "team_dashboard", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60,
    )


def test_generate_cli(tmp_path):
    result = _run(["generate", "--out", str(tmp_path / "data"), "--seed", "7", "--as-of", "2026-09-21"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "data" / "tasks.csv").exists()
    assert (tmp_path / "data" / "known_totals.json").exists()


def test_input_cli(tmp_path):
    result = _run(["input", "--out", str(tmp_path / "input.xlsx")], tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "input.xlsx").exists()


def test_full_pipeline_cli(tmp_path):
    data_dir = tmp_path / "data"
    r1 = _run(["generate", "--out", str(data_dir), "--seed", "7", "--as-of", "2026-09-21"], tmp_path)
    assert r1.returncode == 0, r1.stderr

    r2 = _run(
        ["sample-inbox", "--out", str(tmp_path / "inbox" / "priya.xlsx"), "--data", str(data_dir), "--as-of", "2026-09-21"],
        tmp_path,
    )
    assert r2.returncode == 0, r2.stderr

    r3 = _run(
        ["sync", "--inbox", str(tmp_path / "inbox"), "--data", str(data_dir), "--exceptions", str(tmp_path / "exceptions.csv")],
        tmp_path,
    )
    assert r3.returncode == 0, r3.stderr
    summary = json.loads(r3.stdout)
    assert summary["exceptions"] == 8

    r4 = _run(
        ["refresh", "--data", str(data_dir), "--out", str(tmp_path / "dashboards"), "--as-of", "2026-09-21"],
        tmp_path,
    )
    assert r4.returncode == 0, r4.stderr
    assert (tmp_path / "dashboards" / "master-dashboard.xlsx").exists()
    assert (tmp_path / "dashboards" / "team-aurora-dashboard.xlsx").exists()


def test_cli_with_no_subcommand_errors_cleanly(tmp_path):
    result = _run([], tmp_path)
    assert result.returncode != 0
