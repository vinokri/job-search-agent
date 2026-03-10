#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

export PYTHONPATH=src

python3 -m job_agent serve-ui --host "$HOST" --port "$PORT"
