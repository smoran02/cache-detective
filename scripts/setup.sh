#!/usr/bin/env bash
# One command: create .venv and install requirements. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required (set PYTHON=/path/to/python3.x)")'

"$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

echo "Ready. Next: .venv/bin/python app.py"
