#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
PYTHONPATH=src python3 -m credit_card_dashboard serve-ui --host 127.0.0.1 --port 8010
