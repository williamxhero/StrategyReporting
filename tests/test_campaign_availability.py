from __future__ import annotations

from copy import deepcopy

import pytest
from campaign_fixtures import CAMPAIGN_ID, publish_campaign_source, scenario_campaign_source
from conftest import FakeWorkspace

from strategy_reporting.application import ReportingApplication
from strategy_reporting.errors import ContractError, SourceError


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("complete", "complete"),
        ("partial", "design"),
        ("retired", "partial"),
        ("blocked", "blocked"),
        ("unavailable", "unavailable"),
    ],
)
def test_campaign_report_state_uses_only_explicit_availability(
    workspace: FakeWorkspace, scenario: str, expected: str
) -> None:
    source = scenario_campaign_source(scenario)
    publish_campaign_source(workspace, source)

    model = ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)

    assert model.report_state == expected
    for source_section, report_section in zip(source["sections"], model.sections, strict=True):
        assert report_section.availability.model_dump(mode="json") == source_section["availability"]
        if report_section.availability.status != "available":
            assert report_section.items == []
            assert report_section.facts == {}
    assert "chart" not in model.model_dump_json().lower()


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value["sections"].pop(), "complete, unique"),
        (
            lambda value: value["sections"][0]["availability"].update(
                {"status": "available", "reason": "conflicting reason"}
            ),
            "cannot carry a reason",
        ),
        (
            lambda value: value.update({"current_selection": "latest-created-at"}),
            "current_selection",
        ),
    ],
)
def test_missing_conflicting_or_stale_campaign_source_fails_closed(
    workspace: FakeWorkspace, mutation, match: str
) -> None:
    source = scenario_campaign_source("partial")
    mutation(source)
    publish_campaign_source(workspace, source)

    with pytest.raises(ContractError, match=match):
        ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)


def test_missing_owner_record_fails_without_another_source_fallback(
    workspace: FakeWorkspace,
) -> None:
    source = scenario_campaign_source("partial")
    publish_campaign_source(workspace, source)
    workspace.records.pop(source["brief"]["source"]["record_id"])

    with pytest.raises(SourceError, match="cannot read campaign source owner"):
        ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)


def test_explicit_source_identity_resolves_a_conflict_without_latest_inference(
    workspace: FakeWorkspace,
) -> None:
    first = scenario_campaign_source("partial")
    publish_campaign_source(workspace, first)
    second = deepcopy(scenario_campaign_source("retired"))
    publish_campaign_source(workspace, second)

    with pytest.raises(ContractError, match="multiple"):
        ReportingApplication(workspace).build_campaign_model(CAMPAIGN_ID)
    selected = ReportingApplication(workspace).build_campaign_model(
        CAMPAIGN_ID, source_id=first["source_id"]
    )
    assert selected.subject.source_id == first["source_id"]
