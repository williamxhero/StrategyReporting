"""Workspace-only archive readback without archive-domain calculations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from pydantic import TypeAdapter, ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.contracts.quality_diversity_archives import (
    EVIDENCE_ARCHIVE_RECORD_TYPE,
    EXPLORATION_ARCHIVE_RECORD_TYPE,
    SPEC032_BLOCKER,
    ArchiveReadModel,
    ArchiveRecord,
    ArchiveRecordRef,
    EvidenceArchiveEvent,
    EvidenceArchiveLifecycleEvent,
    EvidenceArchivePolicy,
    EvidenceArchiveReadModel,
    EvidenceArchiveRecord,
    EvidenceArchiveSnapshot,
    EvidenceArchiveView,
    ExplorationArchiveEntry,
    ExplorationArchiveEvent,
    ExplorationArchiveLifecycleEvent,
    ExplorationArchivePolicy,
    ExplorationArchiveReadModel,
    ExplorationArchiveRecord,
    ExplorationArchiveSnapshot,
    ExplorationArchiveView,
    PublishedRef,
)
from strategy_reporting.errors import ContractError, ReportingError, SourceError

_EXPLORATION_ADAPTER: TypeAdapter[ExplorationArchiveRecord] = TypeAdapter(ExplorationArchiveRecord)
_EVIDENCE_ADAPTER: TypeAdapter[EvidenceArchiveRecord] = TypeAdapter(EvidenceArchiveRecord)


class QualityDiversityArchiveReadModelBuilder:
    """Verify and present immutable Apex archive publications through Workspace only."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace
        self._archive_publications: dict[tuple[str, str], PublicationReadback] = {}
        self._archive_records: dict[tuple[str, str], ArchiveRecord] = {}
        self._external_publications: dict[tuple[str, str], PublicationReadback] = {}
        self._visiting: set[tuple[str, str]] = set()

    def read(self, reference: ArchiveRecordRef) -> ArchiveReadModel:
        if not isinstance(reference, ArchiveRecordRef):
            raise TypeError("archive reader requires a typed ArchiveRecordRef")
        self._archive_publications.clear()
        self._archive_records.clear()
        self._external_publications.clear()
        self._visiting.clear()
        try:
            record = self._visit_archive(reference)
            publication = self._archive_publications[(reference.record_type, reference.record_id)]
            archives = [
                self._archive_publications[key] for key in sorted(self._archive_publications)
            ]
            externals = [
                self._external_publications[key] for key in sorted(self._external_publications)
            ]
            if reference.record_type == EXPLORATION_ARCHIVE_RECORD_TYPE:
                return ExplorationArchiveReadModel(
                    presentation_label="exploration archive — discovery leaders",
                    archive_family="exploration",
                    record=cast(ExplorationArchiveRecord, record),
                    publication=publication,
                    archive_publications=archives,
                    external_publications=externals,
                )
            return EvidenceArchiveReadModel(
                presentation_label="evidence archive — historical formal evidence leaders",
                archive_family="evidence",
                record=cast(EvidenceArchiveRecord, record),
                publication=publication,
                archive_publications=archives,
                external_publications=externals,
                current_active_eligibility="not_evaluated",
                current_active_reason=SPEC032_BLOCKER,
            )
        except ReportingError:
            raise
        except ValidationError as exc:
            raise ContractError("archive_contract_invalid", str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("archive_readback_invalid", str(exc)) from exc
        except Exception as exc:
            raise SourceError(
                "archive_source_failed", f"cannot read archive owner facts: {exc}"
            ) from exc

    def _visit_archive(self, reference: PublishedRef) -> ArchiveRecord:
        key = (reference.record_type, reference.record_id)
        if key in self._archive_records:
            return self._archive_records[key]
        if key in self._visiting:
            raise ContractError("archive_predecessor_cycle", "archive reference cycle detected")
        self._visiting.add(key)
        publication = self._publication(reference)
        record = self._parse_archive(publication)
        if _record_id(record) != reference.record_id:
            raise ContractError(
                "archive_identity_mismatch",
                "archive payload identity differs from its publication",
            )
        expected_lineage = _expected_lineage(record)
        actual_lineage = [item.model_dump(mode="json") for item in publication.lineage]
        if actual_lineage != expected_lineage:
            raise ContractError(
                "archive_lineage_mismatch",
                "archive publication lineage differs from its frozen owner contract",
            )
        self._archive_publications[key] = publication
        self._archive_records[key] = record
        for related in _archive_refs(record):
            related_record = self._visit_archive(related)
            self._verify_archive_scope(record, related, related_record)
        for external in _external_refs(record):
            self._visit_external(external)
        self._visiting.remove(key)
        return record

    def _publication(self, reference: PublishedRef) -> PublicationReadback:
        try:
            raw = self.workspace.client.get_record(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "archive_record_missing",
                f"cannot read {reference.record_type} {reference.record_id}: {exc}",
            ) from exc
        publication = PublicationReadback.model_validate(raw, strict=True)
        if (
            publication.record_id != reference.record_id
            or publication.record_type != reference.record_type
            or publication.payload.get("schema") != reference.record_type
            or publication.artifacts
        ):
            raise ContractError(
                "archive_reference_mismatch",
                "record differs from its exact typed reference or claims artifacts",
            )
        return publication

    @staticmethod
    def _parse_archive(publication: PublicationReadback) -> ArchiveRecord:
        if publication.record_type == EXPLORATION_ARCHIVE_RECORD_TYPE:
            return _EXPLORATION_ADAPTER.validate_python(publication.payload, strict=True)
        if publication.record_type == EVIDENCE_ARCHIVE_RECORD_TYPE:
            return _EVIDENCE_ADAPTER.validate_python(publication.payload, strict=True)
        raise ContractError("archive_family_invalid", "unsupported archive record family")

    def _visit_external(self, reference: PublishedRef) -> None:
        key = (reference.record_type, reference.record_id)
        if key in self._external_publications:
            return
        if reference.record_type == "quant-research.run-record.v1":
            self._verify_runtime(reference)
            return
        publication = self._publication(reference)
        self._external_publications[key] = publication

    def _verify_runtime(self, reference: PublishedRef) -> None:
        try:
            run = self.workspace.client.get_run(reference.record_id)
            result = self.workspace.client.get_result(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "archive_runtime_source_missing",
                f"cannot read Runtime owner fact {reference.record_id}: {exc}",
            ) from exc
        if run.get("run_id") != reference.record_id or result.get("run_id") != reference.record_id:
            raise ContractError(
                "archive_runtime_source_mismatch", "Runtime owner fact identity differs"
            )

    @staticmethod
    def _verify_archive_scope(
        owner: ArchiveRecord, reference: PublishedRef, related: ArchiveRecord
    ) -> None:
        if reference.record_type not in {
            EXPLORATION_ARCHIVE_RECORD_TYPE,
            EVIDENCE_ARCHIVE_RECORD_TYPE,
        }:
            raise ContractError("archive_family_invalid", "archive reference has wrong family")
        if isinstance(owner, (ExplorationArchivePolicy, EvidenceArchivePolicy)):
            return
        if getattr(owner, "policy", None) == reference:
            if not isinstance(related, (ExplorationArchivePolicy, EvidenceArchivePolicy)):
                raise ContractError(
                    "archive_policy_kind_mismatch", "archive policy is not a policy"
                )
            owner_taxonomy = getattr(owner, "taxonomy", None)
            if owner_taxonomy is not None and owner_taxonomy != related.taxonomy:
                raise ContractError(
                    "archive_taxonomy_mismatch", "archive state and policy taxonomy differ"
                )


def _record_id(record: ArchiveRecord) -> str:
    if isinstance(record, (ExplorationArchivePolicy, EvidenceArchivePolicy)):
        return record.policy_id
    if isinstance(
        record,
        (
            ExplorationArchiveEvent,
            ExplorationArchiveLifecycleEvent,
            EvidenceArchiveEvent,
            EvidenceArchiveLifecycleEvent,
        ),
    ):
        return record.event_id
    return record.snapshot_id


def _edge(reference: PublishedRef, relation: str) -> dict[str, str]:
    return {
        "source_kind": reference.record_type,
        "source_id": reference.record_id,
        "relation": relation,
    }


def _expected_lineage(record: ArchiveRecord) -> list[dict[str, str]]:
    if isinstance(record, (ExplorationArchivePolicy, EvidenceArchivePolicy)):
        return [
            _edge(record.campaign, "archive-campaign"),
            _edge(record.taxonomy, "archive-taxonomy"),
        ]
    if isinstance(record, ExplorationArchiveEvent):
        return [
            _edge(record.policy, "archive-policy"),
            _edge(record.considered.descriptor, "archive-descriptor"),
            _edge(record.considered.quality, "archive-quality"),
            *(_edge(item.quality, "archive-displaced-quality") for item in record.displaced),
        ]
    if isinstance(record, EvidenceArchiveEvent):
        link = record.consideration.exploration_lineage
        return [
            _edge(record.policy, "archive-policy"),
            _edge(record.consideration.descriptor, "archive-formal-descriptor"),
            _edge(record.consideration.evidence, "archive-formal-evidence"),
            _edge(record.consideration.qualification, "archive-historical-qualification"),
            *(
                []
                if link is None
                else [
                    _edge(link.snapshot, "optional-exploration-snapshot"),
                    _edge(link.event, "optional-exploration-event"),
                ]
            ),
            *(
                _edge(item.consideration.evidence, "archive-displaced-evidence")
                for item in record.displaced
            ),
        ]
    if isinstance(record, (ExplorationArchiveLifecycleEvent, EvidenceArchiveLifecycleEvent)):
        return [
            _edge(record.policy, "archive-policy"),
            _edge(record.predecessor, "archive-predecessor"),
            _edge(record.owner_source, "archive-lifecycle-owner-source"),
        ]
    if isinstance(record, (ExplorationArchiveView, EvidenceArchiveView)):
        return [
            _edge(record.policy, "archive-policy"),
            _edge(record.predecessor, "archive-predecessor"),
            *(_edge(item, "archive-lifecycle-event") for item in record.events),
        ]
    return [
        _edge(record.policy, "archive-policy"),
        *([] if record.predecessor is None else [_edge(record.predecessor, "archive-predecessor")]),
        *(_edge(item, "archive-event") for item in record.events),
    ]


def _archive_refs(record: ArchiveRecord) -> Iterable[PublishedRef]:
    if isinstance(record, (ExplorationArchivePolicy, EvidenceArchivePolicy)):
        return ()
    values: list[PublishedRef] = [record.policy]
    predecessor = getattr(record, "predecessor", None)
    if predecessor is not None:
        values.append(predecessor)
    values.extend(getattr(record, "events", ()))
    if isinstance(record, EvidenceArchiveEvent):
        link = record.consideration.exploration_lineage
        if link is not None:
            values.extend((link.snapshot, link.event))
    return values


def _entry_external_refs(entries: Iterable[ExplorationArchiveEntry]) -> Iterable[PublishedRef]:
    for entry in entries:
        yield entry.candidate
        yield entry.descriptor
        yield entry.quality


def _external_refs(record: ArchiveRecord) -> Iterable[PublishedRef]:
    if isinstance(record, (ExplorationArchivePolicy, EvidenceArchivePolicy)):
        return (record.campaign, record.taxonomy)
    values: list[PublishedRef] = []
    taxonomy = getattr(record, "taxonomy", None)
    if taxonomy is not None:
        values.append(taxonomy)
    if isinstance(record, ExplorationArchiveEvent):
        values.extend((record.candidate, record.considered.descriptor, record.considered.quality))
        values.extend(_entry_external_refs(record.displaced))
    elif isinstance(record, (ExplorationArchiveSnapshot, ExplorationArchiveView)):
        entries = [*getattr(record, "entries", ()), *record.historical_entries]
        entries.extend(getattr(record, "active_entries", ()))
        values.extend(_entry_external_refs(entries))
    elif isinstance(record, EvidenceArchiveEvent):
        consideration = record.consideration
        values.extend(
            (
                consideration.candidate,
                consideration.descriptor,
                consideration.evidence,
                consideration.qualification,
                consideration.taxonomy,
            )
        )
        for observation in consideration.observations:
            values.extend(observation.sources)
        for item in record.displaced:
            values.append(item.consideration.evidence)
    elif isinstance(record, (EvidenceArchiveSnapshot, EvidenceArchiveView)):
        entries = [*record.historical_entries]
        entries.extend(getattr(record, "all_historical_entries", ()))
        entries.extend(getattr(record, "eligible_historical_entries", ()))
        for item in entries:
            consideration = item.consideration
            values.extend(
                (
                    consideration.candidate,
                    consideration.descriptor,
                    consideration.evidence,
                    consideration.qualification,
                    consideration.taxonomy,
                )
            )
            for observation in consideration.observations:
                values.extend(observation.sources)
    elif isinstance(record, (ExplorationArchiveLifecycleEvent, EvidenceArchiveLifecycleEvent)):
        values.extend((record.previous_taxonomy, record.taxonomy, record.owner_source))
    return values


__all__ = ["QualityDiversityArchiveReadModelBuilder"]
