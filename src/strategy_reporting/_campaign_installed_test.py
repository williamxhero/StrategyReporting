"""Installed-wheel acceptance nodes for deterministic campaign reporting."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from strategy_workspace import WorkspaceClient

from strategy_reporting.application import application_for_workspace
from strategy_reporting.portal import PortalBuilder

SECTION_NAMES = (
    "hypotheses",
    "candidates",
    "iterations",
    "quality_gates",
    "packages_and_runs",
    "validation_and_evidence",
    "qualification",
    "failures",
    "budget",
    "exploration_archive",
    "evidence_archive",
    "auxiliary_evidence",
    "limitations",
)
CAMPAIGN_ID = hashlib.sha256(b"installed-campaign").hexdigest()
BRIEF_ID = hashlib.sha256(b"installed-brief").hexdigest()
HYPOTHESIS_ID = hashlib.sha256(b"installed-hypothesis").hexdigest()


def test_installed_campaign_cli_and_public_workspace_adapter(tmp_path: Path) -> None:
    """The installed CLI consumes only the public Workspace Adapter seam."""

    workspace_root = tmp_path / "workspace"
    source_id = _publish_source(workspace_root)
    first = _run_cli(workspace_root, "render-campaign", "--campaign-id", CAMPAIGN_ID)
    second = _run_cli(
        workspace_root,
        "render-campaign",
        "--campaign-id",
        CAMPAIGN_ID,
        "--source-id",
        source_id,
    )

    first_result = first["result"]
    second_result = second["result"]
    assert first_result["envelope"]["report_id"] == second_result["envelope"]["report_id"]
    assert first_result["envelope"]["identity"] == second_result["envelope"]["identity"]
    assert first_result["publication"]["payload"] == second_result["publication"]["payload"]
    assert first_result["envelope"]["report_kind"] == "campaign"
    assert len(first_result["envelope"]["artifacts"]) == 2
    _assert_installed_modules()


def test_installed_campaign_verify_rebuild_and_portal_are_deterministic(
    tmp_path: Path,
) -> None:
    """One installed environment reproduces immutable model, HTML and portal bytes."""

    workspace_root = tmp_path / "workspace"
    _publish_source(workspace_root)
    rendered = _run_cli(
        workspace_root,
        "render-campaign",
        "--campaign-id",
        CAMPAIGN_ID,
        "--detail-row-limit",
        "1",
    )
    report_id = rendered["result"]["envelope"]["report_id"]
    verified = _run_cli(workspace_root, "verify", "--report-id", report_id)
    rebuilt = _run_cli(workspace_root, "rebuild", "--report-id", report_id)
    assert verified["result"]["envelope"]["report_id"] == report_id
    assert rebuilt["result"]["published"] is False
    assert (
        rebuilt["result"]["rebuilt_content_hashes"]
        == rendered["result"]["publication"]["payload"]["expected_content_hashes"]
    )

    app = application_for_workspace(workspace_root)
    first_root = tmp_path / "portal-first"
    second_root = tmp_path / "portal-second"
    first_model = PortalBuilder(app.workspace).build(first_root)
    second_model = PortalBuilder(app.workspace).build(second_root)
    assert first_model["report_count"] == second_model["report_count"] == 1
    assert (first_root / "strategy-report-index.json").read_bytes() == (
        second_root / "strategy-report-index.json"
    ).read_bytes()
    assert (first_root / "index.html").read_bytes() == (second_root / "index.html").read_bytes()
    html = (first_root / "index.html").read_text(encoding="utf-8")
    assert "AI Research Campaigns" in html
    assert "http://" not in html and "https://" not in html and "<script" not in html
    portal_model = json.loads(
        (first_root / "strategy-report-index.json").read_text(encoding="utf-8")
    )
    assert len(portal_model["campaigns"]) == 1
    _assert_installed_modules()


def _publish_source(workspace_root: Path) -> str:
    client = WorkspaceClient(workspace_root)
    client.init()
    references = sorted(
        (
            {"record_id": CAMPAIGN_ID, "record_type": "apex-research.campaign.v1"},
            {"record_id": HYPOTHESIS_ID, "record_type": "apex-research.hypothesis.v1"},
            {"record_id": BRIEF_ID, "record_type": "apex-research.research-brief.v1"},
        ),
        key=lambda item: (item["record_type"], item["record_id"]),
    )
    for reference in references:
        client.publish_record(
            {
                "record_id": reference["record_id"],
                "record_type": reference["record_type"],
                "payload": {"schema": reference["record_type"], "status": "published"},
                "lineage": [],
            }
        )
    sections = [
        {
            "name": "hypotheses",
            "availability": {"status": "available", "reason": None},
            "items": [
                {
                    "source": {
                        "record_id": HYPOTHESIS_ID,
                        "record_type": "apex-research.hypothesis.v1",
                    },
                    "ordinal": 1,
                    "summary": {
                        "evidence_level": "discovery",
                        "statement": "Momentum persists after costs.",
                        "candidate_count": 2,
                    },
                }
            ],
            "facts": {},
        },
        *[
            {
                "name": name,
                "availability": {
                    "status": "not_evaluated",
                    "reason": f"no public {name} owner facts",
                },
                "items": [],
                "facts": {},
            }
            for name in SECTION_NAMES[1:]
        ],
    ]
    payload: dict[str, Any] = {
        "schema": "apex-research.campaign-report-source.v1",
        "campaign": {
            "source": references[0],
            "brief_id": BRIEF_ID,
            "title": "Installed campaign <safe>",
        },
        "brief": {
            "source": next(
                item
                for item in references
                if item["record_type"] == "apex-research.research-brief.v1"
            ),
            "question": "Can the candidate survive formal validation?",
            "constraints": ["Nautilus is formal truth"],
            "assumptions": ["Published records are immutable"],
        },
        "sections": sections,
        "sources": references,
        "workspace_runs": [],
        "current_evidence": None,
        "current_qualification": None,
        "record_ordering": "semantic-sequence-then-public-identity",
        "current_selection": "explicit-supersession-and-currency",
        "failure_policy": "include-all-within-bounded-public-graph",
        "reporting_interpretation": "forbidden",
        "runtime_invocation": "forbidden",
    }
    source_id = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload["source_id"] = source_id
    client.publish_record(
        {
            "record_id": source_id,
            "record_type": "apex-research.campaign-report-source.v1",
            "payload": payload,
            "lineage": [
                {
                    "source_kind": item["record_type"],
                    "source_id": item["record_id"],
                    "relation": "supports-campaign-report",
                }
                for item in references
            ],
        }
    )
    return source_id


def _run_cli(workspace_root: Path, *arguments: str) -> dict[str, Any]:
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(name, None)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "strategy_reporting.cli",
            "--workspace",
            str(workspace_root),
            *arguments,
        ],
        cwd=workspace_root.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        raise AssertionError("CLI result must be a JSON object")
    assert value["ok"] is True
    return value


def _assert_installed_modules() -> None:
    import strategy_workspace

    import strategy_reporting

    for module in (strategy_reporting, strategy_workspace):
        location = Path(str(module.__file__)).resolve().as_posix().lower()
        assert "site-packages" in location
        assert "/src/" not in location
