from __future__ import annotations

import pytest
from conftest import FakeWorkspace, add_apex_source, add_formal_run

from strategy_reporting.application import ReportingApplication
from strategy_reporting.errors import RenderError
from strategy_reporting.html.security import validate_html
from strategy_reporting.models import ReportOptions


def test_malicious_formal_values_are_escaped(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace, malicious=True), ReportOptions()
    )
    html_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-html"
    )
    page = workspace.contents[html_ref.sha256].decode("utf-8")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img src=x" not in page
    assert "&lt;img src=x onerror=" in page


def test_malicious_research_title_is_not_exposed_as_report_copy(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "research-study", add_apex_source(workspace), ReportOptions()
    )
    html_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-html"
    )
    page = workspace.contents[html_ref.sha256].decode("utf-8")
    assert "<script>研究</script>" not in page
    assert "&lt;script&gt;研究&lt;/script&gt;" not in page


@pytest.mark.parametrize(
    "html",
    [
        '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src none"></head><body><script src="https://evil.test/x.js"></script></body></html>',
        '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src none"></head><body><img onerror="boom()"></body></html>',
        '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src none"></head><body><form></form></body></html>',
    ],
)
def test_html_validator_rejects_remote_and_active_content(html: str) -> None:
    with pytest.raises(RenderError):
        validate_html(html.encode(), maximum_bytes=100_000)


def test_html_size_cap_is_enforced() -> None:
    with pytest.raises(RenderError, match="limit"):
        validate_html(b"<!doctype html>" + b"x" * 100, maximum_bytes=10)
