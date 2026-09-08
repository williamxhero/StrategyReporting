from __future__ import annotations

import json

import pytest
from conftest import FakeWorkspace

from strategy_reporting import cli
from strategy_reporting.adapters.revalidation import RevalidationReadModelBuilder
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.revalidation import RevalidationRecordRef
from strategy_reporting.errors import ContractError
from strategy_reporting.renderers.revalidation import RevalidationRenderer


def _ref(record_id: str, record_type: str) -> dict[str, str]:
    return {"record_id": record_id, "record_type": record_type}


def _publish(
    workspace: FakeWorkspace, record_id: str, record_type: str, payload: dict[str, object]
) -> None:
    workspace.publish_record(
        {"record_id": record_id, "record_type": record_type, "payload": payload, "lineage": []}
    )


def _fixture(workspace: FakeWorkspace, *, malicious: bool = False) -> str:
    closure_id, plan_id, currency_id = "1" * 64, "2" * 64, "3" * 64
    outcome_id, decay_id, archive_id = "4" * 64, "5" * 64, "6" * 64
    evidence_id, replacement_id = "7" * 64, "8" * 64
    evidence_publication_id, qualification_id = "9" * 64, "a" * 64
    reason = "<script>alert(1)</script>" if malicious else "formal Evidence strengthened"
    _publish(
        workspace,
        plan_id,
        "apex-research.revalidation-plan.v1",
        {
            "schema": "apex-research.revalidation-plan.v1",
            "plan_id": plan_id,
            "campaign_id": "b" * 64,
            "stages": [
                {
                    "stage": "data",
                    "action": "external_validation",
                    "resource_class": "local",
                    "resources": [{"kind": "dataset", "resource_id": "fixture", "version": "v1"}],
                    "budget": [
                        {
                            "key": "sample_count",
                            "amount": 1,
                            "unit": "count",
                            "resource_class": "local",
                        }
                    ],
                }
            ],
        },
    )
    _publish(
        workspace,
        currency_id,
        "apex-research.evidence-currency.v1",
        {
            "schema": "apex-research.evidence-currency.v1",
            "currency_id": currency_id,
            "qualification_maturity": "research_qualified",
            "currency": "revalidation_due",
            "evaluation_status": "evaluated",
            "observations": [
                {
                    "trigger": "new_sample_count",
                    "status": "evaluated",
                    "triggered": True,
                    "delta": 200,
                    "reason": "Runtime owner observation",
                    "source": _ref("c" * 64, "quant-runtime.data-change-observation.v1"),
                }
            ],
        },
    )
    _publish(
        workspace,
        outcome_id,
        "apex-research.revalidation-stage-outcome.v1",
        {
            "schema": "apex-research.revalidation-stage-outcome.v1",
            "stage": "data",
            "status": "completed",
            "reason": reason,
        },
    )
    _publish(
        workspace,
        decay_id,
        "apex-research.decay-evaluation.v1",
        {
            "schema": "apex-research.decay-evaluation.v1",
            "status": "evaluated",
            "metrics": [
                {"selector": "formal.nautilus.metrics.sharpe_ratio", "disposition": "strengthened"}
            ],
        },
    )
    closure_ref = _ref(closure_id, "apex-research.revalidation-closure.v1")
    _publish(
        workspace,
        archive_id,
        "apex-research.evidence-archive-current.v1",
        {
            "schema": "apex-research.evidence-archive-current.v1",
            "historical_entries": [
                _ref(evidence_id, "apex-research.evidence.v2"),
                _ref(replacement_id, "apex-research.evidence.v2"),
            ],
            "active_entries": [_ref(replacement_id, "apex-research.evidence.v2")],
            "excluded_entries": [_ref(evidence_id, "apex-research.evidence.v2")],
        },
    )
    _publish(
        workspace,
        evidence_publication_id,
        "apex-research.revalidation-evidence-publication.v1",
        {
            "schema": "apex-research.revalidation-evidence-publication.v1",
            "closure": closure_ref,
            "evidence": _ref(replacement_id, "apex-research.evidence.v2"),
        },
    )
    _publish(
        workspace,
        qualification_id,
        "apex-research.qualification-revalidation.v1",
        {
            "schema": "apex-research.qualification-revalidation.v1",
            "closure": closure_ref,
            "status": "renewed",
            "maturity": "research_qualified",
        },
    )
    _publish(
        workspace,
        closure_id,
        "apex-research.revalidation-closure.v1",
        {
            "schema": "apex-research.revalidation-closure.v1",
            "closure_id": closure_id,
            "plan": _ref(plan_id, "apex-research.revalidation-plan.v1"),
            "outcomes": [_ref(outcome_id, "apex-research.revalidation-stage-outcome.v1")],
            "decays": [_ref(decay_id, "apex-research.decay-evaluation.v1")],
            "prior_currency": _ref(currency_id, "apex-research.evidence-currency.v1"),
            "disposition": "strengthened",
            "resulting_currency": "current",
            "supersedes_evidence": _ref(evidence_id, "apex-research.evidence.v2"),
            "replacement_evidence": _ref(replacement_id, "apex-research.evidence.v2"),
            "reason": reason,
        },
    )
    return closure_id


