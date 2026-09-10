from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.models import StrictModel

CampaignAvailabilityStatus = Literal["available", "not_evaluated", "blocked", "unavailable"]
CampaignSectionName = Literal[
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
]
CampaignEvidenceClass = Literal["formal", "discovery", "empirical", "benchmark", "auxiliary"]
CampaignReportState = Literal["complete", "design", "partial", "blocked", "unavailable"]
CAMPAIGN_EVIDENCE_ORDER: tuple[CampaignEvidenceClass, ...] = (
    "formal",
    "discovery",
    "empirical",
    "benchmark",
    "auxiliary",
)

CAMPAIGN_SECTION_ORDER: tuple[CampaignSectionName, ...] = (
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

_FORBIDDEN_KEY_PARTS = {
    "credential",
    "local_path",
    "password",
    "private_artifact",
    "private_state",
    "prompt",
    "raw_log",
    "secret",
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[a-zA-Z]:[\\/]")


def reject_unsafe_campaign_value(value: object, *, location: str = "source") -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).lower()
            if any(part in key for part in _FORBIDDEN_KEY_PARTS):
                raise ValueError(f"forbidden campaign source field: {location}.{raw_key}")
            reject_unsafe_campaign_value(item, location=f"{location}.{raw_key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            reject_unsafe_campaign_value(item, location=f"{location}[{index}]")
    elif isinstance(value, str) and (
        _WINDOWS_ABSOLUTE_PATH.match(value)
        or PureWindowsPath(value).is_absolute()
        or PurePosixPath(value).is_absolute()
        or value.startswith("file://")
    ):
        raise ValueError(f"forbidden local path in campaign source: {location}")


class CampaignSourceRef(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)


class CampaignAvailability(StrictModel):
    status: CampaignAvailabilityStatus
    reason: str | None

    @model_validator(mode="after")
    def verify_reason(self) -> Self:
        if self.status == "available" and self.reason is not None:
            raise ValueError("available campaign sections cannot carry a reason")
        if self.status != "available" and not self.reason:
            raise ValueError("unavailable campaign sections require a reason")
        return self


class CampaignSourceItem(StrictModel):
    source: CampaignSourceRef
    ordinal: int = Field(ge=1)
    summary: dict[str, Any]

    @model_validator(mode="after")
    def verify_safe_summary(self) -> Self:
        reject_unsafe_campaign_value(self.summary, location="summary")
        return self


class CampaignSourceSection(StrictModel):
    name: CampaignSectionName
    availability: CampaignAvailability
    items: list[CampaignSourceItem] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def verify_content(self) -> Self:
        reject_unsafe_campaign_value(self.facts, location="facts")
        if self.availability.status == "available":
            if not self.items and not self.facts:
                raise ValueError("available campaign sections require public facts")
        elif self.items or self.facts:
            raise ValueError("unavailable campaign sections cannot carry public facts")
        if [item.ordinal for item in self.items] != list(range(1, len(self.items) + 1)):
            raise ValueError("campaign section ordinals must be contiguous")
        return self


class CampaignSourceCampaign(StrictModel):
    source: CampaignSourceRef
    brief_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1)

    @model_validator(mode="after")
    def verify_source(self) -> Self:
        if (
            self.source.record_type != "apex-research.campaign.v1"
            or self.source.record_id != self.source.record_id.lower()
        ):
            raise ValueError("campaign source reference is invalid")
        return self


class CampaignSourceBrief(StrictModel):
    source: CampaignSourceRef
    question: str = Field(min_length=1)
    constraints: list[str]
    assumptions: list[str]

    @model_validator(mode="after")
    def verify_source(self) -> Self:
        if self.source.record_type != "apex-research.research-brief.v1":
            raise ValueError("campaign brief source reference is invalid")
        reject_unsafe_campaign_value(
            {
                "question": self.question,
                "constraints": self.constraints,
                "assumptions": self.assumptions,
            },
            location="brief",
        )
        return self


class CampaignReportSource(StrictModel):
    schema_id: Literal["apex-research.campaign-report-source.v1"] = Field(alias="schema")
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign: CampaignSourceCampaign
    brief: CampaignSourceBrief
    sections: list[CampaignSourceSection]
    sources: list[CampaignSourceRef] = Field(min_length=2)
    workspace_runs: list[str]
    current_evidence: CampaignSourceRef | None
    current_qualification: CampaignSourceRef | None
    record_ordering: Literal["semantic-sequence-then-public-identity"]
    current_selection: Literal["explicit-supersession-and-currency"]
    failure_policy: Literal["include-all-within-bounded-public-graph"]
    reporting_interpretation: Literal["forbidden"]
    runtime_invocation: Literal["forbidden"]

    def identity_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude={"source_id"})

    @model_validator(mode="after")
    def verify_contract(self) -> Self:
        if self.campaign.brief_id != self.brief.source.record_id:
            raise ValueError("campaign source brief identity mismatch")
        if tuple(section.name for section in self.sections) != CAMPAIGN_SECTION_ORDER:
            raise ValueError("campaign sections must be complete, unique and canonical")
        source_keys = [(item.record_type, item.record_id) for item in self.sources]
        if source_keys != sorted(set(source_keys)):
            raise ValueError("campaign source references must be unique and canonical")
        required = {self.campaign.source, self.brief.source}
        required.update(item.source for section in self.sections for item in section.items)
        if self.current_evidence is not None:
            required.add(self.current_evidence)
        if self.current_qualification is not None:
            required.add(self.current_qualification)
        if not required <= set(self.sources):
            raise ValueError("campaign source lineage is incomplete")
        run_refs = {
            item.record_id
            for item in self.sources
            if item.record_type == "quant-research.run-record.v1"
        }
        if self.workspace_runs != sorted(set(self.workspace_runs)) or run_refs != set(
            self.workspace_runs
        ):
            raise ValueError("campaign Workspace run lineage is inconsistent")
        if self.source_id != canonical_sha256(self.identity_payload()):
            raise ValueError("campaign report source identity mismatch")
        return self


