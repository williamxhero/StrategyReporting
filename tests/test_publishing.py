from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from conftest import FakeWorkspace, FakeWorkspaceError, add_apex_source, add_formal_run

from strategy_reporting.adapters import WorkspaceAdapter, WorkspaceFormalRunAdapter
from strategy_reporting.application import ReportingApplication
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.errors import ContractError
from strategy_reporting.models import ReportOptions
from strategy_reporting.publishing import WorkspaceReportPublisher
from strategy_reporting.renderers import RendererRegistry


def test_renderer_version_changes_report_identity(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace)
    adapter = WorkspaceFormalRunAdapter(WorkspaceAdapter(workspace))
    model = adapter.build_model(run_id, ReportOptions())
    bundle = RendererRegistry().resolve(model).render(model, ReportOptions())
    publisher = WorkspaceReportPublisher(WorkspaceAdapter(workspace))
    first = publisher.publish(bundle)
    changed = publisher.publish(replace(bundle, renderer_version=bundle.renderer_version + ".next"))
    assert first.envelope.report_id != changed.envelope.report_id


def test_existing_descriptor_conflict_fails_closed(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace)
    adapter = WorkspaceFormalRunAdapter(WorkspaceAdapter(workspace))
    model = adapter.build_model(run_id, ReportOptions())
    bundle = RendererRegistry().resolve(model).render(model, ReportOptions())
    publisher = WorkspaceReportPublisher(WorkspaceAdapter(workspace))
    report = publisher.publish(bundle)
    workspace.records[report.envelope.report_id]["payload"]["title"] = "changed"
    with pytest.raises(ContractError, match="descriptor differs"):
        publisher.publish(bundle)


def test_publication_race_reloads_and_validates_winner(
    workspace: FakeWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = add_formal_run(workspace)
    model = WorkspaceFormalRunAdapter(WorkspaceAdapter(workspace)).build_model(
        run_id, ReportOptions()
    )
    bundle = RendererRegistry().resolve(model).render(model, ReportOptions())
    original_publish = workspace.publish_record

    def competing_publish(record, *, artifacts=()):
        original_publish(record, artifacts=artifacts)
        raise FakeWorkspaceError("record_conflict", record["record_id"])

    monkeypatch.setattr(workspace, "publish_record", competing_publish)
    publication = WorkspaceReportPublisher(WorkspaceAdapter(workspace)).publish(bundle)

    assert publication.envelope.report_id in workspace.records
    assert workspace.publish_calls == 1


def test_publication_lineage_covers_required_formal_sources(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    kinds = {item.source_kind for item in report.envelope.lineage}
    assert {
        "workspace-run",
        "workspace-attempt",
        "strategy-package",
        "market-snapshot",
        "workspace-artifact",
    } <= kinds


@pytest.mark.parametrize(
    "field",
    ["subject_id", "title", "report_kind", "payload_schema", "identity.subject"],
)
def test_verify_binds_descriptor_claims_to_persisted_model(
    workspace: FakeWorkspace, field: str
) -> None:
    app = ReportingApplication(workspace)
    report = app.render_report("formal-run", add_formal_run(workspace), ReportOptions())
    original_id = report.envelope.report_id
    publication = copy.deepcopy(workspace.records.pop(original_id))
    payload = publication["payload"]
    if field == "subject_id":
        payload["subject_id"] = "workspace-run:forged#attempt:forged#formal:forged"
    elif field == "title":
        payload["title"] = "forged but structurally valid title"
    elif field == "report_kind":
        payload["report_kind"] = "research-study"
        payload["identity"]["report_kind"] = "research-study"
    elif field == "payload_schema":
        payload["payload_schema"] = "strategy-reporting.research-study-report.v1"
    else:
        payload["identity"]["subject"]["workspace_run_id"] = "forged"
    forged_id = "report_" + canonical_sha256(payload["identity"])
    payload["report_id"] = forged_id
    publication["record_id"] = forged_id
    workspace.records[forged_id] = publication

    with pytest.raises(ContractError, match="descriptor claims differ"):
        app.verify(forged_id)


def test_rebuild_never_reenters_formal_or_apex_sources(
    workspace: FakeWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ReportingApplication(workspace)
    formal = app.render_report("formal-run", add_formal_run(workspace), ReportOptions())
    research = app.render_report("research-study", add_apex_source(workspace), ReportOptions())

    def forbidden(*args, **kwargs):
        raise AssertionError("rebuild re-entered an upstream source")

    monkeypatch.setattr(workspace, "get_run", forbidden)
    monkeypatch.setattr(workspace, "get_result", forbidden)
    monkeypatch.setattr(workspace, "list_records", forbidden)

    assert app.rebuild(formal.envelope.report_id)["ok"] is True
    assert app.rebuild(research.envelope.report_id)["ok"] is True
