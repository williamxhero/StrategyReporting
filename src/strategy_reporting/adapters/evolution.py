"""Workspace-only evolution progress readback without domain calculations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.contracts.evolution import (
    EVOLUTION_RECORD_TYPE,
    SPEC032_BLOCKER,
    EvolutionFormalSummary,
    EvolutionIslandRef,
    EvolutionLifecycleSummary,
    EvolutionProgressReadModel,
    EvolutionPromotionSummary,
    EvolutionRecordSummary,
    OwnerFactRef,
)
from strategy_reporting.errors import ContractError, ReportingError, SourceError

_IDENTITY_FIELDS = {
    "policy": "policy_id",
    "island": "island_id",
    "generation_snapshot": "snapshot_id",
    "intent": "intent_id",
    "generation_plan": "plan_id",
    "engine_binding": "binding_id",
    "descendant": "descendant_id",
    "discovery_outcome": "outcome_id",
    "promotion_frontier": "frontier_id",
    "formal_outcome": "outcome_id",
    "lifecycle_event": "event_id",
}


class EvolutionProgressReadModelBuilder:
    """Present all owner-published island facts without choosing or scoring them."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, island: EvolutionIslandRef) -> EvolutionProgressReadModel:
        if not isinstance(island, EvolutionIslandRef):
            raise TypeError("evolution reader requires an EvolutionIslandRef")
        try:
            publications = self._evolution_publications()
            root = publications.get(island.record_id)
            if root is None or root.payload.get("kind") != "island":
                raise ContractError(
                    "evolution_island_missing", "evolution island owner record is unavailable"
                )
            related = self._related(publications, island.record_id)
            summaries = [self._summary(item) for item in related]
            generated = [
                summary for summary in summaries if summary.kind == "descendant"
            ]
            rejected = [
                summary
                for summary in summaries
                if (
                    summary.kind == "descendant" and summary.status == "rejected"
                )
                or (
                    summary.kind == "discovery_outcome"
                    and summary.status in {"rejected", "incomparable", "failed"}
                )
            ]
            promotion = self._promotion_summaries(related)
            lifecycle = self._lifecycle_summaries(related)
            formal = self._formal_summaries(related)
            budget = self._budget_owner_facts(related)
            return EvolutionProgressReadModel(
                island=island,
                records=summaries,
                generated=generated,
                rejected_or_incomparable=rejected,
                promoted=[item for item in promotion if item.disposition == "promoted"],
                non_promoted=[item for item in promotion if item.disposition != "promoted"],
                formal_outcomes=formal,
                lifecycle_events=lifecycle,
                budget_owner_facts=budget,
                exploration_label="exploration archive — discovery leaders",
                evidence_label="evidence archive — historical formal evidence leaders",
                current_evidence_eligibility="not_evaluated",
                current_evidence_reason=SPEC032_BLOCKER,
            )
        except ReportingError:
            raise
        except ValidationError as exc:
            raise ContractError("evolution_contract_invalid", str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("evolution_readback_invalid", str(exc)) from exc
        except Exception as exc:
            raise SourceError(
                "evolution_source_failed", f"cannot read evolution owner facts: {exc}"
            ) from exc

    def _evolution_publications(self) -> dict[str, PublicationReadback]:
        raw = self.workspace.client.list_records(
            record_type=EVOLUTION_RECORD_TYPE, limit=10_000
        )
        if not isinstance(raw, list):
            raise ContractError(
                "evolution_listing_invalid", "Workspace evolution listing is not an array"
            )
        values: dict[str, PublicationReadback] = {}
        for item in raw:
            publication = PublicationReadback.model_validate(item, strict=True)
            if (
                publication.record_type != EVOLUTION_RECORD_TYPE
                or publication.payload.get("schema") != EVOLUTION_RECORD_TYPE
                or publication.artifacts
            ):
                raise ContractError(
                    "evolution_publication_invalid", "evolution publication envelope drifted"
                )
            kind = publication.payload.get("kind")
            identity_field = _IDENTITY_FIELDS.get(str(kind))
            if identity_field is None:
                raise ContractError("evolution_kind_invalid", "unknown evolution record kind")
            identity_payload = dict(publication.payload)
            identity = identity_payload.pop(identity_field, None)
            if (
                identity != publication.record_id
                or identity != canonical_sha256(identity_payload)
            ):
                raise ContractError(
                    "evolution_identity_mismatch",
                    "evolution payload identity differs from owner publication",
                )
            if publication.record_id in values:
                raise ContractError(
                    "evolution_duplicate_record", "duplicate evolution publication identity"
                )
            values[publication.record_id] = publication
        return values

    @staticmethod
    def _related(
        publications: dict[str, PublicationReadback], island_id: str
    ) -> list[PublicationReadback]:
        included = {island_id}
        changed = True
        while changed:
            changed = False
            for publication in publications.values():
                if publication.record_id in included:
                    continue
                if any(item.source_id in included for item in publication.lineage):
                    included.add(publication.record_id)
                    changed = True
        return [publications[key] for key in sorted(included)]

    @staticmethod
    def _summary(publication: PublicationReadback) -> EvolutionRecordSummary:
        payload = publication.payload
        status = payload.get("status")
        if status is None:
            status = payload.get("disposition")
        return EvolutionRecordSummary(
            record_id=publication.record_id,
            kind=cast(
                Literal[
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
                ],
                str(payload["kind"]),
            ),
            generation=payload.get("generation"),
            status=None if status is None else str(status),
        )

    @staticmethod
    def _promotion_summaries(
        publications: list[PublicationReadback],
    ) -> list[EvolutionPromotionSummary]:
        result: list[EvolutionPromotionSummary] = []
        for publication in publications:
            if publication.payload.get("kind") != "promotion_frontier":
                continue
            decisions = publication.payload.get("decisions")
            if not isinstance(decisions, list):
                raise ContractError(
                    "evolution_frontier_invalid", "promotion decisions are not an array"
                )
            for raw in decisions:
                if not isinstance(raw, Mapping) or not isinstance(raw.get("outcome"), Mapping):
                    raise ContractError(
                        "evolution_frontier_invalid", "promotion decision is malformed"
                    )
                result.append(
                    EvolutionPromotionSummary(
                        outcome_id=str(raw["outcome"]["record_id"]),
                        disposition=cast(
                            Literal[
                                "promoted", "held", "incomparable", "not_evaluated"
                            ],
                            str(raw["disposition"]),
                        ),
                    )
                )
        return sorted(result, key=lambda item: item.outcome_id)

    @staticmethod
    def _lifecycle_summaries(
        publications: list[PublicationReadback],
    ) -> list[EvolutionLifecycleSummary]:
        return sorted(
            (
                EvolutionLifecycleSummary(
                    record_id=item.record_id,
                    generation=item.payload["generation"],
                    action=str(item.payload["action"]),
                    reason=str(item.payload["reason"]),
                )
                for item in publications
                if item.payload.get("kind") == "lifecycle_event"
            ),
            key=lambda item: (item.generation, item.record_id),
        )

    @staticmethod
    def _formal_summaries(
        publications: list[PublicationReadback],
    ) -> list[EvolutionFormalSummary]:
        result = []
        for item in publications:
            payload = item.payload
            if payload.get("kind") != "formal_outcome":
                continue
            candidate = payload.get("candidate")
            if not isinstance(candidate, Mapping):
                raise ContractError(
                    "evolution_formal_invalid", "formal Candidate reference is malformed"
                )
            result.append(
                EvolutionFormalSummary(
                    record_id=item.record_id,
                    candidate_id=str(candidate["record_id"]),
                    research_validated=payload["research_validated"],
                    research_qualified=payload["research_qualified"],
                    current_evidence_eligibility=payload["current_evidence_eligibility"],
                    current_evidence_reason=payload["current_evidence_reason"],
                )
            )
        return sorted(result, key=lambda item: item.record_id)

    def _budget_owner_facts(
        self, publications: list[PublicationReadback]
    ) -> list[OwnerFactRef]:
        references: dict[tuple[str, str], OwnerFactRef] = {}
        for item in publications:
            if item.payload.get("kind") != "lifecycle_event":
                continue
            raw_refs = item.payload.get("owner_refs", [])
            if not isinstance(raw_refs, list):
                raise ContractError(
                    "evolution_lifecycle_invalid", "lifecycle owner refs are malformed"
                )
            for raw in raw_refs:
                reference = OwnerFactRef.model_validate(raw, strict=True)
                publication = PublicationReadback.model_validate(
                    self.workspace.client.get_record(reference.record_id), strict=True
                )
                if (
                    publication.record_id != reference.record_id
                    or publication.record_type != reference.record_type
                    or publication.artifacts
                ):
                    raise ContractError(
                        "evolution_owner_fact_invalid", "budget owner fact identity drifted"
                    )
                references[(reference.record_type, reference.record_id)] = reference
        return [references[key] for key in sorted(references)]


__all__ = ["EvolutionProgressReadModelBuilder"]
