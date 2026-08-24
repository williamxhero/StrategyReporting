from __future__ import annotations

import json

import pytest
from conftest import FakeWorkspace, add_apex_source, add_formal_run

from strategy_reporting.application import ReportingApplication
from strategy_reporting.errors import ContractError
from strategy_reporting.models import ReportOptions
from strategy_reporting.portal import PortalBuilder
from strategy_reporting.portal.index import _formal_roles, _package_groups


def test_portal_groups_and_materializes_reports(workspace: FakeWorkspace, tmp_path) -> None:
    app = ReportingApplication(workspace)
    formal = app.render_report("formal-run", add_formal_run(workspace), ReportOptions())
    research = app.render_report("research-study", add_apex_source(workspace), ReportOptions())
    research_history = app.render_report(
        "research-study", add_apex_source(workspace, study_id="9" * 64), ReportOptions()
    )
    result = PortalBuilder(app.workspace).build(tmp_path / "portal")
    assert result["report_count"] == 3
    model = json.loads(
        (tmp_path / "portal" / "strategy-report-index.json").read_text(encoding="utf-8")
    )
    assert {item["report_kind"] for item in model["reports"]} == {"formal-run", "research-study"}
    assert len(model["packages"]) == 2
    research_package = next(
        item for item in model["packages"] if item["latest_research"] is not None
    )
    formal_package = next(
        item for item in model["packages"] if item["formal_runs"]["baseline_reference"]
    )
    assert len(research_package["research_history"]) == 1
    assert formal_package["formal_runs"]["baseline_reference"][0]["report_id"] == (
        formal.envelope.report_id
    )
    assert formal_package["formal_runs"]["challenge_window"] == []
    assert formal_package["formal_runs"]["parameter_config_variants"] == []
    assert research_package["discovery_availability"]["status"] == "not_evaluated"
    assert (tmp_path / "portal" / "reports" / formal.envelope.report_id / "index.html").is_file()
    assert (tmp_path / "portal" / "reports" / research.envelope.report_id / "index.html").is_file()
    assert (
        tmp_path / "portal" / "reports" / research_history.envelope.report_id / "index.html"
    ).is_file()
    index = (tmp_path / "portal" / "index.html").read_text(encoding="utf-8")
    assert "https://" not in index and "http://" not in index
    assert "最新 Research Study Report" in index
    assert "历史 Research Study Reports" in index
    assert "Challenge window" in index
    assert "Discovery availability" in index


def test_empty_portal_is_valid(workspace: FakeWorkspace, tmp_path) -> None:
    result = PortalBuilder(ReportingApplication(workspace).workspace).build(tmp_path)
    assert result["report_count"] == 0
    assert "当前没有已发布报告" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_portal_hard_cap_fails_closed(workspace: FakeWorkspace, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workspace, "list_records", lambda **kwargs: [{}] * 10_000)
    with pytest.raises(ContractError, match="hard cap"):
        PortalBuilder(ReportingApplication(workspace).workspace).build(tmp_path)


def test_portal_rejects_materialized_content_identity_mismatch(
    workspace: FakeWorkspace, tmp_path, monkeypatch
) -> None:
    app = ReportingApplication(workspace)
    app.render_report("formal-run", add_formal_run(workspace), ReportOptions())
    original = workspace.materialize_artifact

    def mismatched(uri, destination):
        result = original(uri, destination)
        result["artifact"] = {**result["artifact"], "bytes": result["artifact"]["bytes"] + 1}
        return result

    monkeypatch.setattr(workspace, "materialize_artifact", mismatched)
    with pytest.raises(ContractError, match="identity differs"):
        PortalBuilder(app.workspace).build(tmp_path / "portal")


