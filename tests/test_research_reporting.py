from __future__ import annotations

import json

import pytest
from conftest import FakeWorkspace, add_apex_source, add_formal_run

from strategy_reporting.application import ReportingApplication
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import ReportOptions


def test_research_report_without_discovery_is_valid(workspace: FakeWorkspace) -> None:
    study_id = add_apex_source(workspace, discovery=False)
    app = ReportingApplication(workspace)
    report = app.render_report("research-study", study_id, ReportOptions())
    assert report.envelope.report_kind == "research-study"
    assert len(report.envelope.artifacts) == 2
    assert app.rebuild(report.envelope.report_id)["ok"] is True
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = workspace.contents[model_ref.sha256].decode("utf-8")
    assert (
        '"discovery":{"items":[],"reason":"no published evidence","status":"not_evaluated"}'
        in model
    )
    assert '"status":"not_rendered"' in model


def test_research_report_maps_discovery_when_present(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "research-study", add_apex_source(workspace, discovery=True), ReportOptions()
    )
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    assert '"discovery":{"items":["' in workspace.contents[model_ref.sha256].decode("utf-8")


def test_research_html_is_a_human_decision_report_without_raw_payload_dumps(
    workspace: FakeWorkspace,
) -> None:
    report = ReportingApplication(workspace).render_report(
        "research-study", add_apex_source(workspace), ReportOptions()
    )
    html_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-html"
    )
    page = workspace.contents[html_ref.sha256].decode("utf-8")
    assert "结论的含义" in page
    assert "accept 不可以说明什么" in page
    assert "1 项冻结门槛" in page
    assert "<pre" not in page
    assert '"formal_legs"' not in page


def test_research_model_carries_verified_formal_report_context(
    workspace: FakeWorkspace,
) -> None:
    run_id = add_formal_run(workspace, run_id="run_apex_1")
    app = ReportingApplication(workspace)
    formal = app.render_report("formal-run", run_id, ReportOptions())
    research = app.render_report("research-study", add_apex_source(workspace), ReportOptions())
    model_ref = next(
        item for item in research.envelope.artifacts if item.logical_role == "report-model"
    )
    model = workspace.contents[model_ref.sha256].decode("utf-8")
    assert formal.envelope.report_id in model
    assert '"snapshot_verification":"verified"' in model


def test_research_report_prefers_latest_renderer_for_one_formal_leg(
    workspace: FakeWorkspace,
) -> None:
    app = ReportingApplication(workspace)
    run_id = "run_apex_1"
    app.render_report("formal-run", add_formal_run(workspace, run_id=run_id), ReportOptions())
    workspace.created_at = "2026-08-24T01:02:04Z"
    app.renderers._formal.renderer_version += "+new"
    latest = app.render_report("formal-run", run_id, ReportOptions())
    report = app.render_report("research-study", add_apex_source(workspace), ReportOptions())
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = json.loads(workspace.contents[model_ref.sha256])
    links = model["related_formal_reports"]
    assert len(links) == 1
    assert links[0]["workspace_run_id"] == run_id
    assert links[0]["status"] == "rendered"
    assert links[0]["report_ids"] == [latest.envelope.report_id]


def test_missing_apex_source_never_falls_back_to_markdown(workspace: FakeWorkspace) -> None:
    workspace.records["markdown"] = {
        "schema": "quant-research.publication.v1",
        "record_id": "markdown",
        "record_type": "apex-research.report.v1",
        "created_at": "2026-01-01T00:00:00Z",
        "payload": {"study_id": "1" * 64, "content": "# report"},
        "artifacts": [],
        "lineage": [],
    }
    with pytest.raises(SourceError, match="Markdown fallback is forbidden"):
        ReportingApplication(workspace).render_report("research-study", "1" * 64, ReportOptions())


def test_apex_source_identity_drift_fails_closed(workspace: FakeWorkspace) -> None:
    add_apex_source(workspace)
    source = next(
        item
        for item in workspace.records.values()
        if item["record_type"] == "apex-research.study-report-source.v1"
    )
    source["payload"]["research_metrics"]["accepted"] = False
    with pytest.raises(ContractError, match="source_id"):
        ReportingApplication(workspace).render_report("research-study", "1" * 64, ReportOptions())


