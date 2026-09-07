from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from conftest import FakeWorkspace

from strategy_reporting import cli
from strategy_reporting.adapters.quality_diversity_archives import (
    QualityDiversityArchiveReadModelBuilder,
)
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.quality_diversity_archives import ArchiveRecordRef
from strategy_reporting.errors import ContractError

EXPLORATION = "apex-research.exploration-archive.v1"
EVIDENCE = "apex-research.evidence-archive.v1"


def _ref(record_id: str, record_type: str) -> dict[str, str]:
    return {"record_id": record_id, "record_type": record_type}


def _edge(reference: dict[str, str], relation: str) -> dict[str, str]:
    return {
        "source_kind": reference["record_type"],
        "source_id": reference["record_id"],
        "relation": relation,
    }


def _identified(body: dict[str, Any], identity_field: str) -> dict[str, Any]:
    return {**body, identity_field: canonical_sha256(body)}


def _publish(
    workspace: FakeWorkspace,
    payload: dict[str, Any],
    identity_field: str,
    lineage: list[dict[str, str]],
) -> dict[str, str]:
    record_id = str(payload[identity_field])
    record_type = str(payload["schema"])
    workspace.records[record_id] = {
        "schema": "quant-research.publication.v1",
        "record_id": record_id,
        "record_type": record_type,
        "created_at": "2026-09-07T00:00:00Z",
        "payload": payload,
        "artifacts": [],
        "lineage": lineage,
    }
    return _ref(record_id, record_type)


def _external(workspace: FakeWorkspace, record_id: str, record_type: str) -> dict[str, str]:
    workspace.records[record_id] = {
        "schema": "quant-research.publication.v1",
        "record_id": record_id,
        "record_type": record_type,
        "created_at": "2026-09-07T00:00:00Z",
        "payload": {"schema": record_type},
        "artifacts": [],
        "lineage": [],
    }
    return _ref(record_id, record_type)


