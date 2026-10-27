#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Instale Python 3.10+ com suporte a venv e pip.'
  exit 1
fi
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if [ ! -f .venv/.synapse-ready ]; then
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.synapse-ready
fi
exec .venv/bin/python run.py "$@"
