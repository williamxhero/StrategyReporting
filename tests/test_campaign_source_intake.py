from __future__ import annotations

from copy import deepcopy

import pytest
from campaign_fixtures import (
    CAMPAIGN_ID,
    SECTION_NAMES,
    complete_campaign_source,
    publish_campaign_source,
)
from conftest import FakeWorkspace

from strategy_reporting.adapters.campaign_source import CampaignReportSourceAdapter
from strategy_reporting.application import ReportingApplication
from strategy_reporting.errors import ContractError, SourceError


def test_application_reads_one_strict_verified_campaign_source_without_graph_traversal(
    workspace: FakeWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = publish_campaign_source(workspace)
    monkeypatch.setattr(
        workspace,
        "query_lineage",
        lambda **_kwargs: pytest.fail("Reporting must not traverse the campaign graph"),
        raising=False,
    )

    source = ReportingApplication(workspace).read_campaign_source(CAMPAIGN_ID)

    assert source.source_id == publication["record_id"]
    assert source.campaign.source.record_id == CAMPAIGN_ID
    assert tuple(section.name for section in source.sections) == SECTION_NAMES
    assert [item.model_dump(mode="json") for item in source.sources] == publication["payload"][
        "sources"
    ]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update({"unknown": True}), "fields"),
        (lambda value: value.update({"source_id": "0" * 64}), "identity"),
        (
            lambda value: value["brief"].update({"question": "C:/private/campaign.md"}),
            "local path",
        ),
        (
            lambda value: value["brief"].update(
                {"question": r"\\private-host\campaigns\source.json"}
            ),
            "local path",
        ),
        (
            lambda value: value["brief"].update({"question": "/var/lib/private/campaign.json"}),
            "local path",
        ),
        (
            lambda value: value["sections"][0]["items"][0].update({"ordinal": 2}),
            "ordinal",
        ),
    ],
)
def test_campaign_source_contract_fails_closed(
    workspace: FakeWorkspace, mutation, match: str
) -> None:
    payload = complete_campaign_source()
    mutation(payload)
    publish_campaign_source(workspace, payload)

    with pytest.raises(ContractError, match=match):
        CampaignReportSourceAdapter(ReportingApplication(workspace).workspace).read(CAMPAIGN_ID)


def test_campaign_source_rejects_publication_identity_and_lineage_drift(
    workspace: FakeWorkspace,
) -> None:
    publication = publish_campaign_source(workspace)
    publication["lineage"] = publication["lineage"][:-1]
    with pytest.raises(ContractError, match="lineage"):
        ReportingApplication(workspace).read_campaign_source(CAMPAIGN_ID)

    publication = publish_campaign_source(workspace)
    publication["record_id"] = "f" * 64
    with pytest.raises(ContractError, match="identity"):
        ReportingApplication(workspace).read_campaign_source(CAMPAIGN_ID)


def test_campaign_source_missing_or_conflicting_publication_never_falls_back(
    workspace: FakeWorkspace,
) -> None:
    with pytest.raises(SourceError, match="campaign report source"):
        ReportingApplication(workspace).read_campaign_source(CAMPAIGN_ID)

    publish_campaign_source(workspace)
    conflicting = deepcopy(complete_campaign_source())
    conflicting["source_id"] = "d" * 64
    publish_campaign_source(workspace, conflicting)
    with pytest.raises(ContractError, match="multiple"):
        ReportingApplication(workspace).read_campaign_source(CAMPAIGN_ID)
