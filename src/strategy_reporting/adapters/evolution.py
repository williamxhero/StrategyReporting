"""Workspace-only evolution progress readback without domain calculations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal, cast

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.contracts.evolution import (
    EVOLUTION_RECORD_TYPE,
    SPEC032_BLOCKER,
    EvolutionArchiveOwnerFact,
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
_EVOLUTION_FIELDS = {
    "policy": frozenset(
        [
            "schema",
            "kind",
            "policy_id",
            "campaign",
            "archive_policy",
            "archive_taxonomy",
            "candidate_gate_policy",
            "focused_policy",
            "selection_policy_revision",
            "variation_policy_revision",
            "migration_policy_revision",
            "stopping_policy_revision",
            "allowed_migration_policy_revisions",
            "stage_budgets",
        ]
    ),
    "island": frozenset(
        [
            "schema",
            "kind",
            "island_id",
            "policy",
            "campaign",
            "archive_snapshot",
            "generation",
            "seed_population",
            "rng",
        ]
    ),
    "generation_snapshot": frozenset(
        [
            "schema",
            "kind",
            "snapshot_id",
            "island",
            "policy",
            "archive_snapshot",
            "generation",
            "predecessor",
            "population",
            "events",
            "status",
        ]
    ),
    "intent": frozenset(
        [
            "schema",
            "kind",
            "intent_id",
            "position",
            "operation",
            "archive_snapshot",
            "eligible_parents",
            "eligible_cousins",
            "parents",
            "cousins",
            "cross_island_snapshots",
            "target_niche",
            "policy_inputs",
            "random_draws",
            "variation_revision",
            "variation_parameters",
            "tie_decisions",
        ]
    ),
    "generation_plan": frozenset(
        ["schema", "kind", "plan_id", "island", "predecessor", "generation", "intents"]
    ),
    "engine_binding": frozenset(
        ["schema", "kind", "binding_id", "plan", "request", "reservation", "result"]
    ),
    "descendant": frozenset(
        [
            "schema",
            "kind",
            "descendant_id",
            "plan",
            "intent",
            "engine_binding",
            "hypothesis",
            "candidate",
            "static_assessment",
            "disposition",
            "reason",
        ]
    ),
    "discovery_outcome": frozenset(
        [
            "schema",
            "kind",
            "outcome_id",
            "plan",
            "descendant",
            "candidate",
            "descriptor",
            "archive_event",
            "status",
            "reason",
        ]
    ),
    "promotion_frontier": frozenset(
        [
            "schema",
            "kind",
            "frontier_id",
            "plan",
            "archive_snapshot",
            "capacity",
            "outcomes",
            "decisions",
        ]
    ),
    "formal_outcome": frozenset(
        [
            "schema",
            "kind",
            "outcome_id",
            "frontier",
            "candidate",
            "stages",
            "evidence_entry",
            "attachments",
            "current_evidence_eligibility",
            "current_evidence_reason",
            "research_validated",
            "research_qualified",
        ]
    ),
    "lifecycle_event": frozenset(
        [
            "schema",
            "kind",
            "event_id",
            "island",
            "policy",
            "archive_snapshot",
            "generation",
            "predecessor",
            "action",
            "source_island",
            "target_island",
            "candidates",
            "intent",
            "owner_refs",
            "reason",
        ]
    ),
}
_ARCHIVE_FAMILIES = {
    "apex-research.exploration-archive.v1": "exploration",
    "apex-research.evidence-archive.v1": "evidence",
}


class EvolutionProgressReadModelBuilder:
    """Present exact owner-published island facts without choosing or scoring them."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, island: EvolutionIslandRef) -> EvolutionProgressReadModel:
        if not isinstance(island, EvolutionIslandRef):
            raise TypeError("evolution reader requires an EvolutionIslandRef")
        try:
            publications = self._evolution_publications(island)
            root = publications[island.record_id]
            if root.payload.get("kind") != "island":
                raise ContractError(
                    "evolution_island_missing", "evolution island owner record is unavailable"
                )
            related = [publications[key] for key in sorted(publications)]
            summaries = [self._summary(item) for item in related]
            promotion = self._promotion_summaries(related)
            policy = self._owner_ref(root.payload.get("policy"), "island policy")
            archive_snapshot = self._owner_ref(
                root.payload.get("archive_snapshot"), "island archive snapshot"
            )
            seed_population = self._objects(root.payload.get("seed_population"), "seed population")
            rng = self._object(root.payload.get("rng"), "island rng")
            return EvolutionProgressReadModel(
                island=island,
                policy=policy,
                archive_snapshot=archive_snapshot,
                seed_candidate_ids=[
                    str(self._object(item.get("candidate"), "seed Candidate")["record_id"])
                    for item in seed_population
                ],
                rng=rng,
                records=summaries,
                generated=[item for item in summaries if item.kind == "descendant"],
                rejected_or_incomparable=[
                    item
                    for item in summaries
                    if (item.kind == "descendant" and item.status == "rejected")
                    or (
                        item.kind == "discovery_outcome"
                        and item.status in {"rejected", "incomparable", "failed"}
                    )
                ],
                promoted=[item for item in promotion if item.disposition == "promoted"],
                non_promoted=[item for item in promotion if item.disposition != "promoted"],
                formal_outcomes=self._formal_summaries(related),
                lifecycle_events=self._lifecycle_summaries(related),
                budget_owner_facts=self._budget_owner_facts(related),
                archive_owner_facts=self._archive_owner_facts(related),
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

    def _evolution_publications(self, island: EvolutionIslandRef) -> dict[str, PublicationReadback]:
        root_raw = self.workspace.client.get_record(island.record_id)
        root_publication = PublicationReadback.model_validate(root_raw, strict=True)
        policy = self._owner_ref(root_publication.payload.get("policy"), "island policy")
        raw = [root_raw, self.workspace.client.get_record(policy.record_id)]
        raw.extend(self._query_evolution_descendants(island))
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
            unknown_fields = set(publication.payload) - _EVOLUTION_FIELDS[str(kind)]
            if unknown_fields:
                raise ContractError(
                    "evolution_unknown_fields",
                    f"evolution owner record has unknown fields: {sorted(unknown_fields)}",
                )
            payload_refs = self._payload_record_refs(publication.payload)
            lineage_refs = [(item.source_kind, item.source_id) for item in publication.lineage]
            if len(lineage_refs) != len(set(lineage_refs)) or not set(lineage_refs) <= payload_refs:
                raise ContractError(
                    "evolution_lineage_mismatch",
                    "evolution publication lineage differs from owner payload references",
                )
            identity_payload = dict(publication.payload)
            identity = identity_payload.pop(identity_field, None)
            if identity != publication.record_id or identity != canonical_sha256(identity_payload):
                raise ContractError(
                    "evolution_identity_mismatch",
                    "evolution payload identity differs from owner publication",
                )
            previous = values.setdefault(publication.record_id, publication)
            if previous != publication:
                raise ContractError(
                    "evolution_duplicate_record", "duplicate evolution publication identity"
                )
        return values

    def _query_evolution_descendants(self, island: EvolutionIslandRef) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen = {island.record_id}
        frontier = [island.record_id]
        snapshot_token: str | None = None
        for _depth in range(32):
            discovered: list[str] = []
            for offset in range(0, len(frontier), 50):
                page_records, snapshot_token = self._query_pages(
                    roots=tuple(
                        {"kind": EVOLUTION_RECORD_TYPE, "id": record_id}
                        for record_id in frontier[offset : offset + 50]
                    ),
                    relations=(),
                    record_types=(EVOLUTION_RECORD_TYPE,),
                    max_depth=1,
                    snapshot_token=snapshot_token,
                )
                for item in page_records:
                    publication = self._object(item, "evolution lineage publication")
                    record_id = publication.get("record_id")
                    if isinstance(record_id, str) and record_id not in seen:
                        seen.add(record_id)
                        discovered.append(record_id)
                        records.append(publication)
            if not discovered:
                return records
            frontier = discovered
        raise ContractError(
            "evolution_lineage_too_deep", "evolution lineage exceeds the bounded read depth"
        )

    def _query_pages(
        self,
        *,
        roots: Iterable[Mapping[str, Any]],
        relations: tuple[str, ...],
        record_types: tuple[str, ...],
        max_depth: int,
        snapshot_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        records: list[dict[str, Any]] = []
        roots = tuple(roots)
        cursor: str | None = None
        while True:
            page = self.workspace.client.query_lineage(
                roots=roots,
                direction="descendants",
                relations=relations,
                record_types=record_types,
                max_depth=max_depth,
                page_size=100,
                cursor=cursor,
                snapshot_token=snapshot_token,
            )
            page_records = page.get("records")
            token = page.get("snapshot_token")
            if not isinstance(page_records, list) or not isinstance(token, str):
                raise ContractError("evolution_lineage_invalid", "lineage page is malformed")
            if snapshot_token is not None and token != snapshot_token:
                raise ContractError("evolution_lineage_drift", "lineage snapshot token drifted")
            snapshot_token = token
            records.extend(self._object(item, "lineage publication") for item in page_records)
            next_cursor = page.get("next_cursor")
            if next_cursor is None:
                return records, snapshot_token
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise ContractError("evolution_lineage_invalid", "lineage cursor is malformed")
            cursor = next_cursor

    @staticmethod
    def _summary(publication: PublicationReadback) -> EvolutionRecordSummary:
        payload = publication.payload
        status = payload.get("status", payload.get("disposition"))
        return EvolutionRecordSummary(
            record_id=publication.record_id,
            kind=cast(Any, str(payload["kind"])),
            generation=payload.get("generation"),
            status=None if status is None else str(status),
            source_ids=sorted(item.source_id for item in publication.lineage),
            owner_payload=dict(payload),
        )

    @classmethod
    def _promotion_summaries(
        cls, publications: list[PublicationReadback]
    ) -> list[EvolutionPromotionSummary]:
        result: list[EvolutionPromotionSummary] = []
        for publication in publications:
            if publication.payload.get("kind") != "promotion_frontier":
                continue
            for raw in cls._objects(publication.payload.get("decisions"), "promotion decisions"):
                outcome = cls._object(raw.get("outcome"), "promotion outcome")
                candidate = cls._object(raw.get("candidate"), "promotion Candidate")
                result.append(
                    EvolutionPromotionSummary(
                        outcome_id=str(outcome["record_id"]),
                        candidate_id=str(candidate["record_id"]),
                        disposition=cast(Any, str(raw["disposition"])),
                        observations=cls._objects(raw.get("observations"), "observations"),
                        reason=str(raw["reason"]),
                    )
                )
        return sorted(result, key=lambda item: item.outcome_id)

    @classmethod
    def _lifecycle_summaries(
        cls, publications: list[PublicationReadback]
    ) -> list[EvolutionLifecycleSummary]:
        result = []
        for item in publications:
            payload = item.payload
            if payload.get("kind") != "lifecycle_event":
                continue
            result.append(
                EvolutionLifecycleSummary(
                    record_id=item.record_id,
                    generation=payload["generation"],
                    action=str(payload["action"]),
                    reason=str(payload["reason"]),
                    policy=cls._owner_ref(payload.get("policy"), "lifecycle policy"),
                    archive_snapshot=cls._owner_ref(
                        payload.get("archive_snapshot"), "lifecycle archive snapshot"
                    ),
                    candidate_ids=[
                        str(cls._object(value, "lifecycle Candidate")["record_id"])
                        for value in cls._objects(payload.get("candidates"), "Candidates")
                    ],
                    owner_refs=[
                        cls._owner_ref(value, "lifecycle owner ref")
                        for value in cls._objects(payload.get("owner_refs"), "owner refs")
                    ],
                )
            )
        return sorted(result, key=lambda value: (value.generation, value.record_id))

    @classmethod
    def _formal_summaries(
        cls, publications: list[PublicationReadback]
    ) -> list[EvolutionFormalSummary]:
        result = []
        for item in publications:
            payload = item.payload
            if payload.get("kind") != "formal_outcome":
                continue
            candidate = cls._object(payload.get("candidate"), "formal Candidate")
            frontier = cls._object(payload.get("frontier"), "formal frontier")
            evidence = payload.get("evidence_entry")
            result.append(
                EvolutionFormalSummary(
                    record_id=item.record_id,
                    candidate_id=str(candidate["record_id"]),
                    frontier_id=str(frontier["record_id"]),
                    stages=cls._objects(payload.get("stages"), "formal stages"),
                    evidence_entry=(
                        None if evidence is None else cls._owner_ref(evidence, "evidence entry")
                    ),
                    attachments=cls._object(payload.get("attachments"), "formal attachments"),
                    research_validated=payload["research_validated"],
                    research_qualified=payload["research_qualified"],
                    current_evidence_eligibility=payload["current_evidence_eligibility"],
                    current_evidence_reason=payload["current_evidence_reason"],
                )
            )
        return sorted(result, key=lambda value: value.record_id)

    def _budget_owner_facts(self, publications: list[PublicationReadback]) -> list[OwnerFactRef]:
        references: dict[tuple[str, str], OwnerFactRef] = {}
        for item in self._lifecycle_summaries(publications):
            for reference in item.owner_refs:
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

    def _archive_owner_facts(
        self, publications: list[PublicationReadback]
    ) -> list[EvolutionArchiveOwnerFact]:
        references: dict[tuple[str, str], OwnerFactRef] = {}
        keys = {"archive_policy", "archive_snapshot", "archive_event", "evidence_entry"}
        for publication in publications:
            for key, value in publication.payload.items():
                if key in keys and isinstance(value, Mapping):
                    reference = self._owner_ref(value, f"evolution {key}")
                    expected_family = "evidence" if key == "evidence_entry" else "exploration"
                    if _ARCHIVE_FAMILIES.get(reference.record_type) != expected_family:
                        raise ContractError(
                            "evolution_archive_family_mismatch",
                            f"evolution {key} uses the wrong archive family",
                        )
                    references[(reference.record_type, reference.record_id)] = reference
        facts = [self._archive_fact(reference) for reference in references.values()]
        event_roots = tuple(
            {"kind": item.record_type, "id": item.record_id}
            for item in facts
            if item.kind == "event" and item.archive_family == "exploration"
        )
        if event_roots:
            archive_records, _snapshot_token = self._query_pages(
                roots=event_roots,
                relations=("archive-event",),
                record_types=("apex-research.exploration-archive.v1",),
                max_depth=1,
            )
            for raw in archive_records:
                publication = PublicationReadback.model_validate(raw, strict=True)
                facts.append(
                    self._archive_fact(
                        OwnerFactRef(
                            record_id=publication.record_id,
                            record_type=publication.record_type,
                        )
                    )
                )
        unique = {(item.record_type, item.record_id): item for item in facts}
        return [unique[key] for key in sorted(unique)]

    def _archive_fact(self, reference: OwnerFactRef) -> EvolutionArchiveOwnerFact:
        publication = PublicationReadback.model_validate(
            self.workspace.client.get_record(reference.record_id), strict=True
        )
        family = _ARCHIVE_FAMILIES.get(publication.record_type)
        if (
            family is None
            or publication.record_type != reference.record_type
            or publication.payload.get("archive_family") != family
            or not isinstance(publication.payload.get("kind"), str)
            or publication.artifacts
        ):
            raise ContractError(
                "evolution_archive_fact_invalid", "archive owner fact family or identity drifted"
            )
        return EvolutionArchiveOwnerFact(
            record_id=publication.record_id,
            record_type=cast(Any, publication.record_type),
            archive_family=cast(Literal["exploration", "evidence"], family),
            kind=str(publication.payload["kind"]),
            owner_payload=dict(publication.payload),
        )

    @staticmethod
    def _owner_ref(value: object, label: str) -> OwnerFactRef:
        raw = EvolutionProgressReadModelBuilder._object(value, label)
        return OwnerFactRef(record_id=str(raw["record_id"]), record_type=str(raw["record_type"]))

    @staticmethod
    def _object(value: object, label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ContractError("evolution_owner_payload_invalid", f"{label} is not an object")
        return {str(key): item for key, item in value.items()}

    @classmethod
    def _objects(cls, value: object, label: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ContractError("evolution_owner_payload_invalid", f"{label} is not an array")
        return [cls._object(item, label) for item in value]

    @classmethod
    def _payload_record_refs(cls, value: object) -> set[tuple[str, str]]:
        references: set[tuple[str, str]] = set()
        if isinstance(value, Mapping):
            record_id = value.get("record_id")
            record_type = value.get("record_type")
            if isinstance(record_id, str) and isinstance(record_type, str):
                references.add((record_type, record_id))
            for child in value.values():
                references.update(cls._payload_record_refs(child))
        elif isinstance(value, list):
            for child in value:
                references.update(cls._payload_record_refs(child))
        return references


__all__ = ["EvolutionProgressReadModelBuilder"]