def test_formal_roles_are_derived_from_latest_research_trial_structure() -> None:
    trials = [
        {
            "workspace_run_id": "baseline",
            "snapshot_window": {"start": "2026-01-01", "end": "2026-01-31"},
            "parameters": {"lookback": 20},
            "formal_legs": [
                {
                    "formal_id": "primary",
                    "adapter": "nautilus",
                    "config": {"fee": "base"},
                    "result_identity": "a" * 64,
                    "metrics": {"score": 1.0},
                }
            ],
        },
        {
            "workspace_run_id": "challenge",
            "snapshot_window": {"start": "2025-01-01", "end": "2025-12-31"},
            "parameters": {"lookback": 20},
            "formal_legs": [
                {
                    "formal_id": "primary",
                    "adapter": "nautilus",
                    "config": {"fee": "base"},
                    "result_identity": "b" * 64,
                    "metrics": {"score": 0.5},
                }
            ],
        },
        {
            "workspace_run_id": "variant",
            "snapshot_window": {"start": "2026-01-01", "end": "2026-01-31"},
            "parameters": {"lookback": 40},
            "formal_legs": [
                {
                    "formal_id": "primary",
                    "adapter": "nautilus",
                    "config": {"fee": "base"},
                    "result_identity": "c" * 64,
                    "metrics": {"score": 1.1},
                }
            ],
        },
        {
            "workspace_run_id": "same-config-rerun",
            "snapshot_window": {"start": "2026-01-01", "end": "2026-01-31"},
            "parameters": {"lookback": 20},
            "formal_legs": [
                {
                    "formal_id": "primary",
                    "adapter": "nautilus",
                    "config": {"fee": "base"},
                    "result_identity": "d" * 64,
                    "metrics": {"score": -1.0},
                }
            ],
        },
    ]
    assert _formal_roles(trials) == {
        "baseline": "baseline_reference",
        "challenge": "challenge_window",
        "variant": "parameter_config_variants",
        "same-config-rerun": "baseline_reference",
    }


def test_portal_merges_historical_roles_and_latest_wins_conflicts() -> None:
    package = {"strategy_id": "s", "revision": 1, "package_hash": "p"}
    baseline = {
        "workspace_run_id": "baseline",
        "snapshot_window": {"window": "base"},
        "parameters": {"lookback": 20},
        "formal_legs": [{"formal_id": "f", "adapter": "n", "config": {}}],
    }
    entries = [
        {
            "report_id": "latest",
            "report_kind": "research-study",
            "created_at": "2026-02-01T00:00:00Z",
            "_package": package,
            "_trials": [
                baseline,
                {**baseline, "workspace_run_id": "shared"},
            ],
            "_discovery": {"status": "not_evaluated", "items": [], "reason": "none"},
        },
        {
            "report_id": "history",
            "report_kind": "research-study",
            "created_at": "2026-01-01T00:00:00Z",
            "_package": package,
            "_trials": [
                baseline,
                {
                    **baseline,
                    "workspace_run_id": "historical-challenge",
                    "snapshot_window": {"window": "challenge"},
                },
                {
                    **baseline,
                    "workspace_run_id": "shared",
                    "snapshot_window": {"window": "challenge"},
                },
            ],
            "_discovery": {"status": "not_evaluated", "items": [], "reason": "none"},
        },
        {
            "report_id": "formal-history",
            "report_kind": "formal-run",
            "created_at": "2026-01-02T00:00:00Z",
            "_package": package,
            "_workspace_run_id": "historical-challenge",
        },
        {
            "report_id": "formal-shared",
            "report_kind": "formal-run",
            "created_at": "2026-02-02T00:00:00Z",
            "_package": package,
            "_workspace_run_id": "shared",
        },
    ]
    group = _package_groups(entries)[0]
    assert [item["report_id"] for item in group["formal_runs"]["challenge_window"]] == [
        "formal-history"
    ]
    assert [item["report_id"] for item in group["formal_runs"]["baseline_reference"]] == [
        "formal-shared"
    ]


def test_portal_shows_only_latest_renderer_for_same_workspace_run() -> None:
    package = {"strategy_id": "s", "revision": 1, "package_hash": "p"}
    entries = [
        {
            "report_id": "latest-renderer",
            "report_kind": "formal-run",
            "created_at": "2026-02-01T00:00:00Z",
            "_package": package,
            "_workspace_run_id": "same-run",
        },
        {
            "report_id": "older-renderer",
            "report_kind": "formal-run",
            "created_at": "2026-01-01T00:00:00Z",
            "_package": package,
            "_workspace_run_id": "same-run",
        },
    ]
    group = _package_groups(entries)[0]
    assert [item["report_id"] for item in group["formal_runs"]["baseline_reference"]] == [
        "latest-renderer"
    ]
