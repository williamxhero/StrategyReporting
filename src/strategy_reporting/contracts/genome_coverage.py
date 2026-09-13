"""Public, presentation-only Genome comparison facts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from strategy_reporting.models import StrictModel

Comparison = Literal["equal", "different", "incomparable", "unknown"]


class GenomeCoverageSource(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)


class GenomeCoverageReadModel(StrictModel):
    schema_id: Literal["strategy-reporting.genome-coverage-read-model.v1"] = Field(
        default="strategy-reporting.genome-coverage-read-model.v1", alias="schema"
    )
    source: GenomeCoverageSource
    identities: dict[str, Any]
    lifecycle: dict[str, Any]
    comparison: dict[str, Any]
    research_brief: dict[str, Any]
    links: list[GenomeCoverageSource]
    availability: dict[str, str]


__all__ = ["GenomeCoverageReadModel", "GenomeCoverageSource"]
