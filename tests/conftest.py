from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from team_dashboard import generator  # noqa: E402

SEED = 7
AS_OF = date(2026, 9, 21)


@pytest.fixture(scope="session")
def generated(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("data")
    known_totals = generator.generate(out_dir, seed=SEED, as_of=AS_OF)
    return out_dir, known_totals


@pytest.fixture
def data_dir(generated):
    return generated[0]


@pytest.fixture
def known_totals(generated):
    return generated[1]
