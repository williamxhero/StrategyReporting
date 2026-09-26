"""apex-research S4-T4 (#541): a real CpaFailureAttribution v2 source renders, verifies and
rebuilds through the existing StrategyReport-v0 pipeline with no adapter changes.

The fixture is the exact ``StudyReportSourceV2.to_wire()`` output apex-research's
``cpa_failure_attribution.build_report_source`` produced from real, published
#539/#540 evidence (CPA-EMA-Crossback-v0 and CPA-Ablation-v0, all three data roles) --
not a hand-typed approximation of its shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import FakeWorkspace

from strategy_reporting.adapters.strategy_v0 import V2_SOURCE_TYPE
from strategy_reporting.application import ReportingApplication
from strategy_reporting.models import ReportOptions

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "apex-research"
    / "cpa-failure-attribution-report-source-v2.json"
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

    workspace.records[research_id] = _publication(
        research_id, research_type, {"schema": research_type, "comparison_id": research_id}
    )
    workspace.records[registration_id] = _publication(
        registration_id,
        registration_type,
        {"schema": registration_type, "registration_id": registration_id},
    )
    workspace.records[source_id] = _publication(source_id, V2_SOURCE_TYPE, source)
    return source_id, research_id


def test_real_cpa_attribution_source_renders_a_strategy_report_v0(
    workspace: FakeWorkspace,
) -> None:
    source_id, research_id = _seed(workspace)
    app = ReportingApplication(workspace)

    report = app.render_report(
        "strategy-report-v0", research_id, ReportOptions(source_id=source_id)
    )

    model_artifact = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = json.loads(workspace.contents[model_artifact.sha256].decode("utf-8"))
    assert model["source_id"] == source_id
    assert model["decision"] == "not_evaluated"
    assert model["evidence_level"] == "not_evaluated"
    # Every not_evaluated section's reason surfaces as a limitation, for real, per-role,
    # per-category evidence gaps -- not a single generic disclaimer.
    assert any("no market-regime classifier" in item for item in model["limitations"])
    assert any("#538's raw event census" in item for item in model["limitations"])
    verdict_sections = [s for s in model["sections"] if s["section_id"].endswith(":verdict")]
    assert len(verdict_sections) == 6
    assert {s["facts"]["verdict"] for s in verdict_sections} == {"failure", "inconclusive"}


def test_real_cpa_attribution_source_verifies_and_rebuilds_deterministically(
    workspace: FakeWorkspace,
) -> None:
    source_id, research_id = _seed(workspace)
    app = ReportingApplication(workspace)

    first = app.render_report("strategy-report-v0", research_id, ReportOptions(source_id=source_id))
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
