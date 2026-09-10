from __future__ import annotations

import json

import pytest
from conftest import FakeWorkspace, add_apex_source

from strategy_reporting.application import ReportingApplication
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.cli import main, parser
from strategy_reporting.errors import ContractError
from strategy_reporting.models import ReportOptions


def _publication(
    workspace: FakeWorkspace,
    record_id: str,
    record_type: str,
    payload: dict[str, object],
    *,
    lineage: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    workspace.publish_record(
        {
            "record_id": record_id,
            "record_type": record_type,
            "payload": payload,
            "lineage": lineage or [],
        }
    )
    return {"record_id": record_id, "record_type": record_type}


def _identity(schema: str, field: str, **values: object) -> dict[str, object]:
    body = {"schema": schema, **values}
    return {field: canonical_sha256(body), **body}


def add_replication_source(workspace: FakeWorkspace, outcome: str) -> str:
    case_payload = _identity(
        "apex-research.replication-case.v1",
        "replication_id",
    )
    case = _publication(
        workspace,
        str(case_payload["replication_id"]),
        "apex-research.replication-case.v1",
        case_payload,
    )
    source_metrics = [
        {
            "partition": "source",
            "selector": "source.metrics.total_return_micros",
            "value_micros": 120_000,
            "source_location": "p. 9, table 4",
        }
    ]
    legacy_metrics = [
        {
            "partition": "legacy",
            "selector": "legacy.metrics.total_return_micros",
            "value_micros": 110_000,
            "source_location": "legacy row 7",
        }
    ]
    assumptions = [
        _identity(
            "apex-research.replication-assumption.v1",
            "assumption_id",
            selector="research.assumptions.execution_timing",
            value="next_bar_open",
            rationale="frozen assumption",
        )
    ]
    comparison_policy = _identity(
        "apex-research.replication-comparison-policy.v1",
        "policy_id",
        policy_version="1",
        criteria=[
            {
                "dimension": "metric_definition",
                "source_selector": "source.metrics.total_return_micros",
                "formal_selector": "formal.nautilus.metrics.total_return_micros",
                "mode": "directional" if outcome == "directional" else "exact",
                "tolerance_micros": 0,
                "direction": "same_sign" if outcome == "directional" else None,
            }
        ],
        empirical_methods=[],
    )
    if outcome == "not_reproducible":
        design_type = "apex-research.replication-research-design.v1"
        design_payload = _identity(
            design_type,
            "design_id",
            gaps=[
                {
                    "code": "rule_mapping_incomplete",
                    "selector": "rules.missing",
                    "owner_references": [case],
                }
            ],
        )
        design = _publication(
            workspace,
            str(design_payload["design_id"]),
            design_type,
            design_payload,
        )
        evidence_type = "apex-research.replication-evidence.v1"
        evidence_values = {
            "campaign_id": "a" * 64,
            "case": case,
            "research_design": design,
            "source_metrics": source_metrics,
            "legacy_metrics": legacy_metrics,
            "research_assumptions": assumptions,
            "comparison_policy": comparison_policy,
            "formal_facts": [],
        }
        evidence = _identity(evidence_type, "evidence_id", **evidence_values)
        evidence_ref = _publication(
            workspace, str(evidence["evidence_id"]), evidence_type, evidence
        )
        decision_type = "apex-research.replication-decision.v1"
        decision = _identity(
            decision_type,
            "decision_id",
            campaign_id="a" * 64,
            case=case,
            research_design=design,
            replication_evidence=evidence_ref,
            outcome=outcome,
            formal_run=None,
            evidence_v2=None,
        )
        decision_ref = _publication(
            workspace, str(decision["decision_id"]), decision_type, decision
        )
        formal = None
        formal_facts: list[dict[str, object]] = []
        differences: list[dict[str, object]] = []
        roots = [design, evidence_ref, decision_ref, case]
    else:
        runtime = _publication(
            workspace,
            "8" * 64,
            "quant-research.result.v4",
            {"schema": "quant-research.result.v4", "outcome": "completed"},
        )
        formal_facts = [
            {
                "selector": "formal.nautilus.metrics.total_return_micros",
                "value_micros": 118_000,
                "runtime_evidence": runtime,
            }
        ]
        formal_payload = _identity(
            "apex-research.replication-formal-execution.v1",
            "execution_id",
        )
        formal = _publication(
            workspace,
            str(formal_payload["execution_id"]),
            "apex-research.replication-formal-execution.v1",
            formal_payload,
        )
        differences = [
            {
                "dimension": "metric_definition",
                "source_selector": source_metrics[0]["selector"],
                "formal_selector": formal_facts[0]["selector"],
                "mode": "directional" if outcome == "directional" else "exact",
                "source_value_micros": 120_000,
                "formal_value_micros": 118_000,
                "delta_micros": -2_000,
                "matched": outcome != "failed",
                "source_provenance": "source:p. 9, table 4",
                "formal_provenance": runtime,
            }
        ]
        evidence_type = "apex-research.replication-comparison-evidence.v1"
        evidence = _identity(
            evidence_type,
            "evidence_id",
            campaign_id="a" * 64,
            case=case,
            formal_execution=formal,
            outcome=outcome,
            differences=differences,
            source_metrics=source_metrics,
            legacy_metrics=legacy_metrics,
            research_assumptions=assumptions,
            comparison_policy=comparison_policy,
            formal_facts=formal_facts,
            empirical_support=[],
        )
        evidence_ref = _publication(
            workspace, str(evidence["evidence_id"]), evidence_type, evidence
        )
        decision_type = "apex-research.replication-comparison-decision.v1"
        decision = _identity(
            decision_type,
            "decision_id",
            campaign_id="a" * 64,
            case=case,
            comparison_evidence=evidence_ref,
            outcome=outcome,
        )
        decision_ref = _publication(
            workspace, str(decision["decision_id"]), decision_type, decision
        )
        design = None
        roots = [formal, evidence_ref, decision_ref, case]
    source_values = {
        "campaign_id": "a" * 64,
        "case": case,
        "formal_execution": formal,
        "research_design": design,
        "comparison_evidence": evidence_ref,
        "decision": decision_ref,
        "outcome": outcome,
        "source_metrics": source_metrics,
        "legacy_metrics": legacy_metrics,
        "research_assumptions": assumptions,
        "comparison_policy": comparison_policy,
        "formal_facts": formal_facts,
    }
    source = _identity(
        "apex-research.replication-report-source.v1",
        "report_source_id",
        **source_values,
    )
    source_id = str(source["report_source_id"])
    _publication(
        workspace,
        source_id,
        "apex-research.replication-report-source.v1",
        source,
        lineage=[
            {
                "source_kind": item["record_type"],
                "source_id": item["record_id"],
                "relation": "supports-replication-comparison",
            }
            for item in roots
            if item is not None
        ],
    )
    return source_id


@pytest.mark.parametrize("outcome", ("exact", "directional", "failed", "not_reproducible"))
def test_replication_report_publish_verify_and_rebuild_is_deterministic(
    workspace: FakeWorkspace, outcome: str
) -> None:
    source_id = add_replication_source(workspace, outcome)
    app = ReportingApplication(workspace)

    first = app.render_report("replication-study", source_id, ReportOptions())
    replay = app.render_report("replication-study", source_id, ReportOptions())

    assert replay.envelope == first.envelope
    assert first.envelope.report_kind == "replication-study"
    assert app.verify(first.envelope.report_id).envelope == first.envelope
    assert app.rebuild(first.envelope.report_id)["ok"] is True
    model_ref = next(
        item for item in first.envelope.artifacts if item.logical_role == "report-model"
    )
    html_ref = next(item for item in first.envelope.artifacts if item.logical_role == "report-html")
    model = workspace.contents[model_ref.sha256].decode("utf-8")
    html = workspace.contents[html_ref.sha256].decode("utf-8")
    assert outcome in model and outcome in html
    for partition in (
        "source_metrics",
        "legacy_metrics",
        "research_assumptions",
        "comparison_criteria",
    ):
        assert partition in model and partition in html
    assert bool(json.loads(model)["formal_facts"]) is (outcome != "not_reproducible")
    assert ("rule_mapping_incomplete" in html) is (outcome == "not_reproducible")


def test_replication_source_unknown_field_fails_without_weakening_legacy(
    workspace: FakeWorkspace,
) -> None:
    source_id = add_replication_source(workspace, "not_reproducible")
    workspace.records[source_id]["payload"]["unknown"] = True
    with pytest.raises(ContractError):
        ReportingApplication(workspace).render_report(
            "replication-study", source_id, ReportOptions()
        )

    legacy = FakeWorkspace()
    study_id = add_apex_source(legacy)
    assert (
        ReportingApplication(legacy)
        .render_report("research-study", study_id, ReportOptions())
        .envelope.report_kind
        == "research-study"
    )


def test_render_study_cli_adds_replication_subject_without_changing_legacy_flag() -> None:
    replication = parser().parse_args(["render-study", "--replication-source-id", "1" * 64])
    legacy = parser().parse_args(["render-study", "--study-id", "study-1"])

    assert replication.replication_source_id == "1" * 64
    assert replication.study_id is None
    assert legacy.study_id == "study-1"
    assert legacy.replication_source_id is None


def test_replication_case_owner_identity_drift_fails_closed(
    workspace: FakeWorkspace,
) -> None:
    source_id = add_replication_source(workspace, "exact")
    case_id = workspace.records[source_id]["payload"]["case"]["record_id"]
    workspace.records[case_id]["payload"]["replication_id"] = "0" * 64

    with pytest.raises(ContractError, match="identity"):
        ReportingApplication(workspace).render_report(
            "replication-study", source_id, ReportOptions()
        )


@pytest.mark.parametrize("outcome", ("exact", "directional", "failed", "not_reproducible"))
def test_render_study_cli_dispatches_each_closed_replication_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    outcome: str,
) -> None:
    source_id = canonical_sha256({"outcome": outcome})

    class CliApplication:
        def render_report(self, kind: str, subject: str, options: ReportOptions):
            assert kind == "replication-study"
            assert subject == source_id
            assert options.workspace_root == tmp_path
            return {"outcome": outcome, "source_id": subject}

    monkeypatch.setattr(
        "strategy_reporting.cli.application_for_workspace",
        lambda _root: CliApplication(),
    )

    assert (
        main(
            [
                "--workspace",
                str(tmp_path),
                "render-study",
                "--replication-source-id",
                source_id,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "result": {"outcome": outcome, "source_id": source_id},
    }
