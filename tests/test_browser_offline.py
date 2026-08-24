from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeWorkspace, add_formal_run

from strategy_reporting.application import ReportingApplication
from strategy_reporting.models import ReportOptions


def test_formal_html_opens_in_edge_without_network(
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
        pytest.skip("Microsoft Edge is unavailable")
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    external: list[str] = []
    console_errors: list[str] = []
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=str(edge), headless=True)
        page = browser.new_page()
        page.on(
            "request",
            lambda request: (
                external.append(request.url)
                if request.url.startswith(("http://", "https://"))
                else None
            ),
        )
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        for ref in report.envelope.artifacts:
            if ref.media_type.startswith("text/html"):
                destination = tmp_path / ref.name
                destination.write_bytes(workspace.contents[ref.sha256])
                response = page.goto(destination.as_uri(), wait_until="load")
                assert response is None or response.ok
                assert page.locator("body").count() == 1
                if ref.logical_role == "native-tearsheet-html":
                    page.wait_for_selector(".main-svg", timeout=5_000)
        browser.close()
    assert external == []
    assert not [item for item in console_errors if "Content Security Policy" in item]
