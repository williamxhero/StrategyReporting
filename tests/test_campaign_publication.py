from __future__ import annotations

import json

import pytest
from campaign_fixtures import (
    CAMPAIGN_ID,
    evidence_lane_campaign_source,
    publish_campaign_source,
    scenario_campaign_source,
)
from conftest import FakeWorkspace

from strategy_reporting.application import ReportingApplication
from strategy_reporting.errors import ReportingError
from strategy_reporting.models import ReportOptions
from strategy_reporting.portal import PortalBuilder


def _workspace_with_campaign(workspace: FakeWorkspace) -> str:
    source = evidence_lane_campaign_source()
    workspace.runs["run-formal-1"] = {
        "schema": "quant-research.run-record.v1",
        "run_id": "run-formal-1",
    }
    publish_campaign_source(workspace, source)
    return source["source_id"]


def test_campaign_publish_is_atomic_immutable_and_replay_idempotent(
    workspace: FakeWorkspace,
) -> None:
    source_id = _workspace_with_campaign(workspace)
    app = ReportingApplication(workspace)

    first = app.render_report("campaign", CAMPAIGN_ID, ReportOptions())
    publish_calls = workspace.publish_calls
    second = app.render_report("campaign", CAMPAIGN_ID, ReportOptions())

    assert first.envelope.report_id == second.envelope.report_id
    assert workspace.publish_calls == publish_calls == 1
    descriptor = workspace.records[first.envelope.report_id]
    assert descriptor["payload"]["identity"]["source_identities"][0] == source_id
    assert {item["logical_role"] for item in descriptor["artifacts"]} == {
        "report-model",
        "report-html",
    }
    assert app.verify(first.envelope.report_id) == first
    rebuilt = app.rebuild(first.envelope.report_id)
    assert rebuilt["rebuilt_content_hashes"] == descriptor["payload"]["expected_content_hashes"]


def test_campaign_verify_rejects_tamper_and_meaning_changes_create_new_identity(
    workspace: FakeWorkspace,
) -> None:
    first_source_id = _workspace_with_campaign(workspace)
    app = ReportingApplication(workspace)
    first = app.render_report("campaign", CAMPAIGN_ID, ReportOptions())

    changed_source = scenario_campaign_source("retired")
    publish_campaign_source(workspace, changed_source)
    changed = app.render_report(
        "campaign",
        CAMPAIGN_ID,
        ReportOptions(campaign_source_id=changed_source["source_id"]),
    )
    changed_render = app.render_report(
        "campaign",
        CAMPAIGN_ID,
        ReportOptions(campaign_source_id=first_source_id, detail_row_limit=1),
    )
    assert (
        len(
            {
                first.envelope.report_id,
                changed.envelope.report_id,
                changed_render.envelope.report_id,
            }
        )
        == 3
    )

    model_ref = next(
        item for item in first.envelope.artifacts if item.logical_role == "report-model"
    )
    workspace.contents[model_ref.sha256] += b"tampered"
    with pytest.raises(ReportingError, match=r"artifact|hash"):
        app.verify(first.envelope.report_id)


def test_campaign_portal_materializes_and_deduplicates_immutable_reports(
    workspace: FakeWorkspace, tmp_path
) -> None:
    _workspace_with_campaign(workspace)
    app = ReportingApplication(workspace)
    first = app.render_report("campaign", CAMPAIGN_ID, ReportOptions())
    app.render_report("campaign", CAMPAIGN_ID, ReportOptions())

    result = PortalBuilder(app.workspace).build(tmp_path / "portal")
    first_index = (tmp_path / "portal" / "index.html").read_bytes()
    first_model = (tmp_path / "portal" / "strategy-report-index.json").read_bytes()
    replay = PortalBuilder(app.workspace).build(tmp_path / "portal")

    assert result["report_count"] == 1
    assert replay == result
    assert (tmp_path / "portal" / "index.html").read_bytes() == first_index
    assert (tmp_path / "portal" / "strategy-report-index.json").read_bytes() == first_model
    portal_model = json.loads((tmp_path / "portal" / "strategy-report-index.json").read_text())
    assert [item["report_id"] for item in portal_model["campaigns"]] == [first.envelope.report_id]
    assert (tmp_path / "portal" / "reports" / first.envelope.report_id / "index.html").is_file()
    assert "AI Research Campaigns" in (tmp_path / "portal" / "index.html").read_text(
        encoding="utf-8"
    )
