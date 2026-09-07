from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import FakeWorkspace

from strategy_reporting import cli
from strategy_reporting.adapters.behavior_descriptors import BehaviorDescriptorReadModelBuilder
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.behavior_descriptors import BehaviorDescriptorRef
from strategy_reporting.errors import ContractError


def _publication(
    record_id: str,
    record_type: str,
    payload: dict[str, Any],
    lineage: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema": "quant-research.publication.v1",
        "record_id": record_id,
        "record_type": record_type,
        "created_at": "2026-09-07T00:00:00Z",
        "payload": payload,
        "artifacts": [],
        "lineage": lineage,
    }


def _descriptor_fixture(workspace: FakeWorkspace) -> tuple[str, str]:
    candidate = {
        "record_id": "a" * 64,
        "record_type": "apex-research.strategy-candidate.v1",
        "semantic_id": "b" * 64,
        "family_id": "strategy.family.fixture",
        "revision": 1,
    }
    workspace.records[candidate["record_id"]] = _publication(
        candidate["record_id"],
        candidate["record_type"],
        {"schema": candidate["record_type"], "revision_id": candidate["record_id"]},
        [],
    )
    dimensions = [
        {
            "kind": "categorical",
            "dimension_id": "strategy_family",
            "human_label": "Strategy family",
            "machine_definition": "Exact StrategyCandidate family identity.",
            "source_selector": "candidate.envelope.family_id",
            "transformation": "identity",
            "unit": "category",
            "missing_behavior": "unavailable",
            "evidence_tiers": ["discovery"],
            "categories": [
                {
                    "source_value": "strategy.family.fixture",
                    "value": "fixture",
                    "human_label": "Fixture",
                }
            ],
        }
    ]
    taxonomy_body = {
        "schema": "apex-research.behavior-taxonomy.v1",
        "name": "fixture",
        "version": "1",
        "dimensions": dimensions,
    }
    taxonomy_id = canonical_sha256(taxonomy_body)
    taxonomy = {**taxonomy_body, "taxonomy_id": taxonomy_id}
    workspace.records[taxonomy_id] = _publication(taxonomy_id, taxonomy["schema"], taxonomy, [])
    taxonomy_ref = {
        "record_id": taxonomy_id,
        "record_type": "apex-research.behavior-taxonomy.v1",
    }
    source = {
        "record_id": candidate["record_id"],
        "record_type": candidate["record_type"],
        "attempt_id": None,
        "request_hash": None,
        "result_hash": None,
    }
    outcome = {
        "dimension_id": "strategy_family",
        "human_label": "Strategy family",
        "machine_definition": "Exact StrategyCandidate family identity.",
        "source_selector": "candidate.envelope.family_id",
        "unit": "category",
        "status": "assigned",
        "evidence_tier": "discovery",
        "sources": [source],
        "value": "fixture",
        "value_human_label": "Fixture",
        "reason": None,
        "comparability": None,
        "source_values_micros": [],
    }
    niche_id = canonical_sha256(
        {"evidence_tier": "discovery", "taxonomy": taxonomy_ref, "dimensions": [outcome]}
    )
    body = {
        "schema": "apex-research.discovery-behavior-descriptor.v1",
        "evidence_tier": "discovery",
        "taxonomy": taxonomy_ref,
        "candidate": candidate,
        "sources": [candidate],
        "dimensions": [outcome],
        "niche_id": niche_id,
        "niche_label": "Strategy family=Fixture",
        "niche_definition": (
            "strategy_family[Exact StrategyCandidate family identity.] "
            "candidate.envelope.family_id (category) -> assigned:fixture"
        ),
    }
    descriptor_id = canonical_sha256(body)
    descriptor = {**body, "descriptor_id": descriptor_id}
    workspace.records[descriptor_id] = _publication(
        descriptor_id,
        descriptor["schema"],
        descriptor,
        [
            {
                "source_kind": candidate["record_type"],
                "source_id": candidate["record_id"],
                "relation": "descriptor-candidate",
            },
            {
                "source_kind": taxonomy["schema"],
                "source_id": taxonomy_id,
                "relation": "descriptor-taxonomy",
            },
        ],
    )

    formal_taxonomy_body = {
        "schema": "apex-research.behavior-taxonomy.v1",
        "name": "formal-fixture",
        "version": "1",
        "dimensions": [
            {
                "kind": "numeric",
                "dimension_id": "risk_adjusted_return",
                "human_label": "Risk-adjusted return",
                "machine_definition": "Completed comparable Nautilus Sharpe-ratio cells.",
                "source_selector": "formal.nautilus.metrics.sharpe_ratio",
                "transformation": "all_same_bin",
                "unit": "ratio",
                "missing_behavior": "not_evaluated",
                "evidence_tiers": ["formal"],
                "bins": [
                    {
                        "value": "positive",
                        "human_label": "Positive",
                        "lower": 0.0,
                        "upper": 2.0,
                        "lower_inclusive": True,
                        "upper_inclusive": False,
                    }
                ],
            }
        ],
    }
    formal_taxonomy_id = canonical_sha256(formal_taxonomy_body)
    formal_taxonomy = {**formal_taxonomy_body, "taxonomy_id": formal_taxonomy_id}
    workspace.records[formal_taxonomy_id] = _publication(
        formal_taxonomy_id, formal_taxonomy["schema"], formal_taxonomy, []
    )
    evidence_id = "c" * 64
    validation_id = "d" * 64
    for owner_id, owner_type in (
        (evidence_id, "apex-research.evidence.v2"),
        (validation_id, "apex-research.validation-evidence.v1"),
    ):
        workspace.records[owner_id] = _publication(owner_id, owner_type, {"schema": owner_type}, [])
    request = {"fixture": "request"}
    result = {"fixture": "result"}
    workspace.runs["run-formal"] = {
        "run_id": "run-formal",
        "request_hash": canonical_sha256(request),
        "request": request,
        "current_attempt_id": "attempt-formal",
        "result": result,
        "status": "completed",
    }
    runtime_source = {
        "record_id": "run-formal",
        "record_type": "quant-research.run-record.v1",
        "attempt_id": "attempt-formal",
        "request_hash": canonical_sha256(request),
        "result_hash": canonical_sha256(result),
    }
    evidence_source = {
        "record_id": evidence_id,
        "record_type": "apex-research.evidence.v2",
        "attempt_id": None,
        "request_hash": None,
        "result_hash": None,
    }
    validation_source = {
        "record_id": validation_id,
        "record_type": "apex-research.validation-evidence.v1",
        "attempt_id": None,
        "request_hash": None,
        "result_hash": None,
    }
    formal_sources = sorted(
        [evidence_source, validation_source, runtime_source],
        key=lambda item: (item["record_type"], item["record_id"]),
    )
    formal_outcome = {
        "dimension_id": "risk_adjusted_return",
        "human_label": "Risk-adjusted return",
        "machine_definition": "Completed comparable Nautilus Sharpe-ratio cells.",
        "source_selector": "formal.nautilus.metrics.sharpe_ratio",
        "unit": "ratio",
        "status": "assigned",
        "evidence_tier": "formal",
        "sources": formal_sources,
        "value": "positive",
        "value_human_label": "Positive",
        "reason": None,
        "comparability": {"data": "same"},
        "source_values_micros": [1_000_000],
    }
    formal_taxonomy_ref = {
        "record_id": formal_taxonomy_id,
        "record_type": "apex-research.behavior-taxonomy.v1",
    }
    formal_niche_id = canonical_sha256(
        {
            "evidence_tier": "formal",
            "taxonomy": formal_taxonomy_ref,
            "dimensions": [formal_outcome],
            "sources": formal_sources,
        }
    )
    formal_body = {
        "schema": "apex-research.formal-behavior-descriptor.v1",
        "evidence_tier": "formal",
        "taxonomy": formal_taxonomy_ref,
        "candidate": candidate,
        "evidence": {"record_id": evidence_id, "record_type": "apex-research.evidence.v2"},
        "validation_evidence": {
            "record_id": validation_id,
            "record_type": "apex-research.validation-evidence.v1",
        },
        "sources": formal_sources,
        "dimensions": [formal_outcome],
        "niche_id": formal_niche_id,
        "niche_label": "Risk-adjusted return=Positive",
        "niche_definition": (
            "risk_adjusted_return[Completed comparable Nautilus Sharpe-ratio cells.] "
            "formal.nautilus.metrics.sharpe_ratio (ratio) -> assigned:positive"
        ),
    }
    formal_id = canonical_sha256(formal_body)
    formal_descriptor = {**formal_body, "descriptor_id": formal_id}
    workspace.records[formal_id] = _publication(
        formal_id,
        formal_descriptor["schema"],
        formal_descriptor,
        [
            {
                "source_kind": formal_taxonomy["schema"],
                "source_id": formal_taxonomy_id,
                "relation": "descriptor-taxonomy",
            },
            *[
                {
                    "source_kind": item["record_type"],
                    "source_id": item["record_id"],
                    "relation": "descriptor-source",
                }
                for item in formal_sources
            ],
        ],
    )
    return descriptor_id, formal_id


