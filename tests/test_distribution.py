from __future__ import annotations

import subprocess
from importlib.resources import files
from pathlib import Path
from zipfile import ZipFile


def test_wheel_accepts_workspace_02_public_contract(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    output = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(output.glob("strategy_reporting-0.1.0-*.whl"))
    with ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode()
    assert "Requires-Dist: strategy-workspace<0.3,>=0.1.0" in metadata


def test_templates_and_assets_are_packaged() -> None:
    html = files("strategy_reporting.html")
    assert html.joinpath("templates/formal.html.j2").is_file()
    assert html.joinpath("templates/research.html.j2").is_file()
    assert html.joinpath("static/report.css").is_file()


def test_public_surface_is_deep_and_small() -> None:
    import strategy_reporting

    assert strategy_reporting.__all__ == ["ReportOptions", "ReportPublication", "render_report"]
