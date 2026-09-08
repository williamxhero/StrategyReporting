from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.replication import (
    ReplicationDifference,
    ReplicationGap,
    ReplicationReadModel,
    ReplicationRecordRef,
    ReplicationReportSource,
    verify_embedded_identity,
)
from strategy_reporting.errors import ContractError, ReportingError, SourceError
from strategy_reporting.models import ReplicationStudyReport, ReplicationSubject, ReportOptions


class ReplicationReadModelBuilder:
    """Read an Apex-owned replication source without selecting or recomputing facts."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, source_id: str) -> ReplicationReadModel:
        try:
            source_ref = ReplicationRecordRef(
                record_id=source_id,
                record_type="apex-research.replication-report-source.v1",
            )
            publication = self._read(source_ref)
            source = ReplicationReportSource.model_validate(publication["payload"], strict=True)
            self._verify_source_publication(publication, source)
            evidence = self._read(source.comparison_evidence)
            decision = self._read(source.decision)
            case = self._read(source.case)
            del case
            differences, gaps = self._verify_owner_meaning(source, evidence, decision)
            refs = [source.case, source.comparison_evidence, source.decision]
            if source.formal_execution is not None:
                refs.append(source.formal_execution)
            if source.research_design is not None:
                design = self._read(source.research_design)
                verify_embedded_identity(
                    design["payload"],
                    id_field="design_id",
                    reference=source.research_design,
                )
                gaps = [
                    ReplicationGap.model_validate(item, strict=True)
                    for item in _list(design["payload"].get("gaps"), "design gaps")
                ]
                refs.append(source.research_design)
            for fact in source.formal_facts:
                self._read(fact.runtime_evidence)
                refs.append(fact.runtime_evidence)
            return ReplicationReadModel(
                source=source,
                differences=differences,
                blocking_prerequisites=gaps,
                source_publication={
                    "record_id": source_id,
                    "record_type": source.schema_id,
                },
                source_records=[
                    item.model_dump(mode="json")
                    for item in sorted(
                        {item.record_id: item for item in refs}.values(),
                        key=lambda item: (item.record_type, item.record_id),
                    )
                ],
            )
        except ReportingError:
            raise
        except ValidationError as exc:
            raise ContractError("replication_contract_invalid", str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("replication_readback_invalid", str(exc)) from exc
        except Exception as exc:
            raise SourceError(
                "replication_source_read_failed", f"cannot read replication source: {exc}"
            ) from exc

    def build_model(self, source_id: str, options: ReportOptions) -> ReplicationStudyReport:
        del options
        read = self.read(source_id)
        source = read.source
        return ReplicationStudyReport(
            title=f"Strict replication · {source.outcome}",
            subject=ReplicationSubject(
                source_id=source.report_source_id,
                campaign_id=source.campaign_id,
                case_id=source.case.record_id,
                decision_id=source.decision.record_id,
                outcome=source.outcome,
            ),
            source_metrics=[item.model_dump(mode="json") for item in source.source_metrics],
            legacy_metrics=[item.model_dump(mode="json") for item in source.legacy_metrics],
            research_assumptions=[
                item.model_dump(mode="json", by_alias=True) for item in source.research_assumptions
            ],
            formal_facts=[item.model_dump(mode="json") for item in source.formal_facts],
            differences=[item.model_dump(mode="json") for item in read.differences],
            blocking_prerequisites=[
                item.model_dump(mode="json") for item in read.blocking_prerequisites
            ],
            source_publication=read.source_publication,
            source_records=read.source_records,
        )

    def _read(self, reference: ReplicationRecordRef) -> dict[str, Any]:
        try:
            raw = self.workspace.client.get_record(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "replication_record_missing",
                f"cannot read {reference.record_type} {reference.record_id}",
            ) from exc
        if not isinstance(raw, Mapping):
            raise ContractError("replication_publication_invalid", "publication must be an object")
        publication = dict(raw)
        if (
            publication.get("record_id") != reference.record_id
            or publication.get("record_type") != reference.record_type
            or not isinstance(publication.get("payload"), dict)
            or publication.get("artifacts", [])
        ):
            raise ContractError(
                "replication_publication_mismatch", "replication owner publication drifted"
            )
        if publication["payload"].get("schema") != reference.record_type:
            raise ContractError(
                "replication_payload_schema_mismatch", "replication owner schema drifted"
            )
        return publication

    @staticmethod
    def _verify_source_publication(
        publication: dict[str, Any], source: ReplicationReportSource
    ) -> None:
        roots = [
            source.formal_execution or source.research_design,
            source.comparison_evidence,
            source.decision,
            source.case,
        ]
        expected = [
            {
                "source_kind": item.record_type,
                "source_id": item.record_id,
                "relation": "supports-replication-comparison",
            }
            for item in roots
            if item is not None
        ]
        if publication.get("payload") != source.model_dump(mode="json", by_alias=True):
            raise ContractError("replication_source_payload_mismatch", "source payload drifted")
        if publication.get("lineage", []) != expected or publication.get("artifacts", []):
            raise ContractError("replication_source_lineage_mismatch", "source lineage drifted")

    @staticmethod
    def _verify_owner_meaning(
        source: ReplicationReportSource,
        evidence: dict[str, Any],
        decision: dict[str, Any],
    ) -> tuple[list[ReplicationDifference], list[ReplicationGap]]:
        evidence_payload = evidence["payload"]
        decision_payload = decision["payload"]
        verify_embedded_identity(
            evidence_payload,
            id_field="evidence_id",
            reference=source.comparison_evidence,
        )
        verify_embedded_identity(
            decision_payload, id_field="decision_id", reference=source.decision
        )
        if decision_payload.get("outcome") != source.outcome:
            raise ValueError("replication decision outcome mismatch")
        for key in (
            "source_metrics",
            "legacy_metrics",
            "research_assumptions",
            "formal_facts",
        ):
            if evidence_payload.get(key) != source.model_dump(mode="json").get(key):
                raise ValueError(f"replication evidence {key} mismatch")
        if source.outcome == "not_reproducible":
            if (
                decision_payload.get("formal_run") is not None
                or decision_payload.get("evidence_v2") is not None
            ):
                raise ValueError("not_reproducible decision contains formal side effects")
            return [], []
        if evidence_payload.get("outcome") != source.outcome:
            raise ValueError("replication evidence outcome mismatch")
        differences = [
            ReplicationDifference.model_validate(item, strict=True)
            for item in _list(evidence_payload.get("differences"), "comparison differences")
        ]
        if not differences:
            raise ValueError("executed replication has no classified differences")
        expected_outcome = (
            "failed"
            if any(not item.matched for item in differences)
            else "directional"
            if any(item.mode == "directional" for item in differences)
            else "exact"
        )
        if source.outcome != expected_outcome:
            raise ValueError("replication classified differences contradict outcome")
        return differences, []


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value
