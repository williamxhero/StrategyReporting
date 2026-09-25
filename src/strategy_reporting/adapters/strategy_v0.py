from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from strategy_reporting.adapters.workspace import WorkspaceAdapter, as_object
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import (
    ConclusionDecision,
    ConclusionEvidenceLevel,
    ReportOptions,
    StrategyReportV0,
)

LEGACY_SOURCE_TYPE = "apex-research.strategy-report-source.v1"
V2_SOURCE_TYPE = "apex-research.strategy-report-source.v2"
PUBLICATION_SCHEMA = "quant-research.publication.v1"
CONCLUSION_TYPE = "apex-research.research-conclusion.v1"
TEMPLATE_ID = "StrategyReport-v0"
TEMPLATE_HASH = canonical_sha256({"template_id": TEMPLATE_ID, "version": 0})


class StrategyReportV0Adapter:
    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def build_model(self, subject_id: str, options: ReportOptions) -> StrategyReportV0:
        selected, source_type = self._source_publication(subject_id, options)
        payload = as_object(selected.get("payload"), "strategy report source")
        if payload.get("schema") != source_type:
            raise ContractError("strategy_report_source_schema", "source schema differs")
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or (
            selected.get("record_id") != source_id or selected.get("record_type") != source_type
        ):
            raise ContractError(
                "strategy_report_source_identity", "source publication identity differs"
            )
        references = self._source_references(payload)
        readbacks = self._read_references(references)
        conclusion, evidence_level, conclusion_limitations = self._conclusion_values(
            payload.get("conclusion"), readbacks
        )
        sections = [
            as_object(item, "report source section") for item in payload.get("sections", [])
        ]
        limitations = [
            str(item.get("reason"))
            for item in sections
            if item.get("status") == "not_evaluated" and item.get("reason")
        ]
        limitations.extend(conclusion_limitations)
        return StrategyReportV0(
            title=f"{subject_id} · StrategyReport-v0",
            subject_id=subject_id,
            source_id=source_id,
            template_hash=TEMPLATE_HASH,
            applicability=as_object(payload.get("constraints"), "report applicability"),
            evidence_level=evidence_level,
            decision=conclusion,
            limitations=list(dict.fromkeys(limitations)),
            sections=sections,
            source_publication={
                "record_id": source_id,
                "record_type": source_type,
            },
            source_records=(
                [
                    {"record_id": record_id, "record_type": record_type}
                    for record_type, record_id in references
                ]
                if source_type == V2_SOURCE_TYPE
                else None
            ),
            source_record_ids=sorted({record_id for _, record_id in references} | {source_id}),
        )

    def _source_publication(
        self, subject_id: str, options: ReportOptions
    ) -> tuple[dict[str, Any], str]:
        legacy = self._matching_sources(LEGACY_SOURCE_TYPE, subject_id, options.source_id)
        if legacy:
            return self._select(legacy), LEGACY_SOURCE_TYPE
        if options.source_id is not None:
            return self._read_v2_source(options.source_id, subject_id), V2_SOURCE_TYPE
        if self._matching_sources(V2_SOURCE_TYPE, subject_id, None):
            raise ContractError(
                "strategy_report_source_id_required",
                f"{V2_SOURCE_TYPE} requires --source-id",
            )
        raise SourceError(
            "strategy_report_source_missing",
            f"no {LEGACY_SOURCE_TYPE} or {V2_SOURCE_TYPE} publication for {subject_id}",
        )

    def _matching_sources(
        self, source_type: str, subject_id: str, source_id: str | None
    ) -> list[dict[str, Any]]:
        try:
            records = self.workspace.client.list_records(record_type=source_type, limit=10_000)
        except Exception as exc:
            raise SourceError(
                "strategy_report_source_read_failed", "cannot list strategy report sources"
            ) from exc
        return [
            item
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("payload"), dict)
            and self._matches(item["payload"], subject_id)
            and (source_id is None or item.get("record_id") == source_id)
        ]

    def _read_v2_source(self, source_id: str, subject_id: str) -> dict[str, Any]:
        try:
            raw = self.workspace.client.get_record(source_id)
        except Exception as exc:
            raise SourceError(
                "strategy_report_source_read_failed", "cannot read strategy report source"
            ) from exc
        if not isinstance(raw, Mapping):
            raise SourceError("strategy_report_source_missing", "strategy report source is missing")
        selected = dict(raw)
        payload = selected.get("payload")
        if (
            selected.get("schema") != PUBLICATION_SCHEMA
            or selected.get("record_id") != source_id
            or selected.get("record_type") != V2_SOURCE_TYPE
            or not isinstance(payload, Mapping)
            or payload.get("schema") != V2_SOURCE_TYPE
            or payload.get("source_id") != source_id
        ):
            raise ContractError(
                "strategy_report_source_identity", "source publication identity differs"
            )
        if not self._matches(dict(payload), subject_id):
            raise SourceError(
                "strategy_report_source_missing",
                f"no {V2_SOURCE_TYPE} publication for {subject_id}",
            )
        return selected

    @staticmethod
    def _matches(payload: dict[str, Any], subject_id: str) -> bool:
        research = payload.get("research")
        return payload.get("source_id") == subject_id or (
            isinstance(research, dict) and research.get("record_id") == subject_id
        )

    @staticmethod
    def _select(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if len(candidates) != 1:
            raise ContractError(
                "strategy_report_source_ambiguous",
                "multiple strategy report sources require --source-id",
            )
        return candidates[0]

    def _source_references(self, payload: dict[str, Any]) -> list[tuple[str, str]]:
        values: list[dict[str, Any]] = []
        for key in (
            "research",
            "registration",
            "assessments",
            "exposures",
            "runtime_facts",
            "conclusion",
            "conclusion_history",
            "revisions",
            "framework_prerequisites",
            "restudies",
        ):
            values.extend(self._references(payload.get(key)))
        references: dict[tuple[str, str], None] = {}
        for value in values:
            record_type = value.get("record_type")
            record_id = value.get("record_id")
            if not isinstance(record_type, str) or not record_type:
                raise ContractError(
                    "strategy_report_reference_invalid", "source reference lacks record_type"
                )
            if not isinstance(record_id, str) or not record_id:
                raise ContractError(
                    "strategy_report_reference_invalid", "source reference lacks record_id"
                )
            references[(record_type, record_id)] = None
        return sorted(references)

    def _read_references(
        self, references: list[tuple[str, str]]
    ) -> dict[tuple[str, str], Mapping[str, Any]]:
        readbacks: dict[tuple[str, str], Mapping[str, Any]] = {}
        for record_type, record_id in references:
            try:
                raw = self.workspace.client.get_record(record_id)
            except Exception as exc:
                raise SourceError(
                    "strategy_report_reference_read_failed",
                    f"cannot read source reference {record_type}:{record_id}",
                ) from exc
            if not isinstance(raw, Mapping):
                raise SourceError(
                    "strategy_report_reference_missing",
                    f"source reference is missing: {record_type}:{record_id}",
                )
            if (
                raw.get("schema") != PUBLICATION_SCHEMA
                or raw.get("record_id") != record_id
                or raw.get("record_type") != record_type
                or not isinstance(raw.get("payload"), Mapping)
                or raw["payload"].get("schema") != record_type
            ):
                raise ContractError(
                    "strategy_report_reference_identity",
                    f"source reference readback differs: {record_type}:{record_id}",
                )
            readbacks[(record_type, record_id)] = raw
        return readbacks

    @staticmethod
    def _conclusion_values(
        value: Any, readbacks: Mapping[tuple[str, str], Mapping[str, Any]]
    ) -> tuple[ConclusionDecision, ConclusionEvidenceLevel, list[str]]:
        if value is None:
            return "not_evaluated", "not_evaluated", []
        if not isinstance(value, Mapping):
            raise ContractError(
                "strategy_report_conclusion_invalid", "conclusion reference invalid"
            )
        record_id = value.get("record_id")
        record_type = value.get("record_type")
        if not isinstance(record_id, str) or not isinstance(record_type, str):
            raise ContractError(
                "strategy_report_conclusion_invalid", "conclusion reference identity invalid"
            )
        if (record_type, record_id) not in readbacks or record_type != CONCLUSION_TYPE:
            raise ContractError(
                "strategy_report_conclusion_invalid", "conclusion readback identity differs"
            )
        payload = as_object(readbacks[(record_type, record_id)].get("payload"), "conclusion")
        if payload.get("schema") != CONCLUSION_TYPE or payload.get("conclusion_id") != record_id:
            raise ContractError(
                "strategy_report_conclusion_invalid", "conclusion payload identity differs"
            )
        decision = payload.get("decision")
        evidence_level = payload.get("evidence_level")
        if decision not in {"supports", "does_not_support", "uncertain", "stopped_or_blocked"}:
            raise ContractError("strategy_report_conclusion_invalid", "conclusion decision invalid")
        if evidence_level not in {"candidate_evidence", "protocol_conforming"}:
            raise ContractError(
                "strategy_report_conclusion_invalid", "conclusion evidence level invalid"
            )
        limitations = payload.get("limitations", [])
        if not isinstance(limitations, list) or any(
            not isinstance(item, str) for item in limitations
        ):
            raise ContractError(
                "strategy_report_conclusion_invalid", "conclusion limitations invalid"
            )
        return (
            cast(ConclusionDecision, decision),
            cast(ConclusionEvidenceLevel, evidence_level),
            limitations,
        )

    @staticmethod
    def _references(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []
