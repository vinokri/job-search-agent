from __future__ import annotations

import argparse
from pathlib import Path

from .orchestration import DashboardOrchestrator, DashboardStore, build_default_paths
from .web import serve_ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Credit card dashboard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh", help="Refresh account summary and reminders.")
    refresh_parser.set_defaults(command="refresh")

    serve_parser = subparsers.add_parser("serve-ui", help="Run the local dashboard UI.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8010)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    orchestrator = DashboardOrchestrator(DashboardStore(build_default_paths(Path(__file__).resolve().parents[2])))
    if args.command == "refresh":
        orchestrator.refresh()
        return
    if args.command == "serve-ui":
        serve_ui(args.host, args.port)
        return
