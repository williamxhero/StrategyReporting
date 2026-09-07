"""Presentation-only contracts for immutable Apex evolution facts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from strategy_reporting.models import StrictModel

EVOLUTION_RECORD_TYPE: Literal["apex-research.evolution.v1"] = (
    "apex-research.evolution.v1"
)
SPEC032_BLOCKER: Literal["SPEC-032 exact currency owner fact unavailable"] = (
    "SPEC-032 exact currency owner fact unavailable"
)
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvolutionIslandRef(StrictModel):
    record_id: Sha256
    record_type: Literal["apex-research.evolution.v1"] = EVOLUTION_RECORD_TYPE


class OwnerFactRef(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)


class EvolutionRecordSummary(StrictModel):
    record_id: Sha256
    kind: Literal[
        "policy",
        "island",
        "generation_snapshot",
        "intent",
        "generation_plan",
        "engine_binding",
        "descendant",
        "discovery_outcome",
        "promotion_frontier",
        "formal_outcome",
        "lifecycle_event",
    ]
    generation: int | None
    status: str | None


class EvolutionPromotionSummary(StrictModel):
    outcome_id: str = Field(min_length=1)
    disposition: Literal["promoted", "held", "incomparable", "not_evaluated"]


class EvolutionLifecycleSummary(StrictModel):
    record_id: Sha256
    generation: int = Field(ge=0)
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EvolutionFormalSummary(StrictModel):
    record_id: Sha256
    candidate_id: str = Field(min_length=1)
    research_validated: Literal["not_evaluated"]
    research_qualified: Literal["not_evaluated"]
    current_evidence_eligibility: Literal["not_evaluated"]
    current_evidence_reason: Literal["SPEC-032 exact currency owner fact unavailable"]


class EvolutionProgressReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.evolution-progress-read-model.v1"] = Field(
        default="strategy-reporting.evolution-progress-read-model.v1", alias="schema"
    )
    island: EvolutionIslandRef
    records: list[EvolutionRecordSummary]
    generated: list[EvolutionRecordSummary]
    rejected_or_incomparable: list[EvolutionRecordSummary]
    promoted: list[EvolutionPromotionSummary]
    non_promoted: list[EvolutionPromotionSummary]
    formal_outcomes: list[EvolutionFormalSummary]
    lifecycle_events: list[EvolutionLifecycleSummary]
    budget_owner_facts: list[OwnerFactRef]
    exploration_label: Literal["exploration archive — discovery leaders"]
    evidence_label: Literal["evidence archive — historical formal evidence leaders"]
    current_evidence_eligibility: Literal["not_evaluated"]
    current_evidence_reason: Literal["SPEC-032 exact currency owner fact unavailable"]


__all__ = [
    "EVOLUTION_RECORD_TYPE",
    "SPEC032_BLOCKER",
    "EvolutionFormalSummary",
    "EvolutionIslandRef",
    "EvolutionLifecycleSummary",
    "EvolutionProgressReadModel",
    "EvolutionPromotionSummary",
    "EvolutionRecordSummary",
    "OwnerFactRef",
]
