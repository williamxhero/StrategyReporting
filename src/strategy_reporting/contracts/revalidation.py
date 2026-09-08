"""Presentation-only contract for SPEC-032 owner publications."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.models import StrictModel


class RevalidationRecordRef(StrictModel):
    record_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_type: Literal["apex-research.revalidation-closure.v1"] = (
        "apex-research.revalidation-closure.v1"
    )


class RevalidationReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.revalidation-read-model.v1"] = Field(
        default="strategy-reporting.revalidation-read-model.v1", alias="schema"
    )
    root: RevalidationRecordRef
    read_status: Literal["complete", "blocked"]
    reason: str = Field(min_length=1)
    maturity: str | None
    currency: str | None
    trigger_observations: list[dict[str, Any]]
    campaign: dict[str, Any] | None
    budget: list[dict[str, Any]]
    stages: list[dict[str, Any]]
    decays: list[dict[str, Any]]
    comparison: dict[str, Any]
    supersession: dict[str, Any]
    archive: dict[str, Any] | None
    evidence_publication: dict[str, Any] | None
    qualification_revalidation: dict[str, Any] | None
    missing_facts: list[str]
    owner_publications: list[PublicationReadback]
    inference: Literal["forbidden"] = "forbidden"

    @model_validator(mode="after")
    def verify_fail_closed_status(self) -> RevalidationReadModel:
        if self.missing_facts != sorted(set(self.missing_facts)):
            raise ValueError("missing revalidation facts must be unique and canonical")
        publication_ids = [item.record_id for item in self.owner_publications]
        if publication_ids != sorted(set(publication_ids)):
            raise ValueError("owner publications must be unique and canonical")
        if (self.read_status == "blocked") != bool(self.missing_facts):
            raise ValueError("missing owner facts must fail closed")
        return self


__all__ = ["RevalidationReadModel", "RevalidationRecordRef"]