def test_builder_preserves_distinct_descriptor_tiers_without_calculation() -> None:
    workspace = FakeWorkspace()
    discovery_id, formal_id = _descriptor_fixture(workspace)
    builder = BehaviorDescriptorReadModelBuilder(WorkspaceAdapter(workspace))

    discovery = builder.read(BehaviorDescriptorRef.discovery(discovery_id))
    formal = builder.read(BehaviorDescriptorRef.formal(formal_id))

    assert discovery.presentation_label == "exploration descriptor"
    assert discovery.evidence_tier == "discovery"
    assert discovery.descriptor.niche_label == "Strategy family=Fixture"
    assert formal.presentation_label == "formal evidence descriptor"
    assert formal.evidence_tier == "formal"
    assert formal.descriptor.dimensions[0].status == "assigned"
    assert formal.descriptor.dimensions[0].comparability == {"data": "same"}


def test_builder_rejects_tier_swap_and_lineage_drift() -> None:
    workspace = FakeWorkspace()
    discovery_id, formal_id = _descriptor_fixture(workspace)
    builder = BehaviorDescriptorReadModelBuilder(WorkspaceAdapter(workspace))

    with pytest.raises(ContractError):
        builder.read(BehaviorDescriptorRef.formal(discovery_id))
    workspace.records[formal_id]["lineage"] = []
    with pytest.raises(ContractError, match="lineage"):
        builder.read(BehaviorDescriptorRef.formal(formal_id))


def test_behavior_cli_emits_one_distinct_json_read_model(monkeypatch, capsys) -> None:
    workspace = FakeWorkspace()
    discovery_id, formal_id = _descriptor_fixture(workspace)
    monkeypatch.setattr(cli, "production_client", lambda _: workspace)

    assert cli.main(["behavior", "--tier", "discovery", "--descriptor-id", discovery_id]) == 0
    discovery = capsys.readouterr()
    assert discovery.err == ""
    assert len(discovery.out.splitlines()) == 1
    assert json.loads(discovery.out)["result"]["presentation_label"] == ("exploration descriptor")

    assert cli.main(["behavior", "--tier", "formal", "--descriptor-id", formal_id]) == 0
    formal = capsys.readouterr()
    assert formal.err == ""
    assert len(formal.out.splitlines()) == 1
    assert json.loads(formal.out)["result"]["presentation_label"] == ("formal evidence descriptor")
