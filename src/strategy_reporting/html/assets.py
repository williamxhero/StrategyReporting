from __future__ import annotations

from importlib.resources import files


def stylesheet() -> str:
    return (
        files("strategy_reporting.html").joinpath("static/report.css").read_text(encoding="utf-8")
    )
