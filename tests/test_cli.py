from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeWorkspace, add_apex_source, add_formal_run
from strategy_workspace import WorkspaceClient, WorkspaceWorker

from strategy_reporting import cli
from strategy_reporting.errors import ContractError, PublicationError, RenderError, SourceError


class StubApplication:
    def inspect(self, report_id: str) -> dict[str, Any]:
        return {"report_id": report_id}


def test_cli_success_is_exactly_one_json_line(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "application_for_workspace", lambda root: StubApplication())
    assert cli.main(["inspect", "--report-id", "report_" + "a" * 64]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert json.loads(captured.out)["ok"] is True


def test_cli_usage_error_is_exactly_one_json_line(capsys) -> None:
    assert cli.main(["render-run"]) == 2
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["exit_code"] == 2
    assert "usage:" not in captured.err


def test_real_workspace_missing_report_is_one_json_line_and_source_exit(tmp_path, capsys) -> None:
    WorkspaceClient(tmp_path).init()
    report_id = "report_" + "a" * 64
    assert cli.main(["--workspace", str(tmp_path), "inspect", "--report-id", report_id]) == 3
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["exit_code"] == 3
    assert payload["error"]["code"] == "report_not_found"


def test_real_workspace_all_cli_commands_emit_one_json_line(tmp_path, capsys) -> None:
    workspace_root = tmp_path / "workspace"
    client = WorkspaceClient(workspace_root)
    package = client.register_package(Path(__file__).parent / "fixtures" / "strategy-package")
    request = {
        "schema": "quant-research.workspace-run-request.v2",
        "strategy_package": package["package_ref"],
        "market_snapshot": {
            "schema": "quant-research.market-snapshot-ref.v1",
            "snapshot_id": "sha256:" + "0" * 64,
            "mode": "reference",
            "trust_policy": "assumed_immutable",
            "source": {
                "adapter": "markethub",
                "adapter_version": "fixture",
                "endpoint_contract": "fixture-v1",
                "base_url": "fixture://offline",
                "data_revision": None,
            },
            "query": {
                "instruments": ["000001.SZ"],
                "start": "2026-01-01",
                "end": "2026-01-04",
                "frequency": "1d",
                "adjustment": "none",
            },
            "calendar": "fixture-calendar",
            "contract_mapping": None,
            "resolved_at": "2026-01-05T00:00:00Z",
        },
        "parameters": {"lookback": 20},
        "execution": {
            "topology": "formal_only",
            "formal": [{"id": "primary", "adapter": "nautilus", "config": {}}],
        },
    }
    run = client.submit_run(request)
    worker = WorkspaceWorker(workspace_root)
    running = worker.start_attempt(run["run_id"], worker_id="reporting-cli-fixture")
    attempt_id = running["current_attempt_id"]
    worker.bind_run_identity(
        run["run_id"],
        {
            "schema": "quant-runtime.identity.v2",
            "parameters_hash": "a" * 64,
            "formal": [
                {
                    "formal_id": "primary",
                    "adapter": {"adapter": "nautilus", "adapter_version": "0.2.1"},
                    "config_hash": "b" * 64,
                }
            ],
        },
    )
    formal_fixture = FakeWorkspace()
    fixture_run_id = add_formal_run(
        formal_fixture,
        strategy_id=package["package_ref"]["strategy_id"],
        package_hash=package["package_ref"]["package_hash"],
        parameters_hash="a" * 64,
        snapshot_id="sha256:" + "0" * 64,
    )
    fixture_result = formal_fixture.runs[fixture_run_id]["result"]
    result_payload = {key: value for key, value in fixture_result.items() if key != "artifacts"}
    result_payload["summary"]["attempt_id"] = attempt_id
    worker.complete_attempt(
        run["run_id"],
        result_payload,
        artifacts=[
            {
                "source": formal_fixture.contents[ref["sha256"]],
                "media_type": ref["media_type"],
                "record_schema": ref["record_schema"],
                "logical_role": ref["logical_role"],
                "name": ref["name"],
            }
            for ref in fixture_result["artifacts"]
        ],
    )
    research_fixture = FakeWorkspace()
    study_id = add_apex_source(research_fixture)
    source = next(
        item
        for item in research_fixture.records.values()
        if item["record_type"] == "apex-research.study-report-source.v1"
    )
    client.publish_record(
        {
            "record_id": source["record_id"],
            "record_type": source["record_type"],
            "payload": source["payload"],
            "lineage": source["lineage"],
        },
        artifacts=[],
    )

    def invoke(*args: str) -> dict[str, Any]:
        assert cli.main(["--workspace", str(workspace_root), *args]) == 0
        captured = capsys.readouterr()
        assert captured.err == ""
        assert len(captured.out.splitlines()) == 1
        value = json.loads(captured.out)
        assert value["ok"] is True
        return value["result"]

    formal = invoke("render-run", "--run-id", run["run_id"])
    research = invoke("render-study", "--study-id", study_id)
    formal_report_id = formal["envelope"]["report_id"]
    assert research["envelope"]["report_kind"] == "research-study"
    invoke("inspect", "--report-id", formal_report_id)
    invoke("verify", "--report-id", formal_report_id)
    invoke("rebuild", "--report-id", formal_report_id)
    portal = invoke("portal", "build", "--output", str(tmp_path / "portal"))
    assert portal["report_count"] == 2

    publication = client.get_record(formal_report_id)
    damaged = next(
        item for item in publication["artifacts"] if item["name"] == "formal-run-report.html"
    )
    object_path = (
        workspace_root
        / "artifacts"
        / "objects"
        / damaged["sha256"][:2]
        / f"{damaged['sha256']}.blob"
    )
    object_path.unlink()
    assert (
        cli.main(["--workspace", str(workspace_root), "verify", "--report-id", formal_report_id])
        == 3
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    failure = json.loads(captured.out)
    assert failure["ok"] is False
    assert failure["exit_code"] == 3
    assert failure["error"]["code"] == "artifact_verification_failed"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SourceError("missing", "missing"), 3),
        (ContractError("invalid", "invalid"), 4),
        (RenderError("unsafe", "unsafe"), 5),
        (PublicationError("publish", "publish"), 6),
    ],
)
def test_cli_reporting_error_exit_contract(monkeypatch, capsys, error, expected: int) -> None:
    class FailingApplication:
        def inspect(self, report_id: str) -> None:
            raise error

    monkeypatch.setattr(cli, "application_for_workspace", lambda root: FailingApplication())
    assert cli.main(["inspect", "--report-id", "report_" + "a" * 64]) == expected
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == expected
    assert payload["ok"] is False
