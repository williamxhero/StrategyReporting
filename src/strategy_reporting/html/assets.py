from __future__ import annotations

from importlib.resources import files


def stylesheet() -> str:
    return (
        files("strategy_reporting.html").joinpath("static/report.css").read_text(encoding="utf-8")
    )


def research_stylesheet() -> str:
    research = (
        files("strategy_reporting.html").joinpath("static/research.css").read_text(encoding="utf-8")
    )
    return f"{stylesheet()}\n{research}"
