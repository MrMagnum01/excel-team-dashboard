#!/usr/bin/env bash
# One-command demo run: generate synthetic data, build a sample filled-in
# member input workbook (with deliberately bad rows), sync it, then build
# the master + team dashboards. Everything under library/ is generated;
# it's git-ignored.
set -euo pipefail
cd "$(dirname "$0")"

export PYTHONPATH=src

python3 -m team_dashboard generate \
    --out library/data --seed 7 --as-of 2026-09-21

python3 -m team_dashboard input \
    --out library/input-workbook-template.xlsx

python3 -m team_dashboard sample-inbox \
    --out library/inbox/priya-submission.xlsx \
    --data library/data --as-of 2026-09-21

python3 -m team_dashboard sync \
    --inbox library/inbox --data library/data \
    --exceptions library/exceptions_report.csv

python3 -m team_dashboard refresh \
    --data library/data --out library/dashboards --as-of 2026-09-21

echo
echo "Done. See:"
echo "  library/data/                 - the five CSV tables + known_totals.json"
echo "  library/exceptions_report.csv - rejected rows from the sample sync"
echo "  library/dashboards/           - master-dashboard.xlsx + one per team"
