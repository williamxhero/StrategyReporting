from __future__ import annotations

import json
from pathlib import Path

import pytest
from campaign_fixtures import (
    CAMPAIGN_ID,
    evidence_lane_campaign_source,
    publish_campaign_source,
    reidentify_campaign_source,
)
from conftest import FakeWorkspace

from strategy_reporting import cli
from strategy_reporting.application import ReportingApplication
from strategy_reporting.models import ReportOptions


def _rendered_campaign(workspace: FakeWorkspace, *, detail_limit: int = 100):
    source = evidence_lane_campaign_source()
    source["campaign"]["title"] = '</h1><script>alert("campaign")</script>'
    reidentify_campaign_source(source)
    workspace.runs["run-formal-1"] = {
        "schema": "quant-research.run-record.v1",
        "run_id": "run-formal-1",
    }
    publish_campaign_source(workspace, source)
    return ReportingApplication(workspace).render_report(
        "campaign",
        CAMPAIGN_ID,
        ReportOptions(detail_row_limit=detail_limit),
    )


def test_campaign_renderer_is_deterministic_escaped_self_contained_and_bounded(
    workspace: FakeWorkspace,
) -> None:
    publication = _rendered_campaign(workspace, detail_limit=1)
    artifacts = {
        item.name: workspace.contents[item.sha256] for item in publication.envelope.artifacts
    }

    assert publication.envelope.report_kind == "campaign"
    assert set(artifacts) == {"campaign-report.json", "campaign-report.html"}
    model = json.loads(artifacts["campaign-report.json"])
    html = artifacts["campaign-report.html"].decode("utf-8")
    assert model["schema"] == "strategy-reporting.campaign-report.v1"
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html
    assert "Content-Security-Policy" in html
    assert "http://" not in html and "https://" not in html
    assert 'data-omitted="2"' in html
    for evidence_class in ("formal", "discovery", "empirical", "benchmark", "auxiliary"):
        assert f'data-evidence-class="{evidence_class}"' in html

    second = ReportingApplication(workspace).render_report(
        "campaign",
        CAMPAIGN_ID,
        ReportOptions(detail_row_limit=1),
    )
    assert second.envelope.report_id == publication.envelope.report_id
    assert {
        item.name: workspace.contents[item.sha256] for item in second.envelope.artifacts
    } == artifacts


def test_campaign_render_command_uses_public_application_interface(
    workspace: FakeWorkspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = evidence_lane_campaign_source()
    workspace.runs["run-formal-1"] = {
        "schema": "quant-research.run-record.v1",
        "run_id": "run-formal-1",
    }
    publish_campaign_source(workspace, source)
    monkeypatch.setattr(
        cli, "application_for_workspace", lambda _root: ReportingApplication(workspace)
    )

    assert cli.main(["render-campaign", "--campaign-id", CAMPAIGN_ID]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["result"]["envelope"]["report_kind"] == "campaign"


@pytest.mark.slow(
    reason="Launching Edge is an explicit browser acceptance above the 2s unit budget"
)
def test_campaign_html_loads_offline_without_horizontal_overflow_or_console_errors(
    workspace: FakeWorkspace, tmp_path: Path
) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    edge = next(
        (
            path
            for path in (
                Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            )
            if path.is_file()
        ),
        None,
    )
    if edge is None:
        pytest.skip("Edge unavailable")
    publication = _rendered_campaign(workspace)
    html_ref = next(
        item for item in publication.envelope.artifacts if item.logical_role == "report-html"
    )
    destination = tmp_path / "campaign.html"
    destination.write_bytes(workspace.contents[html_ref.sha256])
    console_errors: list[str] = []
    with playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.route(
            "http://**/*", lambda route: pytest.fail(f"network request: {route.request.url}")
        )
        page.route(
            "https://**/*", lambda route: pytest.fail(f"network request: {route.request.url}")
        )
        page.goto(destination.as_uri())
        for width in (1280, 360):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
        browser.close()
    assert console_errors == []
