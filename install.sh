#!/usr/bin/env sh
set -eu

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3.11+ is required to run the installer." >&2
  exit 1
fi

"$PY" installer/main.py "$@"
