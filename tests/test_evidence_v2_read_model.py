from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from conftest import FakeWorkspace

from strategy_reporting.adapters.evidence_v2 import EvidenceV2ReadModelBuilder
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.evidence_v2 import (
    EvidenceV2SourceRef,
    EvidenceV2StudySource,
    evidence_record_descriptor,
)
from strategy_reporting.errors import ContractError


def _publication(
    *,
    record_id: str,
    record_type: str,
    payload: dict[str, Any],
    lineage: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "quant-research.publication.v1",
        "record_id": record_id,
        "record_type": record_type,
        "created_at": "2026-09-05T00:00:00Z",
        "payload": payload,
        "artifacts": [],
        "lineage": lineage or [],
    }


def _owner_record(
    record_type: str,
    identity_field: str,
    **values: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = {"schema": record_type, **values}
    record_id = canonical_sha256(identity)
    payload = {**identity, identity_field: record_id}
    reference = {"record_id": record_id, "record_type": record_type}
    return reference, _publication(
        record_id=record_id,
        record_type=record_type,
        payload=payload,
    )


def _source(
    reference: dict[str, Any],
    *,
    namespace: str,
    canonical_owner: str = "apex_research",
) -> dict[str, Any]:
    return {
        "canonical_owner": canonical_owner,
        "namespace": namespace,
        "record": reference,
    }


def _section(
    status: str,
    reason: str,
    *,
    sources: list[dict[str, Any]] | None = None,
    outcome: str | None = None,
    blockers: list[dict[str, Any]] | None = None,
    incompatibilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "sources": sources or [],
        "outcome": outcome,
        "blockers": blockers or [],
        "incompatibilities": incompatibilities or [],
    }


def test_evidence_record_descriptor_is_the_single_typed_taxonomy() -> None:
    candidate = evidence_record_descriptor("apex-research.strategy-candidate.v1")
    runtime = evidence_record_descriptor("quant-research.run-record.v1")
    auxiliary = evidence_record_descriptor("apex-research.auxiliary-validation.v1")

    assert candidate.reference_shape == "candidate"
    assert candidate.namespace == "strategy.composition"
    assert candidate.identity_field == "revision_id"
    assert runtime.canonical_owner == "quant_runtime"
    assert runtime.reference_shape == "runtime"
    assert auxiliary.artifact_claim == "auxiliary"
    assert auxiliary.scope_binding == "campaign_candidate_protocol"
    with pytest.raises(ValueError, match="unsupported"):
        evidence_record_descriptor("unknown.owner-record.v1")


def _fixture(workspace: FakeWorkspace) -> EvidenceV2SourceRef:
    package = {
        "schema": "quant-research.strategy-package-ref.v1",
        "strategy_id": "strict-v2-strategy",
        "revision": 1,
        "package_hash": "9" * 64,
    }
    campaign_ref, campaign_publication = _owner_record(
        "apex-research.campaign.v1",
        "campaign_id",
        title="Strict Evidence v2 campaign",
    )
    strategy_ref, strategy_publication = _owner_record(
        "apex-research.strategy-candidate.v1",
        "revision_id",
        semantic_id="8" * 64,
        envelope={"family_id": "strict-family", "revision": 1},
        semantics={"signals": []},
    )
    strategy_ref.update(
        semantic_id="8" * 64,
        family_id="strict-family",
        revision=1,
    )
    protocol_ref, protocol_publication = _owner_record(
        "apex-research.validation-protocol-matrix.v1",
        "protocol_id",
        campaign={key: campaign_ref[key] for key in ("record_id", "record_type")},
        candidate={key: strategy_ref[key] for key in ("record_id", "record_type")},
        strategy_package=package,
    )

    campaign_source = _source(campaign_ref, namespace="apex.control")
    protocol_source = _source(protocol_ref, namespace="apex.control")
    strategy_source = _source(strategy_ref, namespace="strategy.composition")
    sources = sorted(
        [campaign_source, protocol_source, strategy_source],
        key=lambda item: (
            item["canonical_owner"],
            item["namespace"],
            item["record"]["record_type"],
            item["record"]["record_id"],
        ),
    )
    not_evaluated = _section(
        "not_evaluated",
        "No canonical owner record was present in this frozen snapshot.",
    )
    evidence_identity = {
        "schema": "apex-research.evidence.v2",
        "scope": {
            "campaign": campaign_ref,
            "protocol": protocol_ref,
            "candidate": strategy_ref,
            "strategy_package": package,
            "hypothesis": None,
            "iteration": None,
        },
        "sources": sources,
        "sections": {
            "source_mapping": _section(
                "evaluated",
                "The exact canonical owner source set was read back.",
                sources=sources,
            ),
            "candidates": {
                "factor": deepcopy(not_evaluated),
                "model": deepcopy(not_evaluated),
                "strategy": _section(
                    "evaluated",
                    "The exact StrategyCandidate was read back.",
                    sources=[strategy_source],
                    outcome="pass",
                ),
            },
            "candidate_gates": deepcopy(not_evaluated),
            "data_identity": deepcopy(not_evaluated),
            "execution_costs": deepcopy(not_evaluated),
            "formal_results": deepcopy(not_evaluated),
            "validation_matrix": deepcopy(not_evaluated),
            "statistical_controls": deepcopy(not_evaluated),
            "robustness": _section(
                "incomparable",
                "The frozen protocol and Candidate scopes are incompatible.",
                sources=[protocol_source, strategy_source],
                incompatibilities=[
                    {
                        "axis": "strategy.scope",
                        "left": protocol_source,
                        "right": strategy_source,
                    }
                ],
            ),
            "auxiliary_validation": deepcopy(not_evaluated),
            "failures": _section(
                "blocked",
                "A canonical campaign owner fact blocks evaluation.",
                sources=[campaign_source],
                blockers=[campaign_source],
            ),
            "warnings": deepcopy(not_evaluated),
            "limitations": deepcopy(not_evaluated),
            "co_evolution": deepcopy(not_evaluated),
            "currency": deepcopy(not_evaluated),
            "revalidation": deepcopy(not_evaluated),
        },
        "candidate_composition": {
            "factors": [],
            "models": [],
            "strategy": strategy_ref,
            "factor_namespace": "discovery.non_formal",
            "model_namespace": "discovery.non_formal",
            "formal_source": "strategy_package_only",
        },
        "candidate_gate": None,
        "runtime_formal": [],
        "validation_coverage": None,
        "statistical_control": None,
        "honesty": None,
        "qualification_inference": "forbidden",
        "production_approval_inference": "forbidden",
        "supersedes": None,
    }
    evidence_id = canonical_sha256(evidence_identity)
    evidence = {**evidence_identity, "evidence_id": evidence_id}
    evidence_ref = {
        "record_id": evidence_id,
        "record_type": "apex-research.evidence.v2",
    }
    evidence_lineage = [
        {
            "source_kind": item["record"]["record_type"],
            "source_id": item["record"]["record_id"],
            "relation": "evidence-source",
        }
        for item in sources
    ] + [
        {
            "source_kind": "quant-research.strategy-package-ref.v1",
            "source_id": package["package_hash"],
            "relation": "evidence-strategy-package",
        }
    ]
    if evidence.get("supersedes") is not None:
        evidence_lineage.append(
            {
                "source_kind": evidence["supersedes"]["record_type"],
                "source_id": evidence["supersedes"]["record_id"],
                "relation": "supersedes-evidence",
            }
        )
    evidence_publication = _publication(
        record_id=evidence_id,
        record_type="apex-research.evidence.v2",
        payload=evidence,
        lineage=evidence_lineage,
    )

    source_refs = [
        {
            "record_id": item["record"]["record_id"],
            "record_type": item["record"]["record_type"],
        }
        for item in sources
    ]
    source_identity = {
        "schema": "apex-research.study-report-source.v2",
        "evidence_ref": evidence_ref,
        "evidence": evidence,
        "sources": source_refs,
        "source_record_ids": [item["record_id"] for item in source_refs],
        "workspace_runs": [],
        "qualification_inference": "forbidden",
        "production_approval_inference": "forbidden",
    }
    source_id = canonical_sha256(source_identity)
    source_payload = {**source_identity, "source_id": source_id}
    source_lineage = [
        {
            "source_kind": "apex-research.evidence.v2",
            "source_id": evidence_id,
            "relation": "evidence-v2",
        }
    ] + [
        {
            "source_kind": item["record_type"],
            "source_id": item["record_id"],
            "relation": "evidence-source",
        }
        for item in source_refs
    ]
    source_publication = _publication(
        record_id=source_id,
        record_type="apex-research.study-report-source.v2",
        payload=source_payload,
        lineage=source_lineage,
    )

    workspace.records.update(
        {
            campaign_ref["record_id"]: campaign_publication,
            strategy_ref["record_id"]: strategy_publication,
            protocol_ref["record_id"]: protocol_publication,
            evidence_id: evidence_publication,
            source_id: source_publication,
        }
    )
    return EvidenceV2SourceRef(record_id=source_id)


def _publish_source(
    workspace: FakeWorkspace,
    evidence: dict[str, Any],
) -> EvidenceV2SourceRef:
    evidence_identity = {key: value for key, value in evidence.items() if key != "evidence_id"}
    evidence_id = canonical_sha256(evidence_identity)
    evidence = {**evidence_identity, "evidence_id": evidence_id}
    evidence_ref = {
        "record_id": evidence_id,
        "record_type": "apex-research.evidence.v2",
    }
    evidence_lineage = [
        {
            "source_kind": item["record"]["record_type"],
            "source_id": item["record"]["record_id"],
            "relation": "evidence-source",
        }
        for item in evidence["sources"]
    ] + [
        {
            "source_kind": "quant-research.strategy-package-ref.v1",
            "source_id": evidence["scope"]["strategy_package"]["package_hash"],
            "relation": "evidence-strategy-package",
        }
    ]
    if evidence.get("supersedes") is not None:
        evidence_lineage.append(
            {
                "source_kind": evidence["supersedes"]["record_type"],
                "source_id": evidence["supersedes"]["record_id"],
                "relation": "supersedes-evidence",
            }
        )
    source_refs = [
        {
            "record_id": item["record"]["record_id"],
            "record_type": item["record"]["record_type"],
        }
        for item in evidence["sources"]
    ]
    workspace_runs = sorted(
        [
            item["record"]
            for item in evidence["sources"]
            if item["record"]["record_type"] == "quant-research.run-record.v1"
        ],
        key=lambda item: (item["record_id"], item["attempt_id"]),
    )
    source_identity = {
        "schema": "apex-research.study-report-source.v2",
        "evidence_ref": evidence_ref,
        "evidence": evidence,
        "sources": source_refs,
        "source_record_ids": [item["record_id"] for item in source_refs],
        "workspace_runs": workspace_runs,
        "qualification_inference": "forbidden",
        "production_approval_inference": "forbidden",
    }
    source_id = canonical_sha256(source_identity)
    source_payload = {**source_identity, "source_id": source_id}
    workspace.records[evidence_id] = _publication(
        record_id=evidence_id,
        record_type="apex-research.evidence.v2",
        payload=evidence,
        lineage=evidence_lineage,
    )
    workspace.records[source_id] = _publication(
        record_id=source_id,
        record_type="apex-research.study-report-source.v2",
        payload=source_payload,
        lineage=[
            {
                "source_kind": "apex-research.evidence.v2",
                "source_id": evidence_id,
                "relation": "evidence-v2",
            },
            *(
                {
                    "source_kind": item["record_type"],
                    "source_id": item["record_id"],
                    "relation": "evidence-source",
                }
                for item in source_refs
            ),
        ],
    )
    return EvidenceV2SourceRef(record_id=source_id)


def _runtime_fixture(workspace: FakeWorkspace) -> EvidenceV2SourceRef:
    base = _fixture(workspace)
    evidence = deepcopy(workspace.records[base.record_id]["payload"]["evidence"])
    package = evidence["scope"]["strategy_package"]
    campaign_ref = evidence["scope"]["campaign"]
    candidate_ref = evidence["scope"]["candidate"]
    protocol_ref = evidence["scope"]["protocol"]
    run_id = "runtime-run-1"
    attempt_id = "runtime-attempt-1"
    artifact = workspace.add_artifact(
        b'{"equity": [1, 2, 3]}',
        name="formal/primary/equity.json",
        logical_role="formal-equity",
    )
    market_snapshot = {
        "schema": "quant-research.market-snapshot-ref.v2",
        "snapshot_id": "sha256:" + "4" * 64,
        "mode": "reference",
        "trust_policy": "verified_immutable",
        "source": {
            "adapter": "markethub",
            "adapter_version": "1.0.1",
            "endpoint_contract": "v2",
            "base_url": "http://fixture",
            "data_revision": "fixture-global-v1:fixture-daily-v1",
        },
        "query": {
            "instruments": ["SH.600000"],
            "start": "2025-01-01",
            "end": "2025-01-31",
            "frequency": "1d",
            "adjustment": "none",
        },
        "calendar": "cn-equity-v1",
        "contract_mapping": None,
        "as_of": "2025-02-01T00:00:00Z",
        "required_semantics": ["field_availability", "point_in_time", "time"],
        "data_semantics": {
            "field_availability": {"status": "verified", "reason": "canonical bars"},
            "point_in_time": {"status": "verified", "reason": "bounded as-of"},
            "time": {"status": "verified", "reason": "trading-day close"},
            "provider_lineage": {"status": "verified", "reason": "frozen revision"},
        },
        "verification": {
            "canonical_input_hash": "5" * 64,
            "data_version": "fixture-global-v1",
            "dataset_version": "fixture-daily-v1",
            "catalog_hash": "6" * 64,
            "calendar_hash": "7" * 64,
            "coverage_hash": "8" * 64,
        },
        "resolved_at": "2025-02-01T00:00:00Z",
    }
    parameters = {
        "validation_fee_micros": 100,
        "validation_slippage_micros": 200,
        "validation_margin_micros": 300,
        "validation_liquidity_micros": 400,
    }
    backend = {"id": "primary", "adapter": "nautilus", "config": {}}
    request = {
        "schema": "quant-research.workspace-run-request.v4",
        "strategy_package": package,
        "market_snapshot": market_snapshot,
        "parameters": parameters,
        "sandbox_profile": {"profile_id": "production-oci"},
        "behavioral_conformance": {"conformance_id": "sha256:" + "a" * 64},
        "execution": {"topology": "formal_only", "formal": [backend]},
    }
    result = {
        "schema": "quant-research.result.v2",
        "outcome": "completed",
        "summary": {},
        "formal": {
            "primary": {
                "adapter": "nautilus",
                "metrics": {"sharpe_ratio": 1.25},
                "artifacts": [artifact],
            }
        },
        "artifacts": [],
    }
    request_hash = canonical_sha256(request)
    result_hash = canonical_sha256(result)
    runtime_identity = {
        "runtime": "quant-runtime",
        "engine": "nautilus",
        "engine_version": "1.231.0",
    }
    attempt = {
        "schema": "quant-research.run-attempt.v1",
        "attempt_id": attempt_id,
        "run_id": run_id,
        "attempt_number": 1,
        "status": "completed",
        "worker_id": "worker-fixture",
        "runtime_identity": runtime_identity,
        "result": result,
        "error": None,
        "created_at": "2026-09-05T00:00:00Z",
        "started_at": "2026-09-05T00:00:01Z",
        "finished_at": "2026-09-05T00:00:02Z",
    }
    workspace.runs[run_id] = {
        "schema": "quant-research.run-record.v1",
        "run_id": run_id,
        "request_hash": request_hash,
        "request": request,
        "package": {
            "package_ref": package,
            "manifest": {},
            "parameter_schema": {},
            "bundle": {},
        },
        "status": "completed",
        "current_attempt_id": attempt_id,
        "created_at": "2026-09-05T00:00:00Z",
        "updated_at": "2026-09-05T00:00:02Z",
        "result": result,
        "error": None,
        "attempts": [attempt],
    }
    hypothesis_ref, hypothesis_publication = _owner_record(
        "apex-research.hypothesis.v1",
        "hypothesis_id",
        campaign_id=campaign_ref["record_id"],
        statement="Runtime evidence remains bound.",
        source_evidence=[],
        assumptions=[],
    )
    trial_ref, trial_publication = _owner_record(
        "apex-research.trial.v1",
        "trial_id",
        study_id=campaign_ref["record_id"],
        protocol_hash=protocol_ref["record_id"],
        request_hash=request_hash,
        workspace_run_id=run_id,
        topology="formal_only",
        run_status="completed",
        discovery_present=False,
        formal_backends=["primary"],
        strategy_package_hash=package["package_hash"],
    )
    iteration_ref, iteration_publication = _owner_record(
        "apex-research.iteration.v2",
        "iteration_id",
        campaign_id=campaign_ref["record_id"],
        hypothesis_id=hypothesis_ref["record_id"],
        candidate=candidate_ref,
        strategy_package=package,
        workspace_request_id=request_hash,
        workspace_run_id=run_id,
        trial=trial_ref,
        evidence_availability="available",
    )
    workspace.records.update(
        {
            hypothesis_ref["record_id"]: hypothesis_publication,
            trial_ref["record_id"]: trial_publication,
            iteration_ref["record_id"]: iteration_publication,
        }
    )
    evidence["scope"]["hypothesis"] = hypothesis_ref
    evidence["scope"]["iteration"] = iteration_ref
    run_ref = {
        "record_id": run_id,
        "record_type": "quant-research.run-record.v1",
        "attempt_id": attempt_id,
        "request_hash": request_hash,
        "result_hash": result_hash,
    }
    extra_sources = [
        _source(hypothesis_ref, namespace="apex.control"),
        _source(iteration_ref, namespace="apex.control"),
        _source(trial_ref, namespace="apex.control"),
        _source(run_ref, namespace="formal.nautilus", canonical_owner="quant_runtime"),
    ]
    evidence["sources"] = sorted(
        [*evidence["sources"], *extra_sources],
        key=lambda item: (
            item["canonical_owner"],
            item["namespace"],
            item["record"]["record_type"],
            item["record"]["record_id"],
        ),
    )
    by_id = {item["record"]["record_id"]: item for item in evidence["sources"]}
    formal_sources = [
        item
        for item in evidence["sources"]
        if item["record"]["record_id"] in {run_id, trial_ref["record_id"]}
    ]
    evidence["sections"]["source_mapping"]["sources"] = evidence["sources"]
    for name in ("formal_results", "data_identity", "execution_costs"):
        evidence["sections"][name] = _section(
            "evaluated",
            f"Exact {name} owner facts were read back.",
            sources=formal_sources,
            outcome="pass",
        )
    snapshot_source = market_snapshot["source"]
    snapshot_query = market_snapshot["query"]
    snapshot_semantics = market_snapshot["data_semantics"]
    snapshot_verification = market_snapshot["verification"]
    evidence["runtime_formal"] = [
        {
            "run": run_ref,
            "trial": trial_ref,
            "execution": {
                "run_status": "completed",
                "result_outcome": "completed",
                "attempt_number": 1,
                "worker_id": "worker-fixture",
                "runtime_identity": runtime_identity,
                "runtime_identity_hash": canonical_sha256(runtime_identity),
                "topology": "formal_only",
                "formal_backends": [
                    {
                        "backend_id": "primary",
                        "adapter": "nautilus",
                        "request_selector": "execution.formal.0",
                        "request_hash": canonical_sha256(backend),
                    }
                ],
            },
            "metrics": [
                {
                    "backend_id": "primary",
                    "selector": "formal.primary.metrics.sharpe_ratio",
                    "value": 1.25,
                }
            ],
            "artifacts": [
                {
                    "backend_id": "primary",
                    "selector": "formal.primary.artifacts.0",
                    "artifact": artifact,
                }
            ],
            "data_identity": {
                "snapshot_id": market_snapshot["snapshot_id"],
                "snapshot_hash": canonical_sha256(market_snapshot),
                "mode": "reference",
                "trust_policy": "verified_immutable",
                "source_adapter": "markethub",
                "source_adapter_version": snapshot_source["adapter_version"],
                "endpoint_contract": snapshot_source["endpoint_contract"],
                "base_url": snapshot_source["base_url"],
                "data_revision": snapshot_source["data_revision"],
                "source_identity_hash": canonical_sha256(snapshot_source),
                "instruments": snapshot_query["instruments"],
                "start": snapshot_query["start"],
                "end": snapshot_query["end"],
                "frequency": snapshot_query["frequency"],
                "adjustment": snapshot_query["adjustment"],
                "query_hash": canonical_sha256(snapshot_query),
                "calendar": market_snapshot["calendar"],
                "contract_mapping": None,
                "as_of": market_snapshot["as_of"],
                "required_semantics": market_snapshot["required_semantics"],
                "field_availability": snapshot_semantics["field_availability"],
                "point_in_time": snapshot_semantics["point_in_time"],
                "time": snapshot_semantics["time"],
                "provider_lineage": snapshot_semantics["provider_lineage"],
                "data_semantics_hash": canonical_sha256(snapshot_semantics),
                "canonical_input_hash": snapshot_verification["canonical_input_hash"],
                "data_version": snapshot_verification["data_version"],
                "dataset_version": snapshot_verification["dataset_version"],
                "catalog_hash": snapshot_verification["catalog_hash"],
                "calendar_hash": snapshot_verification["calendar_hash"],
                "coverage_hash": snapshot_verification["coverage_hash"],
                "verification_hash": canonical_sha256(snapshot_verification),
                "resolved_at": market_snapshot["resolved_at"],
            },
            "execution_costs": {
                "fee_micros": 100,
                "slippage_micros": 200,
                "margin_micros": 300,
                "liquidity_micros": 400,
            },
            "namespace": "formal.nautilus",
            "qualification_inference": "forbidden",
            "production_approval_inference": "forbidden",
        }
    ]
    assert by_id[run_id]["canonical_owner"] == "quant_runtime"
    return _publish_source(workspace, evidence)


def test_v2_read_model_preserves_owner_evidence_without_interpretation(
    workspace: FakeWorkspace,
) -> None:
    reference = _fixture(workspace)

    model = EvidenceV2ReadModelBuilder(WorkspaceAdapter(workspace)).read(reference)

    assert model.source.source_id == reference.record_id
    assert model.source.evidence.sections.candidates.strategy.outcome == "pass"
    assert model.source.evidence.sections.failures.status == "blocked"
    assert model.source.evidence.sections.failures.blockers
    assert model.source.evidence.sections.robustness.status == "incomparable"
    assert model.source.evidence.sections.robustness.incompatibilities[0].left
    assert model.source.evidence.sections.robustness.incompatibilities[0].right
    assert model.source.evidence.sections.warnings.status == "not_evaluated"
    assert model.source.evidence.candidate_composition is not None
    assert model.source.evidence.candidate_composition.strategy.family_id == "strict-family"
    assert [item.reference.record_id for item in model.external_records] == (
        model.source.source_record_ids
    )
    assert model.qualification_inference == "forbidden"
    assert model.production_approval_inference == "forbidden"


@pytest.mark.parametrize("target", ["source", "evidence", "owner"])
def test_v2_read_model_fails_closed_on_tampered_public_readback(
    workspace: FakeWorkspace,
    target: str,
) -> None:
    reference = _fixture(workspace)
    source_publication = workspace.records[reference.record_id]
    evidence_id = source_publication["payload"]["evidence_ref"]["record_id"]
    if target == "source":
        source_publication["lineage"] = []
    elif target == "evidence":
        workspace.records[evidence_id]["payload"]["sections"]["warnings"]["reason"] = "tampered"
    else:
        owner_id = source_publication["payload"]["source_record_ids"][0]
        workspace.records[owner_id]["payload"]["title"] = "tampered"

    with pytest.raises(ContractError):
        EvidenceV2ReadModelBuilder(WorkspaceAdapter(workspace)).read(reference)


def test_v2_contract_rejects_formal_auxiliary_namespace_swap(
    workspace: FakeWorkspace,
) -> None:
    reference = _fixture(workspace)
    payload = deepcopy(workspace.records[reference.record_id]["payload"])
    strategy_id = payload["evidence"]["scope"]["candidate"]["record_id"]
    strategy_source = next(
        item
        for item in payload["evidence"]["sources"]
        if item["record"]["record_id"] == strategy_id
    )
    strategy_source["namespace"] = "auxiliary.validation"

    with pytest.raises(ValueError, match="namespace"):
        EvidenceV2StudySource.model_validate(payload, strict=True)


def test_v2_read_model_binds_runtime_request_attempt_result_and_artifact(
    workspace: FakeWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _runtime_fixture(workspace)

    monkeypatch.setattr(
        workspace,
        "list_records",
        lambda **kwargs: pytest.fail(f"v2 reader must not scan records: {kwargs}"),
    )
    model = EvidenceV2ReadModelBuilder(WorkspaceAdapter(workspace)).read(reference)

    assert len(model.source.evidence.runtime_formal) == 1
    formal = model.source.evidence.runtime_formal[0]
    assert formal.execution.formal_backends[0].request_selector == "execution.formal.0"
    assert formal.metrics[0].selector == "formal.primary.metrics.sharpe_ratio"
    assert formal.artifacts[0].selector == "formal.primary.artifacts.0"
    assert formal.data_identity is not None
    assert formal.data_identity.source_adapter == "markethub"
    assert formal.execution_costs is not None
    assert formal.execution_costs.fee_micros == 100
    runtime_readback = next(item for item in model.external_records if item.run is not None)
    assert runtime_readback.result == workspace.get_result("runtime-run-1")


def test_v2_read_model_rejects_verified_artifact_from_the_wrong_result(
    workspace: FakeWorkspace,
) -> None:
    reference = _runtime_fixture(workspace)
    run = workspace.runs["runtime-run-1"]
    result = run["result"]
    assert isinstance(result, dict)
    formal = result["formal"]
    assert isinstance(formal, dict)
    primary = formal["primary"]
    assert isinstance(primary, dict)
    primary["artifacts"] = []
    attempts = run["attempts"]
    assert isinstance(attempts, list)
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    attempt["result"] = deepcopy(result)

    with pytest.raises(ContractError):
        EvidenceV2ReadModelBuilder(WorkspaceAdapter(workspace)).read(reference)


def test_v2_read_model_preserves_supersession_without_mutating_predecessor(
    workspace: FakeWorkspace,
) -> None:
    predecessor_ref = _fixture(workspace)
    predecessor_source = deepcopy(workspace.records[predecessor_ref.record_id])
    predecessor_evidence = predecessor_source["payload"]["evidence"]
    successor_evidence = deepcopy(predecessor_evidence)
    successor_evidence["supersedes"] = {
        "record_id": predecessor_evidence["evidence_id"],
        "record_type": "apex-research.evidence.v2",
    }
    successor_ref = _publish_source(workspace, successor_evidence)

    model = EvidenceV2ReadModelBuilder(WorkspaceAdapter(workspace)).read(successor_ref)

    assert model.source.evidence.supersedes is not None
    assert model.source.evidence.supersedes.record_id == predecessor_evidence["evidence_id"]
    assert workspace.records[predecessor_ref.record_id] == predecessor_source


def test_existing_v1_renderer_is_not_extended_for_evidence_v2() -> None:
    from strategy_reporting.renderers.registry import RendererRegistry

    assert "evidence.v2" not in RendererRegistry.__dict__
