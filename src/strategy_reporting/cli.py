from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from pydantic import ValidationError

from strategy_reporting.application import application_for_workspace
from strategy_reporting.errors import ReportingError
from strategy_reporting.models import ReportOptions
from strategy_reporting.portal import PortalBuilder


class CliUsageError(Exception):
    pass


class StrictParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        raise CliUsageError(message or f"parser requested exit {status}")


def parser() -> StrictParser:
    value = StrictParser(prog="strategy-reporting", add_help=False)
    value.add_argument("--workspace", type=Path)
    value.add_argument("--help", action="store_true")
    commands = value.add_subparsers(dest="command", required=True, parser_class=StrictParser)

    render_run = commands.add_parser("render-run", add_help=False)
    render_run.add_argument("--run-id", required=True)
    render_run.add_argument("--formal-id")
    _render_options(render_run)

    render_study = commands.add_parser("render-study", add_help=False)
    render_study.add_argument("--study-id", required=True)
    render_study.add_argument("--decision-id")
    _render_options(render_study)

    for name in ("inspect", "verify", "rebuild"):
        command = commands.add_parser(name, add_help=False)
        command.add_argument("--report-id", required=True)

    portal = commands.add_parser("portal", add_help=False)
    portal_commands = portal.add_subparsers(
        dest="portal_command", required=True, parser_class=StrictParser
    )
    build = portal_commands.add_parser("build", add_help=False)
    build.add_argument("--strategy-id")
    build.add_argument("--output", required=True, type=Path)
    return value


def _render_options(value: argparse.ArgumentParser) -> None:
    value.add_argument("--theme", choices=("paper", "dark"), default="paper")
    value.add_argument("--detail-row-limit", type=int, default=100)
    value.add_argument("--max-model-bytes", type=int, default=2_000_000)
    value.add_argument("--max-html-bytes", type=int, default=12_000_000)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(list(argv) if argv is not None else None)
        if args.help:
            raise CliUsageError(
                "use one of render-run, render-study, inspect, verify, rebuild, portal build"
            )
        workspace_root = args.workspace or _environment_workspace()
        app = application_for_workspace(workspace_root)
        if args.command == "render-run":
            options = _options(args, workspace_root, formal_id=args.formal_id)
            result: Any = app.render_report("formal-run", args.run_id, options)
        elif args.command == "render-study":
            options = _options(args, workspace_root, decision_id=args.decision_id)
            result = app.render_report("research-study", args.study_id, options)
        elif args.command == "inspect":
            result = app.inspect(args.report_id)
        elif args.command == "verify":
            result = app.verify(args.report_id)
        elif args.command == "rebuild":
            result = app.rebuild(args.report_id)
        elif args.command == "portal" and args.portal_command == "build":
            result = PortalBuilder(app.workspace).build(args.output, strategy_id=args.strategy_id)
        else:
            raise CliUsageError("unknown command")
        _emit({"ok": True, "result": _json_value(result)})
        return 0
    except CliUsageError as exc:
        _emit_error("cli_usage", str(exc), 2)
        return 2
    except (ValidationError, ValueError) as exc:
        _emit_error("invalid_option", str(exc), 2)
        return 2
    except ReportingError as exc:
        exit_code = {"source": 3, "contract": 4, "render": 5, "publication": 6}[exc.category]
        _emit_error(exc.code, exc.message, exit_code, exc.details)
        return exit_code
    except Exception as exc:
        print(f"unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        _emit_error("internal_error", "unexpected internal error", 4)
        return 4


def _options(
    args: argparse.Namespace,
    workspace_root: Path | None,
    *,
    formal_id: str | None = None,
    decision_id: str | None = None,
) -> ReportOptions:
    return ReportOptions(
        workspace_root=workspace_root,
        formal_id=formal_id,
        decision_id=decision_id,
        theme=args.theme,
        detail_row_limit=args.detail_row_limit,
        max_model_bytes=args.max_model_bytes,
        max_html_bytes=args.max_html_bytes,
    )


def _environment_workspace() -> Path | None:
    value = os.environ.get("STRATEGY_WORKSPACE_ROOT")
    return Path(value) if value else None


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _emit(value: dict[str, Any]) -> None:
    print(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
    )


def _emit_error(
    code: str,
    message: str,
    exit_code: int,
    details: dict[str, object] | None = None,
) -> None:
    _emit(
        {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
            "exit_code": exit_code,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
