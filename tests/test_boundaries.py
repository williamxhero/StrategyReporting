from __future__ import annotations

from pathlib import Path


def test_production_source_has_no_private_or_upstream_internal_imports() -> None:
    root = Path(__file__).parents[1] / "src" / "strategy_reporting"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    forbidden = (
        "strategy_workspace.storage",
        "strategy_workspace.core",
        "sqlite3",
        "from quant_runtime",
        "import quant_runtime",
        "from apex_research",
        "import apex_research",
        "AnalysisBundle",
        "PerformanceMetrics",
        "calculate_performance_metrics",
        "regenerate_report_from_output_dir",
        "parse_legacy_margin_log",
        "analyze_result_directory",
        "apex_backtest",
        "apex-backtest",
        "output-dir",
        "legacy marker",
        "log parser",
        "legacy parser",
    )
    assert all(item not in source for item in forbidden)


def test_runtime_and_apex_are_never_invoked() -> None:
    root = Path(__file__).parents[1] / "src" / "strategy_reporting"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "subprocess" not in source
    assert "quant-runtime " not in source
    assert "apex-research report" not in source


def test_presentation_owns_neither_control_plane_nor_formal_truth() -> None:
    root = Path(__file__).parents[1] / "src" / "strategy_reporting"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py")).lower()
    forbidden = (
        "workspace.sqlite3",
        "strategy_workspace.storage",
        "strategy_workspace.core",
        "import quant_runtime",
        "from quant_runtime",
        "import apex_research",
        "from apex_research",
        "quant-runtime run",
        "apex-research study",
    )
    assert all(item not in source for item in forbidden)
