from __future__ import annotations

import pytest
from campaign_fixtures import (
    CAMPAIGN_ID,
    SECTION_NAMES,
    publish_campaign_source,
    scenario_campaign_source,
)
from conftest import FakeWorkspace

from strategy_reporting.application import ReportingApplication
from strategy_reporting.canonical import canonical_json


def test_complete_campaign_read_model_preserves_every_apex_owned_section(
    workspace: FakeWorkspace,
) -> None:
    source = scenario_campaign_source("complete")
    publish_campaign_source(workspace, source)

    model = ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)

    assert model.schema_id == "strategy-reporting.campaign-report.v1"
    assert model.subject.model_dump(mode="json") == {
        "campaign_id": CAMPAIGN_ID,
        "source_id": source["source_id"],
    }
    assert model.objective.model_dump(mode="json") == {
        "question": "Can the candidate survive formal validation?",
        "constraints": ["Nautilus is formal truth"],
        "assumptions": ["Published records are immutable"],
        "source": source["brief"]["source"],
    }
    assert tuple(item.name for item in model.sections) == SECTION_NAMES
    assert [item.model_dump(mode="json") for item in model.sections] == source["sections"]
    assert model.source_records == source["sources"]
    assert model.workspace_run_ids == []
    assert canonical_json(model.model_dump(mode="json")) == canonical_json(
        ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID).model_dump(mode="json")
    )


@pytest.mark.parametrize(
    ("scenario", "section", "expected"),
    [
        (
            "partial",
            "candidates",
            {"status": "not_evaluated", "reason": "no public candidates owner facts"},
        ),
        ("blocked", "hypotheses", {"status": "blocked", "reason": "upstream blocked"}),
        ("failed", "failures", {"status": "failed", "reason": "formal run failed"}),
        ("retired", "qualification", {"maturity": "retired", "currency": "current"}),
        (
            "diversity",
            "exploration_archive",
            {"record_type": "apex-research.exploration-archive.v1", "active_entries": ["niche-a"]},
        ),
        (
            "auxiliary",
            "auxiliary_evidence",
            {"evidence_level": "auxiliary", "status": "corroborated"},
        ),
    ],
)
def test_campaign_read_model_keeps_honest_scenario_facts_without_interpretation(
    workspace: FakeWorkspace, scenario: str, section: str, expected: dict[str, object]
) -> None:
    publish_campaign_source(workspace, scenario_campaign_source(scenario))

    model = ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)
    selected = next(item for item in model.sections if item.name == section)

    if scenario in {"partial", "blocked"}:
        assert selected.availability.model_dump(mode="json") == expected
    else:
        assert selected.facts == expected
