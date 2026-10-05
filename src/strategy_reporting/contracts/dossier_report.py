"""Evidence-backed dossier projection; every scalar retains an exact public source."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from strategy_reporting.contracts.evidence_v2 import StudyRecordRef
from strategy_reporting.models import LineageEdge, StrictModel

MATRIX_TYPE = "apex-research.v1.2-s5-formal-matrix.v1"
T2_TYPE = "apex-research.v1.2-s5-t2-source.v1"
SOURCE_TYPE = "apex-research.strategy-report-source.v2"
QUARANTINE_TYPE = "apex-research.v1.2-s5-quarantine.v1"
CONCLUSION_TYPE = "apex-research.research-conclusion.v1"

DossierSectionName = Literal[
    "source",
    "experiment_matrix",
    "lineage",
    "metrics",
    "audits",
    "comparisons",
    "attributions",
    "quarantine",
    "holdout_lock",
    "limitations",
]
DOSSIER_SECTION_ORDER: tuple[DossierSectionName, ...] = (
    "source",
    "experiment_matrix",
    "lineage",
    "metrics",
    "audits",
    "comparisons",
    "attributions",
    "quarantine",
    "holdout_lock",
    "limitations",
)
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DossierSourceRefs(StrictModel):
    """Explicit identities, never a latest-record selection or a prefix lookup."""

    matrix: StudyRecordRef
    t2: StudyRecordRef
    report_source: StudyRecordRef
    quarantine: StudyRecordRef
    conclusion: StudyRecordRef

    def records(self) -> list[StudyRecordRef]:
        return [self.matrix, self.t2, self.report_source, self.quarantine, self.conclusion]

    @model_validator(mode="after")
    def verify_types(self) -> Self:
        if [item.record_type for item in self.records()] != [
            MATRIX_TYPE,
            T2_TYPE,
            SOURCE_TYPE,
            QUARANTINE_TYPE,
            CONCLUSION_TYPE,
        ]:
            raise ValueError("dossier source reference types differ")
        if any(
            len(item.record_id) != 64 or any(c not in "0123456789abcdef" for c in item.record_id)
            for item in self.records()
        ):
            raise ValueError("dossier source identities must be complete SHA-256 values")
        return self


CURRENT_DOSSIER_SOURCE_REFS = DossierSourceRefs(
    matrix=StudyRecordRef(
        record_id="7523f0c34e7d90b6e603f63cc53884284d05664351b68d0a59805e9cf8d95bb5",
        record_type=MATRIX_TYPE,
    ),
    t2=StudyRecordRef(
        record_id="0cc1f61f6528720a0145206419362872d4ff8fba9e676ef8f3ac358e4450cf35",
        record_type=T2_TYPE,
    ),
    report_source=StudyRecordRef(
        record_id="79d7bf225182dcaa7999e38613f0da690291c21b8ed7396d291ac389d5a9f99f",
        record_type=SOURCE_TYPE,
    ),
    quarantine=StudyRecordRef(
        record_id="33a9500fad482531b6a4747c67c62dd16132f579782d28234bf8815ee5dfedfc",
        record_type=QUARANTINE_TYPE,
    ),
    conclusion=StudyRecordRef(
        record_id="539390079a3dc4eb8061d83f52ca59f2ad169f38ee3d2419b9ffba99164e5dc9",
        record_type=CONCLUSION_TYPE,
    ),
)


class DossierArtifactRef(StrictModel):
    """Content citation; numeric descriptor metadata is projected as sourced facts."""

    uri: str
    sha256: Sha256
    name: str = Field(min_length=1)
    record_schema: str | None = None

    @model_validator(mode="after")
    def verify_uri(self) -> Self:
        if self.uri != f"workspace-artifact://sha256/{self.sha256}":
            raise ValueError("dossier artifact URI differs from its content hash")
        return self


class DossierValueSource(StrictModel):
    record: StudyRecordRef
    selector: str = Field(pattern=r"^/")
    artifact: DossierArtifactRef | None = None


class DossierValue(StrictModel):
    """A verbatim scalar or an explicitly unavailable field, with JSON-pointer provenance."""

    path: str = Field(pattern=r"^/")
    value: StrictStr | StrictInt | StrictFloat | StrictBool | None
    status: Literal["evaluated", "not_evaluated"]
    derivation: Literal["Runtime-native", "presentation-derived", "not_evaluated"]
    derivation_reason: str = Field(min_length=1)
    sources: list[DossierValueSource] = Field(min_length=1)
    reason: str | None = None

    @model_validator(mode="after")
    def verify_status(self) -> Self:
        if self.status == "not_evaluated":
            if self.value is not None or not self.reason or self.derivation != "not_evaluated":
                raise ValueError("not_evaluated dossier values require null, reason and status")
        elif self.value is None or self.reason is not None or self.derivation == "not_evaluated":
            raise ValueError("evaluated dossier values require a value and derivation")
        if self.derivation == "Runtime-native" and any(
            item.artifact is None for item in self.sources
        ):
            raise ValueError("Runtime-native values require a verified native artifact citation")
        return self


class DossierEvidence(StrictModel):
    source: StudyRecordRef
    payload_sha256: Sha256 | None
    lineage: list[LineageEdge]
    artifacts: list[DossierArtifactRef]
    facts: list[DossierValue]

    @model_validator(mode="after")
    def verify_facts(self) -> Self:
        paths = [item.path for item in self.facts]
        if paths != sorted(set(paths)):
            raise ValueError("dossier fact paths must be unique and canonical")
        artifact_set = set(self.artifacts)
        if self.artifacts != sorted(artifact_set, key=lambda item: (item.sha256, item.name)):
            raise ValueError("dossier artifacts must be unique and canonical")
        if any(
            citation.record != self.source
            or (citation.artifact is not None and citation.artifact not in artifact_set)
            for fact in self.facts
            for citation in fact.sources
        ):
            raise ValueError("dossier fact citations differ from their evidence owner")
        return self


class DossierSection(StrictModel):
    name: DossierSectionName
    status: Literal["evaluated", "not_evaluated"]
    reason: str | None = None
    evidence: list[DossierEvidence]

    @model_validator(mode="after")
    def verify_status(self) -> Self:
        if self.status == "not_evaluated":
            if self.evidence or not self.reason:
                raise ValueError("unavailable dossier sections require only a reason")
        elif not self.evidence or self.reason is not None:
            raise ValueError("evaluated dossier sections require public evidence")
        keys = [(item.source.record_type, item.source.record_id) for item in self.evidence]
        if keys != sorted(set(keys)):
            raise ValueError("dossier evidence must be unique and canonical")
        return self


class DossierReport(StrictModel):
    schema_id: Literal["strategy-reporting.dossier-report.v1"] = Field(
        default="strategy-reporting.dossier-report.v1", alias="schema"
    )
    title: str = "Quant Research Dossier v2 · 开发与验证"
    banner: Literal["非前向 Holdout / 非实盘结论"] = "非前向 Holdout / 非实盘结论"
    source_refs: DossierSourceRefs
    sections: list[DossierSection]
    source_records: list[StudyRecordRef]
    source_artifacts: list[DossierArtifactRef]
    evidence_ceiling: Literal["candidate_evidence"] = "candidate_evidence"
    qualification_inference: Literal["forbidden"] = "forbidden"
    causal_inference: Literal["forbidden"] = "forbidden"
    production_approval_inference: Literal["forbidden"] = "forbidden"
    holdout_results: Literal["not_evaluated"] = "not_evaluated"

    @model_validator(mode="after")
    def verify_closure(self) -> Self:
        if tuple(item.name for item in self.sections) != DOSSIER_SECTION_ORDER:
            raise ValueError("dossier sections must be complete and canonical")
        keys = [(item.record_type, item.record_id) for item in self.source_records]
        if keys != sorted(set(keys)):
            raise ValueError("dossier source records must be unique and canonical")
        evidence = [item for section in self.sections for item in section.evidence]
        cited = {item.source for item in evidence}
        if cited != set(self.source_records) or not set(self.source_refs.records()) <= cited:
            raise ValueError("dossier public source closure is incomplete")
        artifacts = {artifact for item in evidence for artifact in item.artifacts}
        if set(self.source_artifacts) != artifacts or self.source_artifacts != sorted(
            artifacts, key=lambda item: (item.sha256, item.name)
        ):
            raise ValueError("dossier artifact closure differs")
        return self


__all__ = [
    "CURRENT_DOSSIER_SOURCE_REFS",
    "DossierReport",
    "DossierSourceRefs",
    "DossierValue",
]
