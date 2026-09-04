from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from strategy_reporting.canonical import canonical_sha256, normalize_json

ReportKind = Literal["formal-run", "research-study"]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    @model_validator(mode="after")
    def finite_json(self) -> StrictModel:
        normalize_json(self.model_dump(mode="json"))
        return self


class Availability(StrictModel):
    status: Literal["available", "unavailable", "not_evaluated"]
    reason: str | None = None
    items: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def reason_for_absence(self) -> Availability:
        if self.status != "available" and not self.reason:
            raise ValueError("unavailable and not_evaluated values require a reason")
        return self


class ArtifactRef(StrictModel):
    schema_id: Literal["quant-research.artifact-ref.v1"] = Field(alias="schema")
    uri: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    media_type: str
    record_schema: str | None = None
    logical_role: str
    name: str

    @field_validator("uri")
    @classmethod
    def opaque_workspace_uri(cls, value: str) -> str:
        if not value.startswith("workspace-artifact://sha256/"):
            raise ValueError("artifact URI must be an opaque Workspace URI")
        return value


class LineageEdge(StrictModel):
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    relation: str = Field(min_length=1)


class ReportOptions(StrictModel):
    workspace_root: Path | None = Field(default=None, exclude=True)
    formal_id: str | None = Field(default=None, exclude=True)
    decision_id: str | None = Field(default=None, exclude=True)
    locale: Literal["zh-CN"] = "zh-CN"
    theme: Literal["paper", "dark"] = "paper"
    detail_row_limit: int = Field(default=100, ge=0, le=1_000)
    max_model_bytes: int = Field(default=2_000_000, ge=1_024, le=20_000_000)
    max_html_bytes: int = Field(default=12_000_000, ge=10_000, le=50_000_000)

    def normalized(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"workspace_root", "formal_id", "decision_id"})

    @property
    def options_hash(self) -> str:
        return canonical_sha256(self.normalized())


class ReportIdentity(StrictModel):
    schema_id: Literal["strategy-reporting.report-identity.v1"] = Field(
        default="strategy-reporting.report-identity.v1", alias="schema"
    )
    report_kind: ReportKind
    subject: dict[str, Any]
    source_identities: list[str]
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_version: str = Field(min_length=1)
    options: dict[str, Any]


class ReportDescriptor(StrictModel):
    schema_id: Literal["strategy-reporting.report-descriptor.v1"] = Field(
        default="strategy-reporting.report-descriptor.v1", alias="schema"
    )
    report_id: str = Field(pattern=r"^report_[0-9a-f]{64}$")
    report_kind: ReportKind
    subject_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    payload_schema: str = Field(min_length=1)
    renderer_version: str = Field(min_length=1)
    identity: ReportIdentity
    expected_content_hashes: dict[str, str]

    @field_validator("expected_content_hashes")
    @classmethod
    def hashes_are_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("expected content hashes must not be empty")
        if any(
            len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item)
            for item in value.values()
        ):
            raise ValueError("expected content hashes must be lowercase SHA-256")
        return value


class ReportEnvelope(StrictModel):
    schema_id: Literal["strategy-reporting.report-envelope.v1"] = Field(
        default="strategy-reporting.report-envelope.v1", alias="schema"
    )
    report_id: str = Field(pattern=r"^report_[0-9a-f]{64}$")
    report_kind: ReportKind
    subject_id: str
    title: str
    generated_at: datetime
    payload_schema: str
    renderer_version: str
    identity: ReportIdentity
    artifacts: list[ArtifactRef]
    lineage: list[LineageEdge]


class ReportPublication(StrictModel):
    envelope: ReportEnvelope
    publication: dict[str, Any]


class TablePreview(StrictModel):
    total_rows: int = Field(ge=0)
    rows: list[dict[str, Any]]
    omitted_count: int = Field(ge=0)
    source_artifact: ArtifactRef | None = None

    @model_validator(mode="after")
    def counts_match(self) -> TablePreview:
        if len(self.rows) + self.omitted_count != self.total_rows:
            raise ValueError("preview row count and omitted count must equal total rows")
        return self


class PortfolioReturnPoint(StrictModel):
    timestamp: datetime
    value: Decimal
    frequency: str
    timezone: str
    source: Literal["nautilus-analyzer"] = "nautilus-analyzer"


class FormalSubject(StrictModel):
    workspace_run_id: str
    attempt_id: str
    formal_id: str
    request_hash: str
    status: str
    outcome: str
    topology: str


class FormalPerformance(StrictModel):
    stats_pnls: dict[str, Any]
    stats_returns: dict[str, Any]
    stats_general: dict[str, Any]
    portfolio_returns: list[PortfolioReturnPoint]
    sources: dict[str, str]
    availability: dict[str, dict[str, str]]
    unavailable: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("portfolio_returns")
    @classmethod
    def returns_are_ordered_unique(
        cls, value: list[PortfolioReturnPoint]
    ) -> list[PortfolioReturnPoint]:
        stamps = [item.timestamp for item in value]
        if stamps != sorted(stamps):
            raise ValueError("portfolio returns must be ordered")
        if len(stamps) != len(set(stamps)):
            raise ValueError("portfolio return timestamps must be unique")
        return value


class FormalRunReport(StrictModel):
    schema_id: Literal["strategy-reporting.formal-run-report.v1"] = Field(
        default="strategy-reporting.formal-run-report.v1", alias="schema"
    )
    title: str
    subject: FormalSubject
    strategy: dict[str, Any]
    market: dict[str, Any]
    engine: dict[str, Any]
    performance: FormalPerformance
    run_info: dict[str, Any]
    account_info: dict[str, Any]
    execution: dict[str, TablePreview]
    quality: dict[str, Any]
    execution_performance: dict[str, Any]
    analytics: dict[str, Any] = Field(default_factory=dict)
    source_artifacts: list[ArtifactRef]


class ResearchSubject(StrictModel):
    study_id: str
    decision_id: str
    protocol_hash: str


class ResearchStudyReport(StrictModel):
    schema_id: Literal["strategy-reporting.research-study-report.v1"] = Field(
        default="strategy-reporting.research-study-report.v1", alias="schema"
    )
    title: str
    subject: ResearchSubject
    strategy_package: dict[str, Any]
    hypothesis: str
    protocol: dict[str, Any]
    gate_specs: list[dict[str, Any]]
    trials: list[dict[str, Any]]
    discovery: Availability
    formal_runs: list[dict[str, Any]]
    gate_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    research_metrics: dict[str, Any]
    validation: dict[str, Any] | None = Field(default=None, exclude_if=lambda value: value is None)
    statistical: dict[str, Any] | None = Field(default=None, exclude_if=lambda value: value is None)
    robustness: Availability
    sensitivity: Availability
    capacity: Availability
    final_decision: dict[str, Any]
    related_formal_reports: list[dict[str, Any]]
    unavailable_sections: list[Availability]
    source_publication: dict[str, str]
    source_records: list[dict[str, str]]
    source_record_ids: list[str]
    workspace_run_ids: list[str]


ReportModel = FormalRunReport | ResearchStudyReport
