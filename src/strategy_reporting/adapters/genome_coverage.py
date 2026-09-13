"""Consume the owner-published Genome report-source; never derive comparison facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.genome_coverage import (
    GenomeCoverageReadModel,
    GenomeCoverageSource,
)
from strategy_reporting.errors import ContractError, SourceError

SOURCE_TYPE = "apex-research.genome-report-source.v1"
_SECTIONS = ("identities", "lifecycle", "comparison", "research_brief")


class GenomeCoverageReadModelBuilder:
    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, source: GenomeCoverageSource) -> GenomeCoverageReadModel:
        try:
            raw = self.workspace.client.get_record(source.record_id)
            if (
                raw.get("record_id") != source.record_id
                or raw.get("record_type") != source.record_type
            ):
                raise ContractError("genome_source_identity_mismatch", "source identity differs")
            payload = raw.get("payload")
            if not isinstance(payload, Mapping):
                raise ContractError(
                    "genome_source_invalid", "report-source payload is not an object"
                )
            if source.record_type != SOURCE_TYPE:
                raise ContractError(
                    "genome_source_type_invalid", "unsupported public Genome source"
                )
            sections = {name: _safe_section(payload.get(name)) for name in _SECTIONS}
            links = (
                [_ref(item) for item in payload.get("links", [])]
                if isinstance(payload.get("links", []), list)
                else []
            )
            availability = {
                name: ("available" if name in payload else "unavailable") for name in _SECTIONS
            }
            return GenomeCoverageReadModel(
                source=source,
                identities=sections["identities"],
                lifecycle=sections["lifecycle"],
                comparison=sections["comparison"],
                research_brief=sections["research_brief"],
                links=links,
                availability=availability,
            )
        except (ContractError, SourceError):
            raise
        except ValidationError as exc:
            raise ContractError("genome_source_invalid", str(exc)) from exc
        except Exception as exc:
            raise SourceError("genome_source_failed", str(exc)) from exc


def _safe_section(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"status": "unavailable", "reason": "owner did not publish this section"}
    return dict(value)


def _ref(value: Any) -> GenomeCoverageSource:
    if not isinstance(value, Mapping):
        raise ContractError("genome_link_invalid", "source link is not an object")
    return GenomeCoverageSource.model_validate(value, strict=True)


__all__ = ["SOURCE_TYPE", "GenomeCoverageReadModelBuilder"]
