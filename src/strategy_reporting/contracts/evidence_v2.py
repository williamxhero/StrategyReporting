"""Strict presentation-side contracts for the Apex Evidence v2 study source."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, model_validator

from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.models import ArtifactRef, LineageEdge, StrictModel

Sha256 = str
InferencePolicy = Literal["forbidden"]

CanonicalOwnerName = Literal["apex_research", "quant_runtime"]
RecordReferenceShape = Literal["published", "candidate", "runtime"]
ArtifactClaimShape = Literal["none", "auxiliary", "raw_p_value", "return_series"]
ScopeBindingShape = Literal["none", "campaign", "campaign_candidate_protocol"]


@dataclass(frozen=True, slots=True)
class EvidenceRecordDescriptor:
    canonical_owner: CanonicalOwnerName
    namespace: str | None
    identity_field: str | None = None
    reference_shape: RecordReferenceShape = "published"
    artifact_claim: ArtifactClaimShape = "none"
    scope_binding: ScopeBindingShape = "none"


def _apex(
    namespace: str | None,
    identity_field: str | None = None,
    *,
    reference_shape: RecordReferenceShape = "published",
    artifact_claim: ArtifactClaimShape = "none",
    scope_binding: ScopeBindingShape = "none",
) -> EvidenceRecordDescriptor:
    return EvidenceRecordDescriptor(
        canonical_owner="apex_research",
        namespace=namespace,
        identity_field=identity_field,
        reference_shape=reference_shape,
        artifact_claim=artifact_claim,
        scope_binding=scope_binding,
    )


EVIDENCE_RECORD_DESCRIPTORS: Mapping[str, EvidenceRecordDescriptor] = {
    "apex-research.action-reservation.v1": _apex("statistical.control", "reservation_id"),
    "apex-research.action-settlement.v1": _apex("statistical.control", "settlement_id"),
    "apex-research.auxiliary-validation.v1": _apex(
        "auxiliary.validation",
        "auxiliary_id",
        artifact_claim="auxiliary",
        scope_binding="campaign_candidate_protocol",
    ),
    "apex-research.behavioral-gate-assessment.v1": _apex(
        "candidate_gate.behavioral", "assessment_id"
    ),
    "apex-research.behavioral-gate-request.v1": _apex("candidate_gate.behavioral", "request_id"),
    "apex-research.campaign-trial-census.v1": _apex("statistical.control", "census_id"),
    "apex-research.campaign.v1": _apex("apex.control", "campaign_id"),
    "apex-research.candidate-gate-assessment.v1": _apex(
        "candidate_gate.aggregate", "assessment_id"
    ),
    "apex-research.candidate-gate-campaign-binding.v1": _apex(
        "candidate_gate.policy", "binding_id"
    ),
    "apex-research.candidate-gate-policy.v1": _apex("candidate_gate.policy", "policy_id"),
    "apex-research.dependence-evidence.v1": _apex("statistical.control"),
    "apex-research.evidence.v2": _apex(None),
    "apex-research.factor-candidate.v1": _apex(
        "discovery.non_formal", "revision_id", reference_shape="candidate"
    ),
    "apex-research.failure.v1": _apex("apex.control", "failure_id", scope_binding="campaign"),
    "apex-research.failure.v2": _apex("apex.control", "failure_id", scope_binding="campaign"),
    "apex-research.hypothesis.v1": _apex("apex.control", "hypothesis_id"),
    "apex-research.iteration.v2": _apex("apex.control", "iteration_id"),
    "apex-research.model-candidate.v1": _apex(
        "discovery.non_formal", "revision_id", reference_shape="candidate"
    ),
    "apex-research.raw-p-value-evidence.v1": _apex(
        "statistical.raw", "evidence_id", artifact_claim="raw_p_value"
    ),
    "apex-research.spec-030-evidence-source.v1": _apex(
        "discovery.co_evolution",
        "source_id",
        scope_binding="campaign_candidate_protocol",
    ),
    "apex-research.spec-032-currency-source.v1": _apex(
        "evidence.currency",
        "source_id",
        scope_binding="campaign_candidate_protocol",
    ),
    "apex-research.spec-032-revalidation-source.v1": _apex(
        "evidence.revalidation",
        "source_id",
        scope_binding="campaign_candidate_protocol",
    ),
    "apex-research.statistical-assessment.v1": _apex("statistical.control", "assessment_id"),
    "apex-research.statistical-control-policy.v1": _apex("statistical.control", "policy_id"),
    "apex-research.statistical-selection-snapshot.v1": _apex("statistical.control", "selection_id"),
    "apex-research.statistical-test-family.v1": _apex("statistical.control", "family_id"),
    "apex-research.statistical-test-result.v1": _apex("statistical.raw"),
    "apex-research.strategy-candidate.v1": _apex(
        "strategy.composition", "revision_id", reference_shape="candidate"
    ),
    "apex-research.strategy-static-gate-assessment.v1": _apex(
        "candidate_gate.static", "assessment_id"
    ),
    "apex-research.trial.v1": _apex("apex.control", "trial_id"),
    "apex-research.validation-cell-matrix.v1": _apex("validation.matrix", "matrix_id"),
    "apex-research.validation-cell-outcome.v1": _apex("validation.matrix", "outcome_id"),
    "apex-research.validation-cell-state.v1": _apex("validation.matrix", "state_id"),
    "apex-research.validation-cell.v1": _apex("validation.matrix", "cell_id"),
    "apex-research.validation-eligibility.v1": _apex("validation.matrix", "eligibility_id"),
    "apex-research.validation-evidence.v1": _apex("validation.matrix", "evidence_id"),
    "apex-research.validation-protocol-matrix.v1": _apex("apex.control", "protocol_id"),
    "apex-research.verified-return-series.v1": _apex(
        "statistical.deflated_sharpe", "series_id", artifact_claim="return_series"
    ),
    "quant-research.result.v4": EvidenceRecordDescriptor(
        canonical_owner="quant_runtime", namespace="formal.nautilus"
    ),
    "quant-research.run-record.v1": EvidenceRecordDescriptor(
        canonical_owner="quant_runtime",
        namespace="formal.nautilus",
        reference_shape="runtime",
    ),
}


def evidence_record_descriptor(record_type: str) -> EvidenceRecordDescriptor:
    try:
        return EVIDENCE_RECORD_DESCRIPTORS[record_type]
    except KeyError as exc:
        raise ValueError("Evidence source record type is unsupported") from exc


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class StrategyPackageRef(StrictModel):
    schema_id: Literal["quant-research.strategy-package-ref.v1"] = Field(alias="schema")
    strategy_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class StudyRecordRef(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)


class EvidenceV2SourceRef(StudyRecordRef):
    record_type: Literal["apex-research.study-report-source.v2"] = (
        "apex-research.study-report-source.v2"
    )


class EvidenceRecordRef(StudyRecordRef):
    attempt_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    request_hash: str | None = Field(default=None, exclude_if=lambda value: value is None)
    result_hash: str | None = Field(default=None, exclude_if=lambda value: value is None)
    semantic_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    family_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    revision: int | None = Field(
        default=None,
        ge=1,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def verify_shape(self) -> EvidenceRecordRef:
        descriptor = evidence_record_descriptor(self.record_type)
        if descriptor.reference_shape == "runtime":
            if not self.attempt_id or not self.request_hash or not self.result_hash:
                raise ValueError("Runtime run reference is incomplete")
            if not _is_sha256(self.request_hash) or not _is_sha256(self.result_hash):
                raise ValueError("Runtime run reference hashes are invalid")
            if any(
                value is not None for value in (self.semantic_id, self.family_id, self.revision)
            ):
                raise ValueError("Runtime run reference carries Candidate fields")
        elif descriptor.reference_shape == "candidate":
            if (
                not _is_sha256(self.record_id)
                or not self.semantic_id
                or not _is_sha256(self.semantic_id)
                or not self.family_id
                or self.revision is None
            ):
                raise ValueError("Candidate revision reference is incomplete")
            if any(
                value is not None
                for value in (self.attempt_id, self.request_hash, self.result_hash)
            ):
                raise ValueError("Candidate revision reference carries Runtime fields")
        else:
            if not _is_sha256(self.record_id):
                raise ValueError("published Evidence source record_id must be SHA-256")
            if any(
                value is not None
                for value in (
                    self.attempt_id,
                    self.request_hash,
                    self.result_hash,
                    self.semantic_id,
                    self.family_id,
                    self.revision,
                )
            ):
                raise ValueError("published Evidence source reference has unexpected fields")
        return self


class EvidenceSourceRef(StrictModel):
    canonical_owner: Literal[
        "apex_research",
        "strategy_workspace",
        "quant_runtime",
        "markethub",
        "external_validator",
    ]
    namespace: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9_.-]*$",
    )
    record: EvidenceRecordRef

    @property
    def canonical_key(self) -> tuple[str, str, str, str]:
        return (
            self.canonical_owner,
            self.namespace,
            self.record.record_type,
            self.record.record_id,
        )

    @model_validator(mode="after")
    def verify_owner_namespace(self) -> EvidenceSourceRef:
        descriptor = evidence_record_descriptor(self.record.record_type)
        if self.canonical_owner != descriptor.canonical_owner:
            raise ValueError("Evidence source canonical owner mismatch")
        if descriptor.namespace is None or self.namespace != descriptor.namespace:
            raise ValueError("Evidence source namespace mismatch")
        return self


class EvidenceIncompatibilityAxis(StrictModel):
    axis: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    left: EvidenceSourceRef
    right: EvidenceSourceRef

    @property
    def canonical_key(self) -> tuple[object, ...]:
        return (self.axis, self.left.canonical_key, self.right.canonical_key)

    @model_validator(mode="after")
    def distinct_sides(self) -> EvidenceIncompatibilityAxis:
        if self.left == self.right:
            raise ValueError("incompatibility axis requires distinct source sides")
        return self


class EvidenceSection(StrictModel):
    status: Literal["evaluated", "not_evaluated", "blocked", "incomparable"]
    reason: str = Field(min_length=1)
    sources: list[EvidenceSourceRef]
    outcome: Literal["pass", "fail"] | None = None
    blockers: list[EvidenceSourceRef]
    incompatibilities: list[EvidenceIncompatibilityAxis]

    @model_validator(mode="after")
    def verify_closed_state(self) -> EvidenceSection:
        source_keys = [item.canonical_key for item in self.sources]
        blocker_keys = [item.canonical_key for item in self.blockers]
        axes = [item.canonical_key for item in self.incompatibilities]
        if source_keys != sorted(source_keys) or len(source_keys) != len(set(source_keys)):
            raise ValueError("section sources must be unique and canonically ordered")
        if blocker_keys != sorted(blocker_keys) or len(blocker_keys) != len(set(blocker_keys)):
            raise ValueError("section blockers must be unique and canonically ordered")
        if axes != sorted(axes) or len(axes) != len(set(axes)):
            raise ValueError("section incompatibilities must be unique and canonical")
        if self.status == "evaluated":
            if not self.sources or self.blockers or self.incompatibilities:
                raise ValueError("evaluated section requires only canonical owner sources")
        elif self.status == "not_evaluated":
            if self.outcome is not None or self.blockers or self.incompatibilities:
                raise ValueError("not_evaluated section cannot carry a result or other state")
        elif self.status == "blocked":
            if not self.blockers or self.outcome is not None or self.incompatibilities:
                raise ValueError("blocked section requires exact blocker owner facts")
            if not set(blocker_keys) <= set(source_keys):
                raise ValueError("blocked section omits a blocker owner fact")
        else:
            if not self.incompatibilities or self.outcome is not None or self.blockers:
                raise ValueError("incomparable section requires only frozen axes")
            required = {
                source.canonical_key
                for axis in self.incompatibilities
                for source in (axis.left, axis.right)
            }
            if not required <= set(source_keys):
                raise ValueError("incomparable section omits an axis source side")
        return self


class CandidateEvidenceSections(StrictModel):
    factor: EvidenceSection
    model: EvidenceSection
    strategy: EvidenceSection

    def all_sections(self) -> list[EvidenceSection]:
        return [self.factor, self.model, self.strategy]


class EvidenceSections(StrictModel):
    source_mapping: EvidenceSection
    candidates: CandidateEvidenceSections
    candidate_gates: EvidenceSection
    data_identity: EvidenceSection
    execution_costs: EvidenceSection
    formal_results: EvidenceSection
    validation_matrix: EvidenceSection
    statistical_controls: EvidenceSection
    robustness: EvidenceSection
    auxiliary_validation: EvidenceSection
    failures: EvidenceSection
    warnings: EvidenceSection
    limitations: EvidenceSection
    co_evolution: EvidenceSection
    currency: EvidenceSection
    revalidation: EvidenceSection

    def all_sections(self) -> list[EvidenceSection]:
        return [
            self.source_mapping,
            *self.candidates.all_sections(),
            self.candidate_gates,
            self.data_identity,
            self.execution_costs,
            self.formal_results,
            self.validation_matrix,
            self.statistical_controls,
            self.robustness,
            self.auxiliary_validation,
            self.failures,
            self.warnings,
            self.limitations,
            self.co_evolution,
            self.currency,
            self.revalidation,
        ]


class EvidenceCandidateComposition(StrictModel):
    factors: list[EvidenceRecordRef]
    models: list[EvidenceRecordRef]
    strategy: EvidenceRecordRef
    factor_namespace: Literal["discovery.non_formal"]
    model_namespace: Literal["discovery.non_formal"]
    formal_source: Literal["strategy_package_only"]

    @model_validator(mode="after")
    def verify_graph(self) -> EvidenceCandidateComposition:
        if any(item.record_type != "apex-research.factor-candidate.v1" for item in self.factors):
            raise ValueError("FactorCandidate graph contains a non-factor record")
        if any(item.record_type != "apex-research.model-candidate.v1" for item in self.models):
            raise ValueError("ModelCandidate graph contains a non-model record")
        if self.strategy.record_type != "apex-research.strategy-candidate.v1":
            raise ValueError("StrategyCandidate graph contains a non-strategy record")
        for values in (self.factors, self.models):
            keys = [
                (item.family_id, item.revision, item.semantic_id, item.record_id) for item in values
            ]
            if keys != sorted(keys) or len(keys) != len(set(keys)):
                raise ValueError("Candidate graph must be unique and canonical")
        return self


class EvidenceCandidateGateBinding(StrictModel):
    policy: EvidenceRecordRef
    campaign_binding: EvidenceRecordRef
    static_assessment: EvidenceRecordRef
    behavioral_request: EvidenceRecordRef
    behavioral_assessment: EvidenceRecordRef
    aggregate_assessment: EvidenceRecordRef
    formal_inference: InferencePolicy
    qualification_inference: InferencePolicy

    def records(self) -> list[EvidenceRecordRef]:
        return [
            self.policy,
            self.campaign_binding,
            self.static_assessment,
            self.behavioral_request,
            self.behavioral_assessment,
            self.aggregate_assessment,
        ]

    @model_validator(mode="after")
    def verify_types(self) -> EvidenceCandidateGateBinding:
        expected = [
            "apex-research.candidate-gate-policy.v1",
            "apex-research.candidate-gate-campaign-binding.v1",
            "apex-research.strategy-static-gate-assessment.v1",
            "apex-research.behavioral-gate-request.v1",
            "apex-research.behavioral-gate-assessment.v1",
            "apex-research.candidate-gate-assessment.v1",
        ]
        if [item.record_type for item in self.records()] != expected:
            raise ValueError("Candidate gate binding types or order differ")
        return self


class RuntimeFormalBackendIdentity(StrictModel):
    backend_id: str = Field(min_length=1)
    adapter: Literal["nautilus"]
    request_selector: str = Field(min_length=1)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeFormalMetric(StrictModel):
    backend_id: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    value: str | int | float | bool | None


class RuntimeArtifactMembership(StrictModel):
    backend_id: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    artifact: ArtifactRef


class RuntimeDataSemantic(StrictModel):
    status: Literal["verified", "not_evaluated", "unavailable"]
    reason: str = Field(min_length=1)


class RuntimeDataIdentity(StrictModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["reference"]
    trust_policy: Literal["verified_immutable"]
    source_adapter: Literal["markethub"]
    source_adapter_version: str = Field(min_length=1)
    endpoint_contract: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    data_revision: str = Field(min_length=1)
    source_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    instruments: list[str] = Field(min_length=1)
    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    adjustment: str = Field(min_length=1)
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    calendar: str = Field(min_length=1)
    contract_mapping: str | None
    as_of: str = Field(min_length=1)
    required_semantics: list[str]
    field_availability: RuntimeDataSemantic
    point_in_time: RuntimeDataSemantic
    time: RuntimeDataSemantic
    provider_lineage: RuntimeDataSemantic
    data_semantics_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    catalog_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    calendar_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_at: str = Field(min_length=1)


class RuntimeExecutionCosts(StrictModel):
    fee_micros: int = Field(ge=0)
    slippage_micros: int = Field(ge=0)
    margin_micros: int = Field(ge=0)
    liquidity_micros: int = Field(ge=0)


class RuntimeExecutionIdentity(StrictModel):
    run_status: Literal["completed", "rejected"]
    result_outcome: Literal["completed", "rejected"]
    attempt_number: int = Field(ge=1)
    worker_id: str | None
    runtime_identity: dict[str, Any]
    runtime_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    topology: Literal["formal_only", "discovery_formal", "formal_comparison", "agreement_gate"]
    formal_backends: list[RuntimeFormalBackendIdentity] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_identity(self) -> RuntimeExecutionIdentity:
        if self.runtime_identity_hash != canonical_sha256(self.runtime_identity):
            raise ValueError("Runtime execution identity hash mismatch")
        return self


class RuntimeFormalEvidence(StrictModel):
    run: EvidenceRecordRef
    trial: EvidenceRecordRef
    execution: RuntimeExecutionIdentity
    metrics: list[RuntimeFormalMetric]
    artifacts: list[RuntimeArtifactMembership]
    data_identity: RuntimeDataIdentity | None
    execution_costs: RuntimeExecutionCosts | None
    namespace: Literal["formal.nautilus"]
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy

    @model_validator(mode="after")
    def verify_facts(self) -> RuntimeFormalEvidence:
        if (
            self.run.record_type != "quant-research.run-record.v1"
            or self.trial.record_type != "apex-research.trial.v1"
        ):
            raise ValueError("Runtime formal owner references are invalid")
        metric_keys = [(item.selector, item.backend_id) for item in self.metrics]
        artifact_keys = [(item.selector, item.artifact.sha256) for item in self.artifacts]
        if metric_keys != sorted(metric_keys) or len(metric_keys) != len(set(metric_keys)):
            raise ValueError("Runtime metrics must be unique and canonical")
        if artifact_keys != sorted(artifact_keys) or len(artifact_keys) != len(set(artifact_keys)):
            raise ValueError("Runtime artifacts must be unique and canonical")
        return self


class EvidenceValidationCell(StrictModel):
    ordinal: int = Field(ge=0, le=9_999)
    cell: EvidenceRecordRef
    state: EvidenceRecordRef | None
    outcome: EvidenceRecordRef | None
    runtime: EvidenceRecordRef | None
    source_status: Literal[
        "completed",
        "formally_rejected",
        "failed",
        "blocked",
        "skipped",
        "missing",
        "reconciliation_required",
    ]
    reason: str = Field(min_length=1)
    section: EvidenceSection

    @model_validator(mode="after")
    def verify_cell(self) -> EvidenceValidationCell:
        if self.cell.record_type != "apex-research.validation-cell.v1":
            raise ValueError("validation cell reference type differs")
        if self.state and self.state.record_type != "apex-research.validation-cell-state.v1":
            raise ValueError("validation state reference type differs")
        if self.outcome and self.outcome.record_type != "apex-research.validation-cell-outcome.v1":
            raise ValueError("validation outcome reference type differs")
        if self.runtime and self.runtime.record_type != "quant-research.run-record.v1":
            raise ValueError("validation Runtime reference type differs")
        if self.source_status == "missing":
            if self.state or self.outcome or self.runtime:
                raise ValueError("missing validation cell carries terminal records")
        elif self.state is None:
            raise ValueError("terminal validation cell lacks an exact state record")
        if self.source_status in {"completed", "formally_rejected"}:
            expected = "pass" if self.source_status == "completed" else "fail"
            if (
                self.outcome is None
                or self.runtime is None
                or self.section.status != "evaluated"
                or self.section.outcome != expected
            ):
                raise ValueError("covered validation cell evidence is incomplete")
        elif self.source_status == "blocked":
            if self.section.status != "blocked":
                raise ValueError("blocked validation cell lacks blocker evidence")
        elif self.section.status != "not_evaluated":
            raise ValueError("unexecuted validation cell must remain not_evaluated")
        return self


class EvidenceValidationDimensionMember(StrictModel):
    member_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: Literal[
        "cost",
        "in_sample",
        "out_of_sample",
        "regime",
        "sensitivity",
        "universe",
        "validation",
        "walk_forward",
    ]
    label: str = Field(min_length=1)
    cells: list[EvidenceRecordRef] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_member(self) -> EvidenceValidationDimensionMember:
        keys = [(item.record_type, item.record_id) for item in self.cells]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("validation dimension member cells must be canonical")
        identity = {
            "dimension": self.dimension,
            "label": self.label,
            "cells": [item.model_dump(mode="json", by_alias=True) for item in self.cells],
        }
        if self.member_id != canonical_sha256(identity):
            raise ValueError("validation dimension member identity differs")
        return self


class EvidenceValidationDimension(StrictModel):
    dimension: Literal[
        "cost",
        "in_sample",
        "out_of_sample",
        "regime",
        "sensitivity",
        "universe",
        "validation",
        "walk_forward",
    ]
    members: list[EvidenceValidationDimensionMember] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_dimension(self) -> EvidenceValidationDimension:
        labels = [item.label for item in self.members]
        if labels != sorted(labels) or len(labels) != len(set(labels)):
            raise ValueError("validation dimension members must be unique and canonical")
        if any(item.dimension != self.dimension for item in self.members):
            raise ValueError("validation dimension member scope differs")
        return self


class EvidenceValidationCoverage(StrictModel):
    protocol: EvidenceRecordRef
    matrix: EvidenceRecordRef
    evidence: EvidenceRecordRef
    denominator: int = Field(ge=1, le=10_000)
    cells: list[EvidenceValidationCell] = Field(min_length=1)
    status_counts: dict[str, int]
    covered_cells: int = Field(ge=0, le=10_000)
    complete: bool
    dimensions: list[EvidenceValidationDimension] = Field(min_length=8, max_length=8)
    incompatibilities: list[EvidenceIncompatibilityAxis]
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy

    def records(self) -> list[EvidenceRecordRef]:
        values = [self.protocol, self.matrix, self.evidence]
        for cell in self.cells:
            values.append(cell.cell)
            values.extend(item for item in (cell.state, cell.outcome, cell.runtime) if item)
            values.extend(source.record for source in cell.section.sources)
        values.extend(
            source.record for axis in self.incompatibilities for source in (axis.left, axis.right)
        )
        by_key = {(item.record_type, item.record_id): item for item in values}
        return [by_key[key] for key in sorted(by_key)]

    @model_validator(mode="after")
    def verify_coverage(self) -> EvidenceValidationCoverage:
        if (
            self.protocol.record_type != "apex-research.validation-protocol-matrix.v1"
            or self.matrix.record_type != "apex-research.validation-cell-matrix.v1"
            or self.evidence.record_type != "apex-research.validation-evidence.v1"
        ):
            raise ValueError("validation coverage owner record types differ")
        if self.denominator != len(self.cells):
            raise ValueError("validation denominator cannot shrink")
        if [item.ordinal for item in self.cells] != list(range(self.denominator)):
            raise ValueError("validation cells do not preserve frozen matrix order")
        counts: dict[str, int] = {}
        for item in self.cells:
            counts[item.source_status] = counts.get(item.source_status, 0) + 1
        if self.status_counts != dict(sorted(counts.items())):
            raise ValueError("validation status-count denominator differs")
        if self.covered_cells != sum(
            item.source_status in {"completed", "formally_rejected"} for item in self.cells
        ):
            raise ValueError("validation covered-cell count differs")
        if self.complete != all(item.source_status == "completed" for item in self.cells):
            raise ValueError("validation completeness differs")
        expected_names = [
            "cost",
            "in_sample",
            "out_of_sample",
            "regime",
            "sensitivity",
            "universe",
            "validation",
            "walk_forward",
        ]
        if [item.dimension for item in self.dimensions] != expected_names:
            raise ValueError("validation dimension set is incomplete")
        expected_cells = {(item.cell.record_type, item.cell.record_id) for item in self.cells}
        for dimension in self.dimensions:
            member_cells = [
                (cell.record_type, cell.record_id)
                for member in dimension.members
                for cell in member.cells
            ]
            if len(member_cells) != self.denominator or set(member_cells) != expected_cells:
                raise ValueError("validation dimension denominator differs")
        axes = [item.canonical_key for item in self.incompatibilities]
        if axes != sorted(axes) or len(axes) != len(set(axes)):
            raise ValueError("validation incompatibility axes must be canonical")
        return self


class EvidenceStatisticalControl(StrictModel):
    assessment_ref: EvidenceRecordRef
    assessment: dict[str, Any]
    policy: EvidenceRecordRef
    family: EvidenceRecordRef
    census: EvidenceRecordRef
    selection: EvidenceRecordRef
    test_denominator: int = Field(ge=1)
    test_ids: list[str] = Field(min_length=1)
    raw_evidence: list[EvidenceRecordRef]
    raw_test_ids: list[str]
    raw_owner_sources: list[EvidenceRecordRef]
    missing_test_ids: list[str]
    trial_denominator: int = Field(ge=0)
    trial_sources: list[EvidenceRecordRef]
    cost_fact_sources: list[EvidenceRecordRef]
    return_series: list[EvidenceRecordRef]
    return_owner_sources: list[EvidenceRecordRef]
    missing_return_series_ids: list[str]
    dependence_source: EvidenceRecordRef | None
    validation_denominator: int = Field(ge=1)
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy

    def records(self) -> list[EvidenceRecordRef]:
        values = [
            self.assessment_ref,
            self.policy,
            self.family,
            self.census,
            self.selection,
            *self.raw_evidence,
            *self.raw_owner_sources,
            *self.trial_sources,
            *self.cost_fact_sources,
            *self.return_series,
            *self.return_owner_sources,
        ]
        if self.dependence_source:
            values.append(self.dependence_source)
        by_key = {(item.record_type, item.record_id): item for item in values}
        return [by_key[key] for key in sorted(by_key)]

    @model_validator(mode="after")
    def verify_complete_family(self) -> EvidenceStatisticalControl:
        expected_types = (
            "apex-research.statistical-assessment.v1",
            "apex-research.statistical-control-policy.v1",
            "apex-research.statistical-test-family.v1",
            "apex-research.campaign-trial-census.v1",
            "apex-research.statistical-selection-snapshot.v1",
        )
        if (
            self.assessment_ref.record_type,
            self.policy.record_type,
            self.family.record_type,
            self.census.record_type,
            self.selection.record_type,
        ) != expected_types:
            raise ValueError("statistical predecessor record types differ")
        if self.assessment.get("assessment_id") != self.assessment_ref.record_id:
            raise ValueError("statistical assessment identity differs")
        for field, reference in (
            ("policy", self.policy),
            ("family", self.family),
            ("census", self.census),
            ("selection", self.selection),
        ):
            if self.assessment.get(field) != {
                "record_id": reference.record_id,
                "record_type": reference.record_type,
            }:
                raise ValueError("statistical predecessor binding differs")
        if (
            self.test_denominator != len(self.test_ids)
            or self.test_ids != sorted(self.test_ids)
            or len(self.test_ids) != len(set(self.test_ids))
            or set(self.raw_test_ids) | set(self.missing_test_ids) != set(self.test_ids)
            or set(self.raw_test_ids) & set(self.missing_test_ids)
            or len(self.raw_test_ids) != len(self.raw_evidence)
            or len(self.raw_owner_sources) != len(self.raw_evidence)
            or self.raw_test_ids != sorted(self.raw_test_ids)
            or self.missing_test_ids != sorted(self.missing_test_ids)
        ):
            raise ValueError("statistical test-family denominator differs")
        if self.trial_denominator != len(self.trial_sources):
            raise ValueError("statistical trial denominator differs")
        if len(_record_keys(self.trial_sources)) != len(self.trial_sources):
            raise ValueError("statistical trial source set contains duplicates")
        multiple_testing = self.assessment.get("multiple_testing")
        deflated_sharpe = self.assessment.get("deflated_sharpe")
        if not isinstance(multiple_testing, dict) or not isinstance(deflated_sharpe, dict):
            raise ValueError("statistical assessment controls are not structured")
        raw_ids = multiple_testing.get("raw_evidence_ids")
        if raw_ids != sorted(item.record_id for item in self.raw_evidence):
            raise ValueError("statistical raw evidence source set differs")
        source_series_ids = deflated_sharpe.get("source_series_ids")
        if not isinstance(source_series_ids, list) or (
            {item.record_id for item in self.return_series} | set(self.missing_return_series_ids)
            != set(source_series_ids)
            or {item.record_id for item in self.return_series} & set(self.missing_return_series_ids)
            or len(self.return_series) != len(self.return_owner_sources)
        ):
            raise ValueError("Deflated Sharpe return-series source set differs")
        for name in ("holm", "benjamini_hochberg"):
            correction = multiple_testing.get(name)
            if not isinstance(correction, dict) or not isinstance(correction.get("items"), list):
                raise ValueError("statistical correction evidence is not structured")
            if [item.get("test_id") for item in correction["items"]] != self.test_ids:
                raise ValueError("statistical correction family order differs")
        return self


class EvidenceHonestyBinding(StrictModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovered_record_count: int = Field(ge=0, le=100_000)
    campaign_failures: list[EvidenceRecordRef]
    failure_records: list[EvidenceRecordRef]
    warning_records: list[EvidenceRecordRef]
    limitation_records: list[EvidenceRecordRef]
    robustness_records: list[EvidenceRecordRef]
    auxiliary_records: list[EvidenceRecordRef]
    co_evolution_records: list[EvidenceRecordRef]
    currency_records: list[EvidenceRecordRef]
    revalidation_records: list[EvidenceRecordRef]
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy

    def records(self) -> list[EvidenceRecordRef]:
        values = [
            *self.failure_records,
            *self.warning_records,
            *self.limitation_records,
            *self.robustness_records,
            *self.auxiliary_records,
            *self.co_evolution_records,
            *self.currency_records,
            *self.revalidation_records,
        ]
        by_key = {(item.record_type, item.record_id): item for item in values}
        return [by_key[key] for key in sorted(by_key)]

    @model_validator(mode="after")
    def verify_complete_sets(self) -> EvidenceHonestyBinding:
        for label, records in (
            ("campaign failures", self.campaign_failures),
            ("failure records", self.failure_records),
            ("warning records", self.warning_records),
            ("limitation records", self.limitation_records),
            ("robustness records", self.robustness_records),
            ("auxiliary records", self.auxiliary_records),
            ("co-evolution records", self.co_evolution_records),
            ("currency records", self.currency_records),
            ("revalidation records", self.revalidation_records),
        ):
            keys = [(item.record_type, item.record_id) for item in records]
            if keys != sorted(keys) or len(keys) != len(set(keys)):
                raise ValueError(f"Evidence honesty {label} must be unique and canonical")
        if not _record_keys(self.campaign_failures) <= _record_keys(self.failure_records):
            raise ValueError("Evidence honesty omits a campaign failure")
        if self.discovered_record_count != sum(
            len(records)
            for records in (
                self.campaign_failures,
                self.auxiliary_records,
                self.co_evolution_records,
                self.currency_records,
                self.revalidation_records,
            )
        ):
            raise ValueError("Evidence honesty discovered-record denominator differs")
        return self


class EvidenceV2Scope(StrictModel):
    campaign: EvidenceRecordRef
    protocol: EvidenceRecordRef
    candidate: EvidenceRecordRef
    strategy_package: StrategyPackageRef
    hypothesis: EvidenceRecordRef | None
    iteration: EvidenceRecordRef | None

    @model_validator(mode="after")
    def verify_scope(self) -> EvidenceV2Scope:
        expected = (
            "apex-research.campaign.v1",
            "apex-research.validation-protocol-matrix.v1",
            "apex-research.strategy-candidate.v1",
        )
        if (
            self.campaign.record_type,
            self.protocol.record_type,
            self.candidate.record_type,
        ) != expected:
            raise ValueError("Evidence v2 scope record types differ")
        if (self.hypothesis is None) != (self.iteration is None):
            raise ValueError("campaign hypothesis and iteration must be present together")
        if self.hypothesis and self.hypothesis.record_type != "apex-research.hypothesis.v1":
            raise ValueError("Evidence hypothesis scope type differs")
        if self.iteration and self.iteration.record_type != "apex-research.iteration.v2":
            raise ValueError("Evidence iteration scope type differs")
        return self


def _record_keys(records: list[EvidenceRecordRef]) -> set[tuple[str, str]]:
    return {(item.record_type, item.record_id) for item in records}


def _matching_sources(
    sources: list[EvidenceSourceRef], records: list[EvidenceRecordRef]
) -> list[EvidenceSourceRef]:
    keys = _record_keys(records)
    return [item for item in sources if (item.record.record_type, item.record.record_id) in keys]


class EvidenceV2(StrictModel):
    schema_id: Literal["apex-research.evidence.v2"] = Field(alias="schema")
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: EvidenceV2Scope
    sources: list[EvidenceSourceRef] = Field(min_length=1)
    sections: EvidenceSections
    candidate_composition: EvidenceCandidateComposition | None
    candidate_gate: EvidenceCandidateGateBinding | None
    runtime_formal: list[RuntimeFormalEvidence]
    validation_coverage: EvidenceValidationCoverage | None
    statistical_control: EvidenceStatisticalControl | None
    honesty: EvidenceHonestyBinding | None
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy
    supersedes: EvidenceRecordRef | None

    @model_validator(mode="after")
    def verify_identity_and_closure(self) -> EvidenceV2:
        keys = [item.canonical_key for item in self.sources]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("Evidence sources must be unique and canonically ordered")
        declared = set(keys)
        used = {
            source.canonical_key
            for section in self.sections.all_sections()
            for source in section.sources
        }
        if declared != used:
            raise ValueError("Evidence source set differs from section source closure")
        scope_records = [self.scope.campaign, self.scope.protocol, self.scope.candidate]
        if self.scope.hypothesis and self.scope.iteration:
            scope_records.extend((self.scope.hypothesis, self.scope.iteration))
        for record in scope_records:
            if sum(source.record == record for source in self.sources) != 1:
                raise ValueError("Evidence source set omits or changes a scoped owner record")
        if self.candidate_composition:
            candidate_records = [
                *self.candidate_composition.factors,
                *self.candidate_composition.models,
                self.candidate_composition.strategy,
            ]
            if self.candidate_composition.strategy != self.scope.candidate:
                raise ValueError("Candidate composition and Evidence scope differ")
            for record in candidate_records:
                if sum(source.record == record for source in self.sources) != 1:
                    raise ValueError("Evidence source set omits a Candidate graph record")
        if self.candidate_gate:
            expected = _matching_sources(self.sources, self.candidate_gate.records())
            if self.sections.candidate_gates.sources != expected:
                raise ValueError("Candidate gate section source closure differs")
        runtime_records = [
            record for item in self.runtime_formal for record in (item.run, item.trial)
        ]
        if self.runtime_formal:
            if self.scope.iteration is None:
                raise ValueError("Runtime formal evidence requires campaign iteration scope")
            runtime_keys = [
                (item.run.record_id, item.run.attempt_id) for item in self.runtime_formal
            ]
            if runtime_keys != sorted(runtime_keys) or len(runtime_keys) != len(set(runtime_keys)):
                raise ValueError("Runtime formal evidence order differs")
            expected = _matching_sources(self.sources, runtime_records)
            if self.sections.formal_results.sources != expected:
                raise ValueError("formal result section source closure differs")
            expected_data = _matching_sources(
                self.sources,
                [
                    record
                    for item in self.runtime_formal
                    if item.data_identity is not None
                    for record in (item.run, item.trial)
                ],
            )
            expected_cost = _matching_sources(
                self.sources,
                [
                    record
                    for item in self.runtime_formal
                    if item.execution_costs is not None
                    for record in (item.run, item.trial)
                ],
            )
            if self.sections.data_identity.sources != expected_data:
                raise ValueError("data identity section source closure differs")
            if self.sections.execution_costs.sources != expected_cost:
                raise ValueError("execution cost section source closure differs")
        elif any(
            section.sources
            for section in (
                self.sections.formal_results,
                self.sections.data_identity,
                self.sections.execution_costs,
            )
        ):
            raise ValueError("formal sections carry sources without Runtime evidence")
        if self.validation_coverage:
            expected = _matching_sources(self.sources, self.validation_coverage.records())
            if self.sections.validation_matrix.sources != expected:
                raise ValueError("validation section source closure differs")
            if self.validation_coverage.protocol != self.scope.protocol:
                raise ValueError("validation protocol scope differs")
        elif self.sections.validation_matrix.sources:
            raise ValueError("validation sources require typed validation coverage")
        if self.statistical_control:
            expected = _matching_sources(self.sources, self.statistical_control.records())
            if self.sections.statistical_controls.sources != expected:
                raise ValueError("statistical section source closure differs")
            if (
                not self.validation_coverage
                or self.statistical_control.validation_denominator
                != self.validation_coverage.denominator
            ):
                raise ValueError("statistical validation denominator scope differs")
        elif self.sections.statistical_controls.sources:
            raise ValueError("statistical sources require typed statistical control")
        if self.honesty:
            expected = _matching_sources(self.sources, self.honesty.records())
            if len(expected) != len(self.honesty.records()):
                raise ValueError("honesty source closure differs")
            expected_sections = (
                (self.sections.robustness, self.honesty.robustness_records),
                (self.sections.auxiliary_validation, self.honesty.auxiliary_records),
                (self.sections.failures, self.honesty.failure_records),
                (self.sections.warnings, self.honesty.warning_records),
                (self.sections.limitations, self.honesty.limitation_records),
                (self.sections.co_evolution, self.honesty.co_evolution_records),
                (self.sections.currency, self.honesty.currency_records),
                (self.sections.revalidation, self.honesty.revalidation_records),
            )
            for section, records in expected_sections:
                if section.sources != _matching_sources(self.sources, records):
                    raise ValueError("honesty section source closure differs")
            auxiliary_keys = {
                source.canonical_key for source in self.sections.auxiliary_validation.sources
            }
            formal_keys = {
                source.canonical_key
                for section in (
                    self.sections.formal_results,
                    self.sections.data_identity,
                    self.sections.execution_costs,
                    self.sections.validation_matrix,
                    self.sections.statistical_controls,
                )
                for source in section.sources
            }
            if auxiliary_keys & formal_keys:
                raise ValueError("auxiliary evidence cannot satisfy a formal source requirement")
        if self.supersedes and (
            self.supersedes.record_type != "apex-research.evidence.v2"
            or self.supersedes.record_id == self.evidence_id
        ):
            raise ValueError("Evidence supersession reference is invalid")
        identity = self.model_dump(mode="json", by_alias=True, exclude={"evidence_id"})
        if self.evidence_id != canonical_sha256(identity):
            raise ValueError("Evidence v2 identity mismatch")
        return self


class EvidenceV2StudySource(StrictModel):
    schema_id: Literal["apex-research.study-report-source.v2"] = Field(alias="schema")
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ref: StudyRecordRef
    evidence: EvidenceV2
    sources: list[StudyRecordRef] = Field(min_length=1)
    source_record_ids: list[str] = Field(min_length=1)
    workspace_runs: list[EvidenceRecordRef]
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy

    @model_validator(mode="after")
    def verify_source(self) -> EvidenceV2StudySource:
        expected_sources = [
            StudyRecordRef(
                record_id=item.record.record_id,
                record_type=item.record.record_type,
            )
            for item in self.evidence.sources
        ]
        expected_runs = sorted(
            [
                item.record
                for item in self.evidence.sources
                if evidence_record_descriptor(item.record.record_type).reference_shape == "runtime"
            ],
            key=lambda item: (item.record_id, item.attempt_id or ""),
        )
        if (
            self.evidence_ref.record_type != "apex-research.evidence.v2"
            or self.evidence_ref.record_id != self.evidence.evidence_id
            or self.sources != expected_sources
            or self.source_record_ids != [item.record_id for item in expected_sources]
            or self.workspace_runs != expected_runs
            or len(self.source_record_ids) != len(set(self.source_record_ids))
        ):
            raise ValueError("Evidence v2 study source is incomplete or out of order")
        identity = self.model_dump(mode="json", by_alias=True, exclude={"source_id"})
        if self.source_id != canonical_sha256(identity):
            raise ValueError("Evidence v2 study source identity mismatch")
        return self


class PublicationReadback(StrictModel):
    schema_id: Literal["quant-research.publication.v1"] = Field(alias="schema")
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    payload: dict[str, Any]
    artifacts: list[ArtifactRef]
    lineage: list[LineageEdge]


class ExternalRecordReadback(StrictModel):
    reference: StudyRecordRef
    publication: PublicationReadback | None
    run: dict[str, Any] | None
    result: dict[str, Any] | None

    @model_validator(mode="after")
    def exactly_one_kind(self) -> ExternalRecordReadback:
        is_run = evidence_record_descriptor(self.reference.record_type).reference_shape == "runtime"
        if is_run != (self.run is not None and self.result is not None):
            raise ValueError("Runtime readback is incomplete")
        if is_run == (self.publication is not None):
            raise ValueError("external readback kind differs from its reference")
        return self


class EvidenceV2ReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.evidence-v2-read-model.v1"] = Field(
        default="strategy-reporting.evidence-v2-read-model.v1", alias="schema"
    )
    source: EvidenceV2StudySource
    source_publication: PublicationReadback
    evidence_publication: PublicationReadback
    external_records: list[ExternalRecordReadback]
    qualification_inference: InferencePolicy
    production_approval_inference: InferencePolicy

    @model_validator(mode="after")
    def verify_readback_closure(self) -> EvidenceV2ReadModel:
        references = [item.reference for item in self.external_records]
        if references != self.source.sources:
            raise ValueError("external canonical readback order differs from Evidence sources")
        if self.qualification_inference != self.source.qualification_inference:
            raise ValueError("qualification inference policy differs")
        if self.production_approval_inference != self.source.production_approval_inference:
            raise ValueError("forbidden production inference policy differs")
        return self


__all__ = [
    "EvidenceRecordRef",
    "EvidenceSection",
    "EvidenceSourceRef",
    "EvidenceV2",
    "EvidenceV2ReadModel",
    "EvidenceV2SourceRef",
    "EvidenceV2StudySource",
    "ExternalRecordReadback",
    "PublicationReadback",
]
