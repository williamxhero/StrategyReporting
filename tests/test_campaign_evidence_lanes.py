from __future__ import annotations

from campaign_fixtures import CAMPAIGN_ID, evidence_lane_campaign_source, publish_campaign_source
from conftest import FakeWorkspace

from strategy_reporting.application import ReportingApplication


def test_campaign_evidence_lanes_are_explicit_distinct_and_source_traceable(
    workspace: FakeWorkspace,
) -> None:
    source = evidence_lane_campaign_source()
    workspace.runs["run-formal-1"] = {
        "schema": "quant-research.run-record.v1",
        "run_id": "run-formal-1",
    }
    publish_campaign_source(workspace, source)

    model = ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)

    assert [lane.evidence_class for lane in model.evidence_lanes] == [
        "formal",
        "discovery",
        "empirical",
        "benchmark",
        "auxiliary",
    ]
    lanes = {lane.evidence_class: lane for lane in model.evidence_lanes}
    assert [
        lanes[name].entries[0].data["selector"]
        for name in ("formal", "empirical", "benchmark", "auxiliary")
    ] == [
        "formal.nautilus.metrics.sharpe",
        "empirical.metrics.score",
        "benchmark.metrics.score",
        "auxiliary.metrics.score",
    ]
    assert model.evidence_lanes[1].entries[0].data == {
        "evidence_level": "discovery",
        "entry_count": 9,
    }
    for lane in model.evidence_lanes:
        for entry in lane.entries:
            for quantity in entry.quantitative_values:
                publication_ref = {
                    "record_id": model.source_publication["record_id"],
                    "record_type": model.source_publication["record_type"],
                }
                assert quantity.source in [*model.source_records, publication_ref]
                assert isinstance(quantity.value, int | float) and not isinstance(
                    quantity.value, bool
                )


def test_non_formal_lanes_cannot_populate_formal_or_qualification_claims(
    workspace: FakeWorkspace,
) -> None:
    source = evidence_lane_campaign_source()
    workspace.runs["run-formal-1"] = {
        "schema": "quant-research.run-record.v1",
        "run_id": "run-formal-1",
    }
    publish_campaign_source(workspace, source)

    model = ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)
    lanes = {lane.evidence_class: lane for lane in model.evidence_lanes}

    assert [entry.data["selector"] for entry in lanes["formal"].entries] == [
        "formal.nautilus.metrics.sharpe"
    ]
    assert all(
        not str(entry.data.get("selector", "")).startswith("formal.")
        for name in ("discovery", "empirical", "benchmark", "auxiliary")
        for entry in lanes[name].entries
    )
    qualification = next(item for item in model.sections if item.name == "qualification")
    assert qualification.facts == {"qualification_maturity": "research_validated"}