def test_public_revalidation_reporting_seams_are_available() -> None:
    import strategy_reporting

    assert hasattr(strategy_reporting, "RevalidationReadModelBuilder"), (
        "SPEC-032 Workspace-only read model builder is unavailable"
    )
    assert hasattr(strategy_reporting, "RevalidationRenderer"), (
        "SPEC-032 escaped renderer is unavailable"
    )


def test_builder_copies_maturity_currency_budget_decay_and_archive_without_recalculation() -> None:
    workspace = FakeWorkspace()
    closure_id = _fixture(workspace)
    builder = RevalidationReadModelBuilder(WorkspaceAdapter(workspace))

    first = builder.read(RevalidationRecordRef(record_id=closure_id))
    second = builder.read(RevalidationRecordRef(record_id=closure_id))

    assert first == second
    assert first.read_status == "complete"
    assert first.maturity == "research_qualified"
    assert first.currency == "revalidation_due"
    assert first.trigger_observations[0]["delta"] == 200
    assert first.budget[0]["amount"] == 1
    assert first.decays[0]["metrics"][0]["disposition"] == "strengthened"
    assert first.archive is not None and len(first.archive["historical_entries"]) == 2


def test_renderer_escapes_owner_text_and_cli_is_deterministic(monkeypatch, capsys) -> None:
    workspace = FakeWorkspace()
    closure_id = _fixture(workspace, malicious=True)
    model = RevalidationReadModelBuilder(WorkspaceAdapter(workspace)).read(
        RevalidationRecordRef(record_id=closure_id)
    )
    rendered = RevalidationRenderer().render(model)

    assert b"<script>" not in rendered.html
    assert b"&lt;script&gt;" in rendered.html
    monkeypatch.setattr(cli, "production_client", lambda _: workspace)
    command = ["revalidation", "--record-id", closure_id, "--format", "json"]
    assert cli.main(command) == 0
    first = capsys.readouterr().out
    assert cli.main(command) == 0
    assert capsys.readouterr().out == first
    assert json.loads(first)["result"]["schema"] == (
        "strategy-reporting.revalidation-read-model.v1"
    )


def test_unknown_referenced_schema_fails_closed() -> None:
    workspace = FakeWorkspace()
    closure_id = _fixture(workspace)
    workspace.records[closure_id]["payload"]["plan"]["record_type"] = "unknown.plan.v1"

    with pytest.raises(ContractError, match="schema"):
        RevalidationReadModelBuilder(WorkspaceAdapter(workspace)).read(
            RevalidationRecordRef(record_id=closure_id)
        )
