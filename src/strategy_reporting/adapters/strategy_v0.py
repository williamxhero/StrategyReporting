from __future__ import annotations

from typing import Any

from strategy_reporting.adapters.workspace import WorkspaceAdapter, as_object
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import ReportOptions, StrategyReportV0

SOURCE_TYPE = "apex-research.study-report-source.v2"
TEMPLATE_ID = "StrategyReport-v0"
TEMPLATE_HASH = canonical_sha256({"template_id": TEMPLATE_ID, "version": 0})


class StrategyReportV0Adapter:
    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def build_model(self, subject_id: str, options: ReportOptions) -> StrategyReportV0:
        records = self.workspace.client.list_records(record_type=SOURCE_TYPE, limit=10_000)
        candidates = [
            item
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("payload"), dict)
            and self._matches(item["payload"], subject_id)
        ]
        if not candidates:
            raise SourceError(
                "strategy_report_source_missing",
                f"no {SOURCE_TYPE} publication for {subject_id}",
            )
        selected = self._select(candidates)
        payload = as_object(selected.get("payload"), "strategy report source")
        if payload.get("schema") != SOURCE_TYPE:
            raise ContractError("strategy_report_source_schema", "source schema differs")
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or selected.get("record_id") != source_id:
            raise ContractError(
                "strategy_report_source_identity", "source publication identity differs"
            )
        source_records = [
            self._record_id(value)
            for key in (
                "registration",
                "assessments",
                "exposures",
                "conclusion",
                "conclusion_history",
                "revisions",
                "framework_prerequisites",
                "restudies",
            )
            for value in self._references(payload.get(key))
        ]
        source_records.append(source_id)
        sections = [
            as_object(item, "report source section") for item in payload.get("sections", [])
        ]
        conclusion = "not_evaluated"
        evidence_level = "not_evaluated"
        conclusion_ref = payload.get("conclusion")
        if isinstance(conclusion_ref, dict):
            conclusion = "published conclusion available"
            evidence_level = str(payload.get("versions", {}).get("protocol", "not_evaluated"))
        return StrategyReportV0(
            title=f"{subject_id} · StrategyReport-v0",
            subject_id=subject_id,
            source_id=source_id,
            template_hash=TEMPLATE_HASH,
            applicability=as_object(payload.get("constraints"), "report applicability"),
            evidence_level=evidence_level,
            decision=conclusion,
            limitations=[
                str(item.get("reason"))
                for item in sections
                if item.get("status") == "not_evaluated" and item.get("reason")
            ],
            sections=sections,
            source_publication={
                "record_id": source_id,
                "record_type": SOURCE_TYPE,
            },
            source_record_ids=sorted(set(source_records)),
        )

    @staticmethod
    def _matches(payload: dict[str, Any], subject_id: str) -> bool:
        research = payload.get("research")
        return payload.get("source_id") == subject_id or (
            isinstance(research, dict) and research.get("record_id") == subject_id
        )

    @staticmethod
    def _select(candidates: list[dict[str, Any]]) -> dict[str, Any]:
        return sorted(candidates, key=lambda item: str(item.get("record_id")))[-1]

    @staticmethod
    def _references(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _record_id(value: dict[str, Any]) -> str:
        record_id = value.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise ContractError(
                "strategy_report_reference_invalid", "source reference lacks record_id"
            )
        return record_id
