from __future__ import annotations

import inspect
import re

import pytest
from conftest import FakeWorkspace, add_apex_source
from nautilus_trader.analysis import create_tearsheet_from_stats
from strategy_workspace import WorkspaceClient

from strategy_reporting.adapters import ApexResearchPublicationAdapter, WorkspaceAdapter
from strategy_reporting.errors import ContractError
from strategy_reporting.models import ReportOptions
from strategy_reporting.publishing import WorkspaceReportPublisher
from strategy_reporting.renderers import RendererRegistry


def test_real_workspace_client_publication_round_trip(tmp_path) -> None:
    fixture = FakeWorkspace()
    study_id = add_apex_source(fixture)
    model = ApexResearchPublicationAdapter(WorkspaceAdapter(fixture)).build_model(
        study_id, ReportOptions()
    )
    bundle = RendererRegistry().resolve(model).render(model, ReportOptions())
    client = WorkspaceClient(tmp_path / "workspace")
    client.init()
    publisher = WorkspaceReportPublisher(WorkspaceAdapter(client))
    published = publisher.publish(bundle)
    loaded = publisher.inspect(published.envelope.report_id)
    assert loaded.envelope == published.envelope
    assert all(client.verify_artifact(item.uri)["verified"] for item in loaded.envelope.artifacts)


def test_real_workspace_content_alias_uses_publication_presentation(tmp_path) -> None:
    client = WorkspaceClient(tmp_path / "workspace")
    client.init()
    shared = b"same immutable bytes"
    publication = client.publish_record(
        {
            "record_id": "research.same-content-aliases",
            "record_type": "research-study",
            "payload": {"purpose": "content-alias-regression"},
        },
        artifacts=[
            {
                "source": shared,
                "media_type": "text/csv",
                "record_schema": "quant-research.native-orders.v1",
                "logical_role": "native-orders",
                "name": "native_orders.csv",
            },
            {
                "source": shared,
                "media_type": "application/vnd.quant-research.fills+csv",
                "record_schema": "quant-research.native-fills.v1",
                "logical_role": "native-fills",
                "name": "native_fills.csv",
            },
        ],
    )

    orders, fills = publication["artifacts"]
    assert orders["uri"] == fills["uri"]
    assert orders["sha256"] == fills["sha256"]
    assert orders["name"] == "native_orders.csv"
    assert fills["name"] == "native_fills.csv"
    assert WorkspaceAdapter(client).read_verified_bytes(fills) == shared


def test_real_workspace_forged_report_descriptor_fails_formal_link_lookup(tmp_path) -> None:
    fixture = FakeWorkspace()
    study_id = add_apex_source(fixture)
    source = next(
        item
        for item in fixture.records.values()
        if item["record_type"] == "apex-research.study-report-source.v1"
    )
    client = WorkspaceClient(tmp_path / "workspace")
    client.init()
    client.publish_record(
        {
            "record_id": source["record_id"],
            "record_type": source["record_type"],
            "payload": source["payload"],
            "lineage": source["lineage"],
        },
        artifacts=[],
    )
    client.publish_record(
        {
            "record_id": "report_" + "a" * 64,
            "record_type": "strategy-reporting.report-descriptor.v1",
            "payload": {
                "schema": "strategy-reporting.report-descriptor.v1",
                "report_id": "report_" + "a" * 64,
            },
            "lineage": [],
        },
        artifacts=[],
    )
    with pytest.raises(ContractError, match="descriptor"):
        ApexResearchPublicationAdapter(WorkspaceAdapter(client)).build_model(
            study_id, ReportOptions()
        )


def test_pinned_nautilus_offline_api_signature() -> None:
    signature = inspect.signature(create_tearsheet_from_stats)
    assert list(signature.parameters) == [
        "stats_pnls",
        "stats_returns",
        "stats_general",
        "returns",
        "output_path",
        "title",
        "config",
        "benchmark_returns",
        "benchmark_name",
        "run_info",
        "account_info",
        "engine",
    ]
    assert signature.parameters["output_path"].default == "tearsheet.html"


def test_native_tearsheet_has_no_external_resource_attributes(workspace) -> None:
    from conftest import add_formal_run

    from strategy_reporting.application import ReportingApplication

    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "native-tearsheet-html"
    )
    page = workspace.contents[ref.sha256].decode("utf-8")
    assert not re.search(r"<(?:script|img|link)[^>]+(?:src|href)=[\"'](?:https?:)?//", page, re.I)