class CampaignSubject(StrictModel):
    campaign_id: str = Field(min_length=1)
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class CampaignObjective(StrictModel):
    question: str = Field(min_length=1)
    constraints: list[str]
    assumptions: list[str]
    source: dict[str, str]


class CampaignQuantitativeValue(StrictModel):
    path: str = Field(min_length=1)
    value: int | float
    source: dict[str, str]

    @model_validator(mode="after")
    def reject_boolean(self) -> Self:
        if isinstance(self.value, bool):
            raise ValueError("campaign quantitative values cannot be boolean")
        return self


def campaign_quantitative_values(
    sections: list[CampaignSourceSection], source_publication: dict[str, str]
) -> list[CampaignQuantitativeValue]:
    publication = {
        "record_id": source_publication["record_id"],
        "record_type": source_publication["record_type"],
    }
    values: list[CampaignQuantitativeValue] = []
    for section in sections:
        prefix = f"$.sections.{section.name}"
        for index, item in enumerate(section.items):
            values.extend(
                _quantitative_values(
                    item.summary,
                    source=item.source.model_dump(mode="json"),
                    path=f"{prefix}.items[{index}].summary",
                )
            )
        values.extend(
            _quantitative_values(section.facts, source=publication, path=f"{prefix}.facts")
        )
    return values


def _quantitative_values(
    value: object, *, source: dict[str, str], path: str
) -> list[CampaignQuantitativeValue]:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return []
    if isinstance(value, int | float):
        return [CampaignQuantitativeValue(path=path, value=value, source=source)]
    if isinstance(value, dict):
        return [
            quantity
            for key in sorted(value)
            for quantity in _quantitative_values(value[key], source=source, path=f"{path}.{key}")
        ]
    if isinstance(value, list):
        return [
            quantity
            for index, item in enumerate(value)
            for quantity in _quantitative_values(item, source=source, path=f"{path}[{index}]")
        ]
    return []


class CampaignEvidenceEntry(StrictModel):
    section: CampaignSectionName
    source: dict[str, str]
    data: dict[str, Any]
    quantitative_values: list[CampaignQuantitativeValue]


class CampaignEvidenceLane(StrictModel):
    evidence_class: CampaignEvidenceClass
    entries: list[CampaignEvidenceEntry]


class CampaignReport(StrictModel):
    schema_id: Literal["strategy-reporting.campaign-report.v1"] = Field(
        default="strategy-reporting.campaign-report.v1", alias="schema"
    )
    title: str = Field(min_length=1)
    subject: CampaignSubject
    report_state: CampaignReportState
    objective: CampaignObjective
    sections: list[CampaignSourceSection]
    evidence_lanes: list[CampaignEvidenceLane]
    quantitative_values: list[CampaignQuantitativeValue]
    current_evidence: dict[str, str] | None
    current_qualification: dict[str, str] | None
    source_publication: dict[str, str]
    source_records: list[dict[str, str]]
    workspace_run_ids: list[str]

    @model_validator(mode="after")
    def verify_shape(self) -> Self:
        if tuple(section.name for section in self.sections) != CAMPAIGN_SECTION_ORDER:
            raise ValueError("campaign report sections must preserve Apex order")
        if tuple(lane.evidence_class for lane in self.evidence_lanes) != CAMPAIGN_EVIDENCE_ORDER:
            raise ValueError("campaign evidence lanes must be complete, unique and canonical")
        if self.source_publication != {
            "record_id": self.subject.source_id,
            "record_type": "apex-research.campaign-report-source.v1",
            "source_id": self.subject.source_id,
        }:
            raise ValueError("campaign report source publication identity differs")
        if self.quantitative_values != campaign_quantitative_values(
            self.sections, self.source_publication
        ):
            raise ValueError("campaign quantitative value map must be complete and canonical")
        return self
