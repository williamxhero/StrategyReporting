from __future__ import annotations

from importlib.resources import files


def test_templates_and_assets_are_packaged() -> None:
    html = files("strategy_reporting.html")
    assert html.joinpath("templates/formal.html.j2").is_file()
    assert html.joinpath("templates/research.html.j2").is_file()
    assert html.joinpath("static/report.css").is_file()


def test_public_surface_is_deep_and_small() -> None:
    import strategy_reporting

    assert strategy_reporting.__all__ == ["ReportOptions", "ReportPublication", "render_report"]