def _archive_fixture(workspace: FakeWorkspace) -> tuple[str, str]:
    campaign = _external(workspace, "a" * 64, "apex-research.campaign.v1")
    taxonomy = _external(workspace, "b" * 64, "apex-research.behavior-taxonomy.v1")
    candidate = {
        **_external(workspace, "c" * 64, "apex-research.strategy-candidate.v1"),
        "semantic_id": "d" * 64,
        "family_id": "fixture.strategy",
        "revision": 1,
    }
    descriptor = _external(workspace, "e" * 64, "apex-research.discovery-behavior-descriptor.v1")
    quality = _external(workspace, "f" * 64, "apex-research.discovery-archive-quality.v1")

    exploration_policy = _identified(
        {
            "schema": EXPLORATION,
            "kind": "policy",
            "archive_family": "exploration",
            "archive_label": "exploration archive",
            "entry_label": "discovery leader",
            "campaign": campaign,
            "taxonomy": taxonomy,
            "name": "fixture exploration",
            "version": "1",
            "niche_capacity": 1,
            "comparison_mode": "lexicographic",
            "objectives": [
                {
                    "objective_id": "score",
                    "selector": "discovery.metrics.score",
                    "direction": "maximize",
                    "unit": "ratio",
                    "priority": 0,
                }
            ],
            "tie_breaker": "entry_id_ascending",
            "unavailable_objective_rule": "reject",
            "novelty_rule": "descriptor_niche_id",
            "empty_niche_rule": "admit",
            "formal_claim": "forbidden",
            "robustness_claim": "forbidden",
            "qualification_claim": "forbidden",
            "current_evidence_claim": "forbidden",
            "production_claim": "forbidden",
        },
        "policy_id",
    )
    exploration_policy_ref = _publish(
        workspace,
        exploration_policy,
        "policy_id",
        [_edge(campaign, "archive-campaign"), _edge(taxonomy, "archive-taxonomy")],
    )
    exploration_entry = _identified(
        {
            "candidate": candidate,
            "descriptor": descriptor,
            "quality": quality,
            "niche_id": "1" * 64,
            "generation_position": 0,
            "entry_label": "discovery leader",
        },
        "entry_id",
    )
    exploration_event = _identified(
        {
            "schema": EXPLORATION,
            "kind": "event",
            "archive_family": "exploration",
            "policy": exploration_policy_ref,
            "predecessor": None,
            "generation_position": 0,
            "candidate": candidate,
            "decision": "inserted",
            "considered": exploration_entry,
            "admitted": exploration_entry,
            "displaced": [],
            "reason": "empty niche admitted",
        },
        "event_id",
    )
    exploration_event_ref = _publish(
        workspace,
        exploration_event,
        "event_id",
        [
            _edge(exploration_policy_ref, "archive-policy"),
            _edge(descriptor, "archive-descriptor"),
            _edge(quality, "archive-quality"),
        ],
    )
    exploration_snapshot = _identified(
        {
            "schema": EXPLORATION,
            "kind": "snapshot",
            "archive_family": "exploration",
            "archive_label": "exploration archive",
            "entry_label": "discovery leader",
            "policy": exploration_policy_ref,
            "taxonomy": taxonomy,
            "predecessor": None,
            "generation_id": "2" * 64,
            "generation_positions": [0],
            "events": [exploration_event_ref],
            "entries": [exploration_entry],
            "historical_entries": [exploration_entry],
            "considered_niches": ["1" * 64, "3" * 64],
            "occupied_niches": ["1" * 64],
            "empty_niches": ["3" * 64],
            "formal_claim": "forbidden",
            "robustness_claim": "forbidden",
            "qualification_claim": "forbidden",
            "current_evidence_claim": "forbidden",
            "production_claim": "forbidden",
        },
        "snapshot_id",
    )
    exploration_snapshot_ref = _publish(
        workspace,
        exploration_snapshot,
        "snapshot_id",
        [
            _edge(exploration_policy_ref, "archive-policy"),
            _edge(exploration_event_ref, "archive-event"),
        ],
    )

    formal_descriptor = _external(
        workspace, "4" * 64, "apex-research.formal-behavior-descriptor.v1"
    )
    evidence = _external(workspace, "5" * 64, "apex-research.evidence.v2")
    qualification = _external(workspace, "6" * 64, "apex-research.qualification-decision.v1")
    evidence_policy = _identified(
        {
            "schema": EVIDENCE,
            "kind": "policy",
            "archive_family": "evidence",
            "archive_label": "evidence archive",
            "entry_label": "historical formal evidence leader",
            "campaign": campaign,
            "taxonomy": taxonomy,
            "name": "fixture evidence",
            "version": "1",
            "niche_capacity": 1,
            "comparison_mode": "lexicographic",
            "objectives": [
                {
                    "objective_id": "sharpe",
                    "selector": "formal.nautilus.metrics.sharpe_ratio",
                    "direction": "maximize",
                    "unit": "ratio",
                    "priority": 0,
                }
            ],
            "minimum_historical_maturity": "formally_tested",
            "currency_requirement": "current_required",
            "tie_breaker": "entry_id_ascending",
            "operational_authority": "forbidden",
            "production_claim": "forbidden",
            "live_trading_claim": "forbidden",
        },
        "policy_id",
    )
    evidence_policy_ref = _publish(
        workspace,
        evidence_policy,
        "policy_id",
        [_edge(campaign, "archive-campaign"), _edge(taxonomy, "archive-taxonomy")],
    )
    consideration = _identified(
        {
            "candidate": candidate,
            "descriptor": formal_descriptor,
            "evidence": evidence,
            "qualification": qualification,
            "taxonomy": taxonomy,
            "niche_id": "7" * 64,
            "exploration_lineage": None,
            "observations": [],
            "status": "rejected",
            "reason": "formal owner facts incomplete",
        },
        "consideration_id",
    )
    evidence_event = _identified(
        {
            "schema": EVIDENCE,
            "kind": "event",
            "archive_family": "evidence",
            "policy": evidence_policy_ref,
            "predecessor": None,
            "consideration": consideration,
            "decision": "rejected",
            "admitted": None,
            "displaced": [],
            "reason": "formal owner facts incomplete",
            "historical_claim": "historical_formal_evidence",
            "current_active_eligibility": "not_evaluated",
            "current_active_blocker": "SPEC-032 exact currency owner fact unavailable",
            "operational_authority": "forbidden",
        },
        "event_id",
    )
    evidence_event_ref = _publish(
        workspace,
        evidence_event,
        "event_id",
        [
            _edge(evidence_policy_ref, "archive-policy"),
            _edge(formal_descriptor, "archive-formal-descriptor"),
            _edge(evidence, "archive-formal-evidence"),
            _edge(qualification, "archive-historical-qualification"),
        ],
    )
    evidence_snapshot = _identified(
        {
            "schema": EVIDENCE,
            "kind": "snapshot",
            "archive_family": "evidence",
            "archive_label": "evidence archive",
            "entry_label": "historical formal evidence leader",
            "policy": evidence_policy_ref,
            "taxonomy": taxonomy,
            "predecessor": None,
            "events": [evidence_event_ref],
            "historical_entries": [],
            "all_historical_entries": [],
            "current_active_entries": [],
            "current_active_view": "blocked",
            "current_active_reason": "SPEC-032 exact currency owner fact unavailable",
            "operational_authority": "forbidden",
            "production_claim": "forbidden",
            "live_trading_claim": "forbidden",
        },
        "snapshot_id",
    )
    evidence_snapshot_ref = _publish(
        workspace,
        evidence_snapshot,
        "snapshot_id",
        [_edge(evidence_policy_ref, "archive-policy"), _edge(evidence_event_ref, "archive-event")],
    )
    return exploration_snapshot_ref["record_id"], evidence_snapshot_ref["record_id"]


