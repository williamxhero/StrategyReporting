"""Strict presentation-side mirrors of Apex behavior descriptor records."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.models import StrictModel


class PublishedRef(StrictModel):
    record_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_type: str = Field(min_length=1)


class BehaviorTaxonomyRef(PublishedRef):
    record_type: Literal["apex-research.behavior-taxonomy.v1"]


class StrategyRevisionRef(PublishedRef):
    record_type: Literal["apex-research.strategy-candidate.v1"]
    semantic_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class DescriptorSourceRef(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)
    attempt_id: str | None
    request_hash: str | None
    result_hash: str | None

    @model_validator(mode="after")
    def verify_shape(self) -> DescriptorSourceRef:
        runtime = self.record_type == "quant-research.run-record.v1"
        exact = (self.attempt_id, self.request_hash, self.result_hash)
        if runtime:
            if (
                any(item is None for item in exact)
                or self.request_hash is None
                or self.result_hash is None
                or len(self.request_hash) != 64
                or len(self.result_hash) != 64
            ):
                raise ValueError("Runtime descriptor source identity is incomplete")
        elif any(item is not None for item in exact):
            raise ValueError("non-Runtime descriptor source carries attempt identity")
        return self


class CategoryDefinition(StrictModel):
    source_value: str = Field(min_length=1)
    value: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    human_label: str = Field(min_length=1)


class NumericBin(StrictModel):
    value: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    human_label: str = Field(min_length=1)
    lower: float | None
    upper: float | None
    lower_inclusive: bool
    upper_inclusive: bool


class CategoricalDimension(StrictModel):
    kind: Literal["categorical"]
    dimension_id: str = Field(min_length=1)
    human_label: str = Field(min_length=1)
    machine_definition: str = Field(min_length=1)
    source_selector: str = Field(min_length=1)
    transformation: Literal["identity"]
    unit: Literal["category"]
    missing_behavior: Literal["unavailable", "not_evaluated", "reject"]
    evidence_tiers: list[Literal["discovery", "formal"]]
    categories: list[CategoryDefinition] = Field(min_length=1)


class NumericDimension(StrictModel):
    kind: Literal["numeric"]
    dimension_id: str = Field(min_length=1)
    human_label: str = Field(min_length=1)
    machine_definition: str = Field(min_length=1)
    source_selector: str = Field(min_length=1)
    transformation: Literal["identity", "all_same_bin"]
    unit: Literal["ratio", "bars", "sessions", "calendar_days"]
    missing_behavior: Literal["unavailable", "not_evaluated", "reject"]
    evidence_tiers: list[Literal["discovery", "formal"]]
    bins: list[NumericBin] = Field(min_length=1)


BehaviorDimension = Annotated[CategoricalDimension | NumericDimension, Field(discriminator="kind")]


class BehaviorTaxonomy(StrictModel):
    schema_id: Literal["apex-research.behavior-taxonomy.v1"] = Field(alias="schema")
    taxonomy_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    dimensions: list[BehaviorDimension] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_identity(self) -> BehaviorTaxonomy:
        ids = [item.dimension_id for item in self.dimensions]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("behavior taxonomy dimensions are not canonical")
        identity = self.model_dump(mode="json", by_alias=True, exclude={"taxonomy_id"})
        if self.taxonomy_id != canonical_sha256(identity):
            raise ValueError("behavior taxonomy identity mismatch")
        return self


class DescriptorDimensionOutcome(StrictModel):
    dimension_id: str = Field(min_length=1)
    human_label: str = Field(min_length=1)
    machine_definition: str = Field(min_length=1)
    source_selector: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    status: Literal[
        "assigned", "unavailable", "not_evaluated", "incomparable", "unassigned", "rejected"
    ]
    evidence_tier: Literal["discovery", "formal"]
    sources: list[DescriptorSourceRef]
    value: str | None
    value_human_label: str | None
    reason: str | None
    comparability: dict[str, Any] | None
    source_values_micros: list[int]

    @model_validator(mode="after")
    def verify_state(self) -> DescriptorDimensionOutcome:
        if self.status == "assigned":
            if self.value is None or self.value_human_label is None or self.reason is not None:
                raise ValueError("assigned descriptor outcome is incomplete")
        elif self.value is not None or self.value_human_label is not None or not self.reason:
            raise ValueError("unassigned descriptor outcome is incomplete")
        keys = [(item.record_type, item.record_id) for item in self.sources]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("descriptor outcome sources are not canonical")
        return self


class DiscoveryBehaviorDescriptor(StrictModel):
    schema_id: Literal["apex-research.discovery-behavior-descriptor.v1"] = Field(alias="schema")
    descriptor_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_tier: Literal["discovery"]
    taxonomy: BehaviorTaxonomyRef
    candidate: StrategyRevisionRef
    sources: list[StrategyRevisionRef]
    dimensions: list[DescriptorDimensionOutcome]
    niche_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    niche_label: str = Field(min_length=1)
    niche_definition: str = Field(min_length=1)

    @model_validator(mode="after")
    def verify_identity(self) -> DiscoveryBehaviorDescriptor:
        if self.sources != [self.candidate] or any(
            item.evidence_tier != "discovery" for item in self.dimensions
        ):
            raise ValueError("discovery descriptor tier or sources mismatch")
        niche = {
            "evidence_tier": "discovery",
            "taxonomy": self.taxonomy.model_dump(mode="json"),
            "dimensions": [item.model_dump(mode="json") for item in self.dimensions],
        }
        if self.niche_id != canonical_sha256(niche):
            raise ValueError("discovery niche identity mismatch")
        identity = self.model_dump(mode="json", by_alias=True, exclude={"descriptor_id"})
        if self.descriptor_id != canonical_sha256(identity):
            raise ValueError("discovery descriptor identity mismatch")
        return self


class FormalBehaviorDescriptor(StrictModel):
    schema_id: Literal["apex-research.formal-behavior-descriptor.v1"] = Field(alias="schema")
    descriptor_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_tier: Literal["formal"]
    taxonomy: BehaviorTaxonomyRef
    candidate: StrategyRevisionRef
    evidence: PublishedRef
    validation_evidence: PublishedRef
    sources: list[DescriptorSourceRef]
    dimensions: list[DescriptorDimensionOutcome]
    niche_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    niche_label: str = Field(min_length=1)
    niche_definition: str = Field(min_length=1)

    @model_validator(mode="after")
    def verify_identity(self) -> FormalBehaviorDescriptor:
        keys = [(item.record_type, item.record_id) for item in self.sources]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("formal descriptor sources are not canonical")
        if any(item.evidence_tier != "formal" for item in self.dimensions):
            raise ValueError("formal descriptor tier mismatch")
        if any(item.status == "assigned" for item in self.dimensions) and not any(
            item.record_type == "quant-research.run-record.v1" for item in self.sources
        ):
            raise ValueError("assigned formal descriptor lacks Runtime owner source")
        niche = {
            "evidence_tier": "formal",
            "taxonomy": self.taxonomy.model_dump(mode="json"),
            "dimensions": [item.model_dump(mode="json") for item in self.dimensions],
            "sources": [item.model_dump(mode="json") for item in self.sources],
        }
        if self.niche_id != canonical_sha256(niche):
            raise ValueError("formal niche identity mismatch")
        identity = self.model_dump(mode="json", by_alias=True, exclude={"descriptor_id"})
        if self.descriptor_id != canonical_sha256(identity):
            raise ValueError("formal descriptor identity mismatch")
        return self


BehaviorDescriptor = DiscoveryBehaviorDescriptor | FormalBehaviorDescriptor


class BehaviorDescriptorRef(PublishedRef):
    record_type: Literal[
        "apex-research.discovery-behavior-descriptor.v1",
        "apex-research.formal-behavior-descriptor.v1",
    ]

    @classmethod
    def discovery(cls, record_id: str) -> BehaviorDescriptorRef:
        return cls(
            record_id=record_id,
            record_type="apex-research.discovery-behavior-descriptor.v1",
        )

    @classmethod
    def formal(cls, record_id: str) -> BehaviorDescriptorRef:
        return cls(
            record_id=record_id,
            record_type="apex-research.formal-behavior-descriptor.v1",
        )


class BehaviorDescriptorReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.behavior-descriptor-read-model.v1"] = Field(
        default="strategy-reporting.behavior-descriptor-read-model.v1", alias="schema"
    )
    presentation_label: Literal["exploration descriptor", "formal evidence descriptor"]
    evidence_tier: Literal["discovery", "formal"]
    descriptor: BehaviorDescriptor
    taxonomy: BehaviorTaxonomy

    @model_validator(mode="after")
    def verify_tier(self) -> BehaviorDescriptorReadModel:
        expected = (
            "exploration descriptor"
            if self.evidence_tier == "discovery"
            else "formal evidence descriptor"
        )
        if (
            self.presentation_label != expected
            or self.descriptor.evidence_tier != self.evidence_tier
        ):
            raise ValueError("behavior descriptor presentation tier mismatch")
        return self


__all__ = [
    "BehaviorDescriptorReadModel",
    "BehaviorDescriptorRef",
    "BehaviorTaxonomy",
    "DiscoveryBehaviorDescriptor",
    "FormalBehaviorDescriptor",
]
