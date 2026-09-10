"""Strict presentation-side mirrors for immutable Apex archive records."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.models import StrictModel

EXPLORATION_ARCHIVE_RECORD_TYPE: Literal["apex-research.exploration-archive.v1"] = (
    "apex-research.exploration-archive.v1"
)
EVIDENCE_ARCHIVE_RECORD_TYPE: Literal["apex-research.evidence-archive.v1"] = (
    "apex-research.evidence-archive.v1"
)
SPEC032_BLOCKER: Literal["SPEC-032 exact currency owner fact unavailable"] = (
    "SPEC-032 exact currency owner fact unavailable"
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class PublishedRef(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)


class ArchiveRecordRef(PublishedRef):
    record_id: Sha256
    record_type: Literal[
        "apex-research.exploration-archive.v1",
        "apex-research.evidence-archive.v1",
    ]

    @classmethod
    def exploration(cls, record_id: str) -> ArchiveRecordRef:
        return cls(record_id=record_id, record_type=EXPLORATION_ARCHIVE_RECORD_TYPE)

    @classmethod
    def evidence(cls, record_id: str) -> ArchiveRecordRef:
        return cls(record_id=record_id, record_type=EVIDENCE_ARCHIVE_RECORD_TYPE)


class ExplorationArchiveRef(PublishedRef):
    record_id: Sha256
    record_type: Literal["apex-research.exploration-archive.v1"] = EXPLORATION_ARCHIVE_RECORD_TYPE


class EvidenceArchiveRef(PublishedRef):
    record_id: Sha256
    record_type: Literal["apex-research.evidence-archive.v1"] = EVIDENCE_ARCHIVE_RECORD_TYPE


class TaxonomyRef(PublishedRef):
    record_id: Sha256
    record_type: Literal["apex-research.behavior-taxonomy.v1"]


class StrategyRevisionRef(PublishedRef):
    record_id: Sha256
    record_type: Literal["apex-research.strategy-candidate.v1"]
    semantic_id: Sha256
    family_id: NonEmpty
    revision: int = Field(ge=1)


class DescriptorSourceRef(PublishedRef):
    attempt_id: str | None
    request_hash: str | None
    result_hash: str | None


class ArchiveObjective(StrictModel):
    objective_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    selector: str = Field(pattern=r"^(discovery\.metrics|research)\.[a-z0-9_.-]+$")
    direction: Literal["maximize", "minimize"]
    unit: NonEmpty
    priority: int = Field(ge=0)


class EvidenceArchiveObjective(StrictModel):
    objective_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    selector: str = Field(pattern=r"^formal\.nautilus\.metrics\.[a-z0-9_.-]+$")
    direction: Literal["maximize", "minimize"]
    unit: NonEmpty
    priority: int = Field(ge=0)


class ExplorationArchiveEntry(StrictModel):
    entry_id: Sha256
    candidate: StrategyRevisionRef
    descriptor: PublishedRef
    quality: PublishedRef
    niche_id: Sha256
    generation_position: int = Field(ge=0)
    entry_label: Literal["discovery leader"]

    @model_validator(mode="after")
    def verify_identity(self) -> ExplorationArchiveEntry:
        if self.descriptor.record_type != "apex-research.discovery-behavior-descriptor.v1":
            raise ValueError("exploration descriptor tier mismatch")
        if self.quality.record_type != "apex-research.discovery-archive-quality.v1":
            raise ValueError("exploration quality tier mismatch")
        if self.entry_id != canonical_sha256(self.model_dump(mode="json", exclude={"entry_id"})):
            raise ValueError("exploration archive entry identity mismatch")
        return self


class ExplorationArchivePolicy(StrictModel):
    schema_id: Literal["apex-research.exploration-archive.v1"] = Field(alias="schema")
    kind: Literal["policy"]
    policy_id: Sha256
    archive_family: Literal["exploration"]
    archive_label: Literal["exploration archive"]
    entry_label: Literal["discovery leader"]
    campaign: PublishedRef
    taxonomy: TaxonomyRef
    name: NonEmpty
    version: NonEmpty
    niche_capacity: int = Field(ge=1)
    comparison_mode: Literal["lexicographic", "pareto"]
    objectives: list[ArchiveObjective] = Field(min_length=1)
    tie_breaker: Literal["entry_id_ascending"]
    unavailable_objective_rule: Literal["reject"]
    novelty_rule: Literal["descriptor_niche_id"]
    empty_niche_rule: Literal["admit"]
    formal_claim: Literal["forbidden"]
    robustness_claim: Literal["forbidden"]
    qualification_claim: Literal["forbidden"]
    current_evidence_claim: Literal["forbidden"]
    production_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> ExplorationArchivePolicy:
        if self.policy_id != _identity(self, "policy_id"):
            raise ValueError("exploration archive policy identity mismatch")
        return self


class ExplorationArchiveEvent(StrictModel):
    schema_id: Literal["apex-research.exploration-archive.v1"] = Field(alias="schema")
    kind: Literal["event"]
    event_id: Sha256
    archive_family: Literal["exploration"]
    policy: ExplorationArchiveRef
    predecessor: ExplorationArchiveRef | None
    generation_position: int = Field(ge=0)
    candidate: StrategyRevisionRef
    decision: Literal[
        "inserted", "rejected", "replaced", "tied", "incomparable", "unavailable_objective"
    ]
    considered: ExplorationArchiveEntry
    admitted: ExplorationArchiveEntry | None
    displaced: list[ExplorationArchiveEntry]
    reason: NonEmpty

    @model_validator(mode="after")
    def verify_identity(self) -> ExplorationArchiveEvent:
        if self.decision == "inserted" and self.admitted is None:
            raise ValueError("inserted exploration event requires an admitted entry")
        if self.admitted is not None and self.admitted != self.considered:
            raise ValueError("exploration admitted entry mismatch")
        if self.displaced != sorted(self.displaced, key=lambda item: item.entry_id):
            raise ValueError("exploration displaced entries are not canonical")
        if self.event_id != _identity(self, "event_id"):
            raise ValueError("exploration archive event identity mismatch")
        return self


class ExplorationArchiveSnapshot(StrictModel):
    schema_id: Literal["apex-research.exploration-archive.v1"] = Field(alias="schema")
    kind: Literal["snapshot"]
    snapshot_id: Sha256
    archive_family: Literal["exploration"]
    archive_label: Literal["exploration archive"]
    entry_label: Literal["discovery leader"]
    policy: ExplorationArchiveRef
    taxonomy: TaxonomyRef
    predecessor: ExplorationArchiveRef | None
    generation_id: Sha256
    generation_positions: list[int] = Field(min_length=1)
    events: list[ExplorationArchiveRef]
    entries: list[ExplorationArchiveEntry]
    historical_entries: list[ExplorationArchiveEntry]
    considered_niches: list[Sha256]
    occupied_niches: list[Sha256]
    empty_niches: list[Sha256]
    formal_claim: Literal["forbidden"]
    robustness_claim: Literal["forbidden"]
    qualification_claim: Literal["forbidden"]
    current_evidence_claim: Literal["forbidden"]
    production_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> ExplorationArchiveSnapshot:
        if len(self.events) != len(self.generation_positions):
            raise ValueError("exploration archive generation event count mismatch")
        if self.snapshot_id != _identity(self, "snapshot_id"):
            raise ValueError("exploration archive snapshot identity mismatch")
        return self


class ExplorationArchiveLifecycleEvent(StrictModel):
    schema_id: Literal["apex-research.exploration-archive.v1"] = Field(alias="schema")
    kind: Literal["lifecycle_event"]
    event_id: Sha256
    archive_family: Literal["exploration"]
    action: Literal["retired", "superseded", "source_invalidated", "taxonomy_revision"]
    policy: ExplorationArchiveRef
    predecessor: ExplorationArchiveRef
    previous_taxonomy: TaxonomyRef
    taxonomy: TaxonomyRef
    target_entry_id: Sha256 | None
    owner_source: PublishedRef
    reason: NonEmpty
    formal_claim: Literal["forbidden"]
    production_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> ExplorationArchiveLifecycleEvent:
        revision = self.action == "taxonomy_revision"
        if revision != (self.target_entry_id is None) or revision != (
            self.taxonomy != self.previous_taxonomy
        ):
            raise ValueError("exploration lifecycle transition mismatch")
        if self.event_id != _identity(self, "event_id"):
            raise ValueError("exploration lifecycle identity mismatch")
        return self


class ExplorationArchiveView(StrictModel):
    schema_id: Literal["apex-research.exploration-archive.v1"] = Field(alias="schema")
    kind: Literal["active_view"]
    snapshot_id: Sha256
    archive_family: Literal["exploration"]
    archive_label: Literal["exploration archive"]
    entry_label: Literal["discovery leader"]
    policy: ExplorationArchiveRef
    taxonomy: TaxonomyRef
    predecessor: ExplorationArchiveRef
    events: list[ExplorationArchiveRef] = Field(min_length=1)
    active_entries: list[ExplorationArchiveEntry]
    historical_entries: list[ExplorationArchiveEntry]
    known_niches: list[Sha256]
    occupied_niches: list[Sha256]
    empty_niches: list[Sha256]
    view_status: Literal["evaluated"]
    reason: NonEmpty
    formal_claim: Literal["forbidden"]
    production_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> ExplorationArchiveView:
        if self.snapshot_id != _identity(self, "snapshot_id"):
            raise ValueError("exploration active view identity mismatch")
        return self


class ExplorationEntryLink(StrictModel):
    snapshot: ExplorationArchiveRef
    event: ExplorationArchiveRef
    entry_id: Sha256
    lineage_role: Literal["optional_prior_exploration_context"]
    formal_requirement_satisfaction: Literal["forbidden"]


class EvidenceObservation(StrictModel):
    objective_id: NonEmpty
    selector: NonEmpty
    direction: Literal["maximize", "minimize"]
    unit: NonEmpty
    values_micros: list[int] = Field(min_length=1)
    comparability_group: Sha256
    sources: list[DescriptorSourceRef] = Field(min_length=1)


class EvidenceConsideration(StrictModel):
    consideration_id: Sha256
    candidate: StrategyRevisionRef
    descriptor: PublishedRef
    evidence: PublishedRef
    qualification: PublishedRef
    taxonomy: TaxonomyRef
    niche_id: Sha256
    exploration_lineage: ExplorationEntryLink | None
    observations: list[EvidenceObservation]
    status: Literal["eligible", "rejected", "incomparable"]
    reason: NonEmpty

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceConsideration:
        if self.descriptor.record_type != "apex-research.formal-behavior-descriptor.v1":
            raise ValueError("Evidence descriptor tier mismatch")
        if self.evidence.record_type != "apex-research.evidence.v2":
            raise ValueError("Evidence owner fact tier mismatch")
        if self.consideration_id != _identity(self, "consideration_id"):
            raise ValueError("evidence archive consideration identity mismatch")
        return self


class EvidenceArchiveEntry(StrictModel):
    entry_id: Sha256
    consideration: EvidenceConsideration
    entry_label: Literal["historical formal evidence leader"]
    historical_claim: Literal["historical_formal_evidence"]
    operational_authority: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceArchiveEntry:
        if self.consideration.status != "eligible":
            raise ValueError("evidence archive entry is not eligible historical evidence")
        if self.entry_id != _identity(self, "entry_id"):
            raise ValueError("evidence archive entry identity mismatch")
        return self


class EvidenceArchivePolicy(StrictModel):
    schema_id: Literal["apex-research.evidence-archive.v1"] = Field(alias="schema")
    kind: Literal["policy"]
    policy_id: Sha256
    archive_family: Literal["evidence"]
    archive_label: Literal["evidence archive"]
    entry_label: Literal["historical formal evidence leader"]
    campaign: PublishedRef
    taxonomy: TaxonomyRef
    name: NonEmpty
    version: NonEmpty
    niche_capacity: int = Field(ge=1)
    comparison_mode: Literal["lexicographic", "pareto"]
    objectives: list[EvidenceArchiveObjective] = Field(min_length=1)
    minimum_historical_maturity: Literal[
        "formally_tested", "research_validated", "robustness_validated", "research_qualified"
    ]
    currency_requirement: Literal["not_required_for_historical", "current_required"]
    tie_breaker: Literal["entry_id_ascending"]
    operational_authority: Literal["forbidden"]
    production_claim: Literal["forbidden"]
    live_trading_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceArchivePolicy:
        if self.policy_id != _identity(self, "policy_id"):
            raise ValueError("evidence archive policy identity mismatch")
        return self


class EvidenceArchiveEvent(StrictModel):
    schema_id: Literal["apex-research.evidence-archive.v1"] = Field(alias="schema")
    kind: Literal["event"]
    event_id: Sha256
    archive_family: Literal["evidence"]
    policy: EvidenceArchiveRef
    predecessor: EvidenceArchiveRef | None
    consideration: EvidenceConsideration
    decision: Literal["inserted", "rejected", "replaced", "tied", "incomparable"]
    admitted: EvidenceArchiveEntry | None
    displaced: list[EvidenceArchiveEntry]
    reason: NonEmpty
    historical_claim: Literal["historical_formal_evidence"]
    current_active_eligibility: Literal["not_evaluated"]
    current_active_blocker: Literal["SPEC-032 exact currency owner fact unavailable"]
    operational_authority: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceArchiveEvent:
        if self.admitted is not None and self.admitted.consideration != self.consideration:
            raise ValueError("evidence archive admitted scope mismatch")
        if self.event_id != _identity(self, "event_id"):
            raise ValueError("evidence archive event identity mismatch")
        return self


class EvidenceArchiveSnapshot(StrictModel):
    schema_id: Literal["apex-research.evidence-archive.v1"] = Field(alias="schema")
    kind: Literal["snapshot"]
    snapshot_id: Sha256
    archive_family: Literal["evidence"]
    archive_label: Literal["evidence archive"]
    entry_label: Literal["historical formal evidence leader"]
    policy: EvidenceArchiveRef
    taxonomy: TaxonomyRef
    predecessor: EvidenceArchiveRef | None
    events: list[EvidenceArchiveRef] = Field(min_length=1)
    historical_entries: list[EvidenceArchiveEntry]
    all_historical_entries: list[EvidenceArchiveEntry]
    current_active_entries: list[EvidenceArchiveEntry]
    current_active_view: Literal["blocked"]
    current_active_reason: Literal["SPEC-032 exact currency owner fact unavailable"]
    operational_authority: Literal["forbidden"]
    production_claim: Literal["forbidden"]
    live_trading_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceArchiveSnapshot:
        if self.current_active_entries:
            raise ValueError("Evidence active view lacks exact currency owner facts")
        if self.snapshot_id != _identity(self, "snapshot_id"):
            raise ValueError("evidence archive snapshot identity mismatch")
        return self


class EvidenceArchiveLifecycleEvent(StrictModel):
    schema_id: Literal["apex-research.evidence-archive.v1"] = Field(alias="schema")
    kind: Literal["lifecycle_event"]
    event_id: Sha256
    archive_family: Literal["evidence"]
    action: Literal["retired", "superseded", "source_invalidated", "taxonomy_revision"]
    policy: EvidenceArchiveRef
    predecessor: EvidenceArchiveRef
    previous_taxonomy: TaxonomyRef
    taxonomy: TaxonomyRef
    target_entry_id: Sha256 | None
    owner_source: PublishedRef
    reason: NonEmpty
    current_active_eligibility: Literal["not_evaluated"]
    current_active_blocker: Literal["SPEC-032 exact currency owner fact unavailable"]
    operational_authority: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceArchiveLifecycleEvent:
        revision = self.action == "taxonomy_revision"
        if revision != (self.target_entry_id is None) or revision != (
            self.taxonomy != self.previous_taxonomy
        ):
            raise ValueError("evidence lifecycle transition mismatch")
        if self.event_id != _identity(self, "event_id"):
            raise ValueError("evidence lifecycle identity mismatch")
        return self


class EvidenceArchiveView(StrictModel):
    schema_id: Literal["apex-research.evidence-archive.v1"] = Field(alias="schema")
    kind: Literal["active_view"]
    snapshot_id: Sha256
    archive_family: Literal["evidence"]
    archive_label: Literal["evidence archive"]
    entry_label: Literal["historical formal evidence leader"]
    policy: EvidenceArchiveRef
    taxonomy: TaxonomyRef
    predecessor: EvidenceArchiveRef
    events: list[EvidenceArchiveRef] = Field(min_length=1)
    historical_entries: list[EvidenceArchiveEntry]
    eligible_historical_entries: list[EvidenceArchiveEntry]
    known_niches: list[Sha256]
    occupied_historical_niches: list[Sha256]
    empty_historical_niches: list[Sha256]
    current_active_entries: list[EvidenceArchiveEntry]
    current_active_view: Literal["blocked"]
    current_active_reason: Literal["SPEC-032 exact currency owner fact unavailable"]
    operational_authority: Literal["forbidden"]
    production_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def verify_identity(self) -> EvidenceArchiveView:
        if self.current_active_entries:
            raise ValueError("Evidence active view lacks exact currency owner facts")
        if self.snapshot_id != _identity(self, "snapshot_id"):
            raise ValueError("evidence archive active view identity mismatch")
        return self


ExplorationArchiveRecord = Annotated[
    ExplorationArchivePolicy
    | ExplorationArchiveEvent
    | ExplorationArchiveSnapshot
    | ExplorationArchiveLifecycleEvent
    | ExplorationArchiveView,
    Field(discriminator="kind"),
]
EvidenceArchiveRecord = Annotated[
    EvidenceArchivePolicy
    | EvidenceArchiveEvent
    | EvidenceArchiveSnapshot
    | EvidenceArchiveLifecycleEvent
    | EvidenceArchiveView,
    Field(discriminator="kind"),
]
ArchiveRecord = ExplorationArchiveRecord | EvidenceArchiveRecord


class ExplorationArchiveReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.exploration-archive-read-model.v1"] = Field(
        default="strategy-reporting.exploration-archive-read-model.v1", alias="schema"
    )
    presentation_label: Literal["exploration archive — discovery leaders"]
    archive_family: Literal["exploration"]
    record: ExplorationArchiveRecord
    publication: PublicationReadback
    archive_publications: list[PublicationReadback]
    external_publications: list[PublicationReadback]


class EvidenceArchiveReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.evidence-archive-read-model.v1"] = Field(
        default="strategy-reporting.evidence-archive-read-model.v1", alias="schema"
    )
    presentation_label: Literal["evidence archive — historical formal evidence leaders"]
    archive_family: Literal["evidence"]
    record: EvidenceArchiveRecord
    publication: PublicationReadback
    archive_publications: list[PublicationReadback]
    external_publications: list[PublicationReadback]
    current_active_eligibility: Literal["not_evaluated"]
    current_active_reason: Literal["SPEC-032 exact currency owner fact unavailable"]


ArchiveReadModel = ExplorationArchiveReadModel | EvidenceArchiveReadModel


def _identity(value: StrictModel, field: str) -> str:
    return canonical_sha256(value.model_dump(mode="json", by_alias=True, exclude={field}))


__all__ = [
    "EVIDENCE_ARCHIVE_RECORD_TYPE",
    "EXPLORATION_ARCHIVE_RECORD_TYPE",
    "SPEC032_BLOCKER",
    "ArchiveReadModel",
    "ArchiveRecord",
    "ArchiveRecordRef",
    "EvidenceArchiveReadModel",
    "EvidenceArchiveRecord",
    "ExplorationArchiveReadModel",
    "ExplorationArchiveRecord",
]