def test_decision_selector_is_exact(workspace: FakeWorkspace) -> None:
    study_id = add_apex_source(workspace)
    with pytest.raises(SourceError, match="expected one source"):
        ReportingApplication(workspace).render_report(
            "research-study", study_id, ReportOptions(decision_id="f" * 64)
        )


def test_apex_source_publication_lineage_tamper_fails_closed(workspace: FakeWorkspace) -> None:
    study_id = add_apex_source(workspace)
    source = next(
        item
        for item in workspace.records.values()
        if item["record_type"] == "apex-research.study-report-source.v1"
    )
    source["lineage"] = []
    with pytest.raises(ContractError, match="top-level lineage"):
        ReportingApplication(workspace).render_report("research-study", study_id, ReportOptions())


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("protocol_record_id", "unknown-protocol", "unknown protocol"),
        ("trial_record_id", "unknown-trial", "unknown trial"),
        ("gate_record_ids", ["unknown-gate"], "unknown gate"),
        ("workspace_run_ids", ["unknown-run"], "unknown Workspace run"),
    ],
)
def test_apex_evidence_reference_closure_fails_even_with_recomputed_source_id(
    workspace: FakeWorkspace, field, replacement, message
) -> None:
    study_id = add_apex_source(workspace)
    source = next(
        item
        for item in workspace.records.values()
        if item["record_type"] == "apex-research.study-report-source.v1"
    )
    old_id = source["record_id"]
    source["payload"]["evidence"][0][field] = replacement
    source_id = canonical_sha256(
        {key: value for key, value in source["payload"].items() if key != "source_id"}
    )
    source["payload"]["source_id"] = source_id
    source["record_id"] = source_id
    workspace.records.pop(old_id)
    workspace.records[source_id] = source
    with pytest.raises(ContractError, match=message):
        ReportingApplication(workspace).render_report("research-study", study_id, ReportOptions())


def test_apex_source_and_formal_link_lists_fail_at_hard_cap(
    workspace: FakeWorkspace, monkeypatch
) -> None:
    original = workspace.list_records
    monkeypatch.setattr(workspace, "list_records", lambda **kwargs: [{}] * 10_000)
    with pytest.raises(ContractError, match="Apex source list reached"):
        ReportingApplication(workspace).render_report("research-study", "1" * 64, ReportOptions())

    workspace = FakeWorkspace()
    study_id = add_apex_source(workspace)

    def capped_formal_links(*, record_type=None, limit=100):
        if record_type == "strategy-reporting.report-descriptor.v1":
            return [{}] * 10_000
        return original(record_type=record_type, limit=limit)

    original = workspace.list_records
    monkeypatch.setattr(workspace, "list_records", capped_formal_links)
    with pytest.raises(ContractError, match="formal report list reached"):
        ReportingApplication(workspace).render_report("research-study", study_id, ReportOptions())


def test_apex_embedded_sources_must_match_exact_ordered_source_refs(
    workspace: FakeWorkspace,
) -> None:
    study_id = add_apex_source(workspace)
    source = next(
        item
        for item in workspace.records.values()
        if item["record_type"] == "apex-research.study-report-source.v1"
    )
    old_id = source["record_id"]
    source["payload"] = json.loads(json.dumps(source["payload"]))
    forged_record_id = source["payload"]["gate_results"][0]["source"]["record_id"]
    source["payload"]["trials"][0]["source"]["record_id"] = forged_record_id
    source["payload"]["evidence"][0]["trial_record_id"] = forged_record_id
    source_id = canonical_sha256(
        {key: value for key, value in source["payload"].items() if key != "source_id"}
    )
    source["payload"]["source_id"] = source_id
    source["record_id"] = source_id
    workspace.records.pop(old_id)
    workspace.records[source_id] = source
    with pytest.raises(ContractError, match="source refs do not match"):
        ReportingApplication(workspace).render_report("research-study", study_id, ReportOptions())
