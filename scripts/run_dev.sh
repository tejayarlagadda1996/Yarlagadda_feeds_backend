#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d .venv ]]; then
  echo "Create venv with: python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
exec .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
