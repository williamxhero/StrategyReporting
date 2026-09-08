from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.models import StrictModel


class ReplicationRecordRef(StrictModel):
    record_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_type: str = Field(min_length=1)


class ReplicationMetric(StrictModel):
    partition: Literal["source", "legacy"]
    selector: str = Field(pattern=r"^(source|legacy)\.metrics\.[a-z0-9_.-]+$")
    value_micros: int
    source_location: str = Field(min_length=1)

    @model_validator(mode="after")
    def verify_partition(self) -> ReplicationMetric:
        if not self.selector.startswith(f"{self.partition}.metrics."):
            raise ValueError("replication metric partition mismatch")
        return self


class ReplicationAssumption(StrictModel):
    schema_id: Literal["apex-research.replication-assumption.v1"] = Field(alias="schema")
    assumption_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    selector: str = Field(pattern=r"^research\.assumptions\.[a-z0-9_.-]+$")
    value: bool | int | str
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def verify_identity(self) -> ReplicationAssumption:
        payload = self.model_dump(exclude={"assumption_id"}, mode="json", by_alias=True)
        if self.assumption_id != canonical_sha256(payload):
            raise ValueError("replication assumption identity mismatch")
        return self


class ReplicationFormalFact(StrictModel):
    selector: str = Field(pattern=r"^formal\.nautilus\.metrics\.[a-z0-9_.-]+$")
    value_micros: int
    runtime_evidence: ReplicationRecordRef

    @model_validator(mode="after")
    def verify_owner(self) -> ReplicationFormalFact:
        if self.runtime_evidence.record_type != "quant-research.result.v4":
            raise ValueError("formal fact must cite Runtime result v4")
        return self


class ReplicationDifference(StrictModel):
    dimension: Literal[
        "metric_definition",
        "sample_window",
        "universe",
        "data_semantics",
        "execution_timing",
        "transaction_costs",
        "benchmark",
        "implementation",
    ]
    source_selector: str = Field(pattern=r"^(source|legacy)\.metrics\.[a-z0-9_.-]+$")
    formal_selector: str = Field(pattern=r"^formal\.nautilus\.metrics\.[a-z0-9_.-]+$")
    mode: Literal["exact", "directional"]
    source_value_micros: int
    formal_value_micros: int
    delta_micros: int
    matched: bool
    source_provenance: str = Field(min_length=1)
    formal_provenance: ReplicationRecordRef

    @model_validator(mode="after")
    def verify_delta(self) -> ReplicationDifference:
        if self.delta_micros != self.formal_value_micros - self.source_value_micros:
            raise ValueError("replication difference delta mismatch")
        return self


class ReplicationGap(StrictModel):
    code: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    owner_references: list[ReplicationRecordRef] = Field(min_length=1)


class ReplicationReportSource(StrictModel):
    schema_id: Literal["apex-research.replication-report-source.v1"] = Field(alias="schema")
    report_source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    case: ReplicationRecordRef
    formal_execution: ReplicationRecordRef | None
    research_design: ReplicationRecordRef | None
    comparison_evidence: ReplicationRecordRef
    decision: ReplicationRecordRef
    outcome: Literal["exact", "directional", "failed", "not_reproducible"]
    source_metrics: list[ReplicationMetric]
    legacy_metrics: list[ReplicationMetric]
    research_assumptions: list[ReplicationAssumption]
    formal_facts: list[ReplicationFormalFact]

    @model_validator(mode="after")
    def verify_source(self) -> ReplicationReportSource:
        not_reproducible = self.outcome == "not_reproducible"
        if not_reproducible:
            if self.formal_execution is not None or self.research_design is None:
                raise ValueError("not_reproducible requires design and zero formal execution")
            if self.formal_facts:
                raise ValueError("not_reproducible cannot carry formal facts")
            expected_evidence = "apex-research.replication-evidence.v1"
            expected_decision = "apex-research.replication-decision.v1"
        else:
            if self.formal_execution is None or self.research_design is not None:
                raise ValueError("executed replication requires formal execution only")
            if not self.formal_facts:
                raise ValueError("executed replication requires formal facts")
            expected_evidence = "apex-research.replication-comparison-evidence.v1"
            expected_decision = "apex-research.replication-comparison-decision.v1"
        if self.comparison_evidence.record_type != expected_evidence:
            raise ValueError("replication report evidence type mismatch")
        if self.decision.record_type != expected_decision:
            raise ValueError("replication report decision type mismatch")
        if any(item.partition != "source" for item in self.source_metrics):
            raise ValueError("replication source metric partition mismatch")
        if any(item.partition != "legacy" for item in self.legacy_metrics):
            raise ValueError("replication legacy metric partition mismatch")
        payload = self.model_dump(exclude={"report_source_id"}, mode="json", by_alias=True)
        if self.report_source_id != canonical_sha256(payload):
            raise ValueError("replication report source identity mismatch")
        return self


class ReplicationReadModel(StrictModel):
    source: ReplicationReportSource
    differences: list[ReplicationDifference]
    blocking_prerequisites: list[ReplicationGap]
    source_publication: dict[str, str]
    source_records: list[dict[str, str]]


def verify_embedded_identity(
    payload: dict[str, Any], *, id_field: str, reference: ReplicationRecordRef
) -> None:
    if (
        payload.get("schema") != reference.record_type
        or payload.get(id_field) != reference.record_id
    ):
        raise ValueError("replication owner identity mirror mismatch")
    identity = {key: value for key, value in payload.items() if key != id_field}
    if canonical_sha256(identity) != reference.record_id:
        raise ValueError("replication owner canonical identity mismatch")
