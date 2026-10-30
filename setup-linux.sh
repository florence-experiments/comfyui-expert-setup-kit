#!/usr/bin/env bash
# Built by Florence for the community.
# ComfyUI Expert Setup Kit - Linux. Run:  bash setup-linux.sh   (no sudo needed)
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 is needed. Install it first, e.g.: sudo apt install python3 python3-venv"
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or newer is needed (found $("$PY" --version 2>&1))."
  exit 1
fi
export PYTHONPATH="$PWD/kit"
exec "$PY" -m cesetup.main "$@"