def test_builder_preserves_distinct_owner_archives_without_calculation() -> None:
    workspace = FakeWorkspace()
    exploration_id, evidence_id = _archive_fixture(workspace)
    builder = QualityDiversityArchiveReadModelBuilder(WorkspaceAdapter(workspace))

    exploration = builder.read(ArchiveRecordRef.exploration(exploration_id))
    evidence = builder.read(ArchiveRecordRef.evidence(evidence_id))

    assert exploration.presentation_label == "exploration archive — discovery leaders"
    assert exploration.record.archive_family == "exploration"
    assert exploration.record.occupied_niches == ["1" * 64]
    assert exploration.record.empty_niches == ["3" * 64]
    assert evidence.presentation_label == "evidence archive — historical formal evidence leaders"
    assert evidence.record.archive_family == "evidence"
    assert evidence.record.current_active_entries == []
    assert evidence.record.current_active_view == "blocked"
    assert evidence.current_active_eligibility == "not_evaluated"
    assert evidence.current_active_reason == "SPEC-032 exact currency owner fact unavailable"


def test_builder_rejects_family_label_identity_and_lineage_drift() -> None:
    workspace = FakeWorkspace()
    exploration_id, evidence_id = _archive_fixture(workspace)
    builder = QualityDiversityArchiveReadModelBuilder(WorkspaceAdapter(workspace))

    with pytest.raises(ContractError):
        builder.read(ArchiveRecordRef.evidence(exploration_id))
    original = copy.deepcopy(workspace.records[evidence_id])
    workspace.records[evidence_id]["payload"]["entry_label"] = "current champion"
    with pytest.raises(ContractError):
        builder.read(ArchiveRecordRef.evidence(evidence_id))
    workspace.records[evidence_id] = original
    workspace.records[evidence_id]["lineage"] = []
    with pytest.raises(ContractError, match="lineage"):
        builder.read(ArchiveRecordRef.evidence(evidence_id))


def test_archive_cli_emits_one_deterministic_distinct_json_model(monkeypatch, capsys) -> None:
    workspace = FakeWorkspace()
    exploration_id, evidence_id = _archive_fixture(workspace)
    monkeypatch.setattr(cli, "production_client", lambda _: workspace)

    assert cli.main(["archive", "--family", "exploration", "--record-id", exploration_id]) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert len(first.out.splitlines()) == 1
    exploration = json.loads(first.out)
    assert exploration["result"]["presentation_label"] == (
        "exploration archive — discovery leaders"
    )

    assert cli.main(["archive", "--family", "evidence", "--record-id", evidence_id]) == 0
    second = capsys.readouterr()
    assert second.err == ""
    assert len(second.out.splitlines()) == 1
    evidence = json.loads(second.out)
    assert evidence["result"]["current_active_eligibility"] == "not_evaluated"
    assert "current champion" not in second.out
    assert cli.main(["archive", "--family", "evidence", "--record-id", evidence_id]) == 0
    assert capsys.readouterr().out == second.out
