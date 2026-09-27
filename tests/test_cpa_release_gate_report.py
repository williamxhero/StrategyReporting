"""apex-research S6-T2 (#547): the real comprehensive V1.1 report source renders, verifies
and rebuilds through the existing StrategyReport-v0 pipeline with no adapter changes, and
rebuild is structurally incapable of submitting a new Runtime job.

The fixture is the exact ``StudyReportSourceV2.to_wire()`` output for the real, published
S6-T1 (#546) comprehensive report source (80 sections: coverage/exclusions/claim-boundaries/
deviations, every #541 attribution finding, #544's revalidation deltas, #543's search
budget) -- not a hand-typed approximation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import FakeWorkspace

from strategy_reporting.adapters.strategy_v0 import V2_SOURCE_TYPE
from strategy_reporting.adapters.workspace import WorkspaceClientPort
from strategy_reporting.application import ReportingApplication
from strategy_reporting.models import ReportOptions

FIXTURE = (
    Path(__file__).parent / "fixtures" / "apex-research" / "cpa-comprehensive-report-source-v2.json"
)


def _publication(record_id: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "quant-research.publication.v1",
        "record_id": record_id,
        "record_type": record_type,
        "created_at": "2026-09-27T00:00:00Z",
        "payload": payload,
        "artifacts": [],
        "lineage": [],
    }


def _seed(workspace: FakeWorkspace) -> tuple[str, str]:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source_id = source["source_id"]
    research_id = source["research"]["record_id"]
    research_type = source["research"]["record_type"]
    registration_id = source["registration"]["record_id"]
    registration_type = source["registration"]["record_type"]
    revision_ref = source["revisions"][0]
    conclusion_ref = source["conclusion"]
    conclusion_history_refs = source["conclusion_history"]

    workspace.records[research_id] = _publication(
        research_id, research_type, {"schema": research_type, "comparison_id": research_id}
    )
    workspace.records[registration_id] = _publication(
        registration_id,
        registration_type,
        {"schema": registration_type, "registration_id": registration_id},
    )
    workspace.records[revision_ref["record_id"]] = _publication(
        revision_ref["record_id"],
        revision_ref["record_type"],
        {"schema": revision_ref["record_type"], "revision_id": revision_ref["record_id"]},
    )
    conclusion_refs = {
        conclusion_ref["record_id"]: conclusion_ref,
        **{r["record_id"]: r for r in conclusion_history_refs},
    }
    for ref in conclusion_refs.values():
        workspace.records[ref["record_id"]] = _publication(
            ref["record_id"],
            ref["record_type"],
            {
                "schema": ref["record_type"],
                "conclusion_id": ref["record_id"],
                "decision": "uncertain",
                "evidence_level": "candidate_evidence",
                "limitations": [],
            },
        )
    workspace.records[source_id] = _publication(source_id, V2_SOURCE_TYPE, source)
    return source_id, research_id


def test_workspace_client_port_cannot_submit_a_new_research_run() -> None:
    """strategy_reporting's entire Workspace interface has no method that could submit a
    new Runtime job -- rebuild() is structurally incapable of triggering new research,
    not merely well-behaved by convention."""
    members = {name for name in dir(WorkspaceClientPort) if not name.startswith("_")}

    assert not any("submit" in name for name in members)
    assert not any(name in {"run", "register_package", "governance"} for name in members)
    assert members == {
        "init",
        "get_run",
        "get_result",
        "get_record",
        "list_records",
        "query_lineage",
        "read_artifact",
        "materialize_artifact",
        "verify_artifact",
        "publish_record",
    }


def test_real_comprehensive_report_source_renders_verifies_and_rebuilds(
    workspace: FakeWorkspace,
) -> None:
    source_id, research_id = _seed(workspace)
    app = ReportingApplication(workspace)

    first = app.render_report("strategy-report-v0", research_id, ReportOptions(source_id=source_id))
    model_artifact = next(
        item for item in first.envelope.artifacts if item.logical_role == "report-model"
    )
    model = json.loads(workspace.contents[model_artifact.sha256].decode("utf-8"))
    assert model["source_id"] == source_id
    assert len(model["sections"]) == 80
    # Real, previously-not_evaluated limitations must still surface, not be summarized away.
    assert any("no market-regime classifier" in item for item in model["limitations"])

    verified = app.verify(first.envelope.report_id)
    assert verified.envelope == first.envelope

    rebuilt = app.rebuild(first.envelope.report_id)
    assert (
        rebuilt["rebuilt_content_hashes"] == first.publication["payload"]["expected_content_hashes"]
    )

    second = app.render_report(
        "strategy-report-v0", research_id, ReportOptions(source_id=source_id)
    )
    assert second.envelope.report_id == first.envelope.report_id
    assert workspace.publish_calls == 1
