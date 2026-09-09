from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.campaign_report import (
    CAMPAIGN_EVIDENCE_ORDER,
    CampaignEvidenceClass,
    CampaignEvidenceEntry,
    CampaignEvidenceLane,
    CampaignObjective,
    CampaignQuantitativeValue,
    CampaignReport,
    CampaignReportSource,
    CampaignReportState,
    CampaignSubject,
)
from strategy_reporting.errors import ContractError, SourceError

CAMPAIGN_SOURCE_TYPE = "apex-research.campaign-report-source.v1"
SOURCE_LIMIT = 10_000
_PUBLICATION_FIELDS = {
    "schema",
    "record_id",
    "record_type",
    "created_at",
    "payload",
    "artifacts",
    "lineage",
}


class CampaignReportSourceAdapter:
    """Read one Apex-owned campaign source through the public Workspace Seam."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, campaign_id: str, *, source_id: str | None = None) -> CampaignReportSource:
        try:
            records = self.workspace.client.list_records(
                record_type=CAMPAIGN_SOURCE_TYPE, limit=SOURCE_LIMIT
            )
        except Exception as exc:
            raise SourceError(
                "campaign_source_read_failed", "cannot list campaign report sources"
            ) from exc
        if len(records) == SOURCE_LIMIT:
            raise ContractError(
                "campaign_source_list_truncated",
                "campaign report source list reached the 10,000 record hard cap",
            )
        matches = [
            record
            for record in records
            if isinstance(record.get("payload"), Mapping)
            and record["payload"].get("campaign", {}).get("source", {}).get("record_id")
            == campaign_id
            and (source_id is None or record.get("record_id") == source_id)
        ]
        if not matches:
            detail = f" with source {source_id}" if source_id else ""
            raise SourceError(
                "campaign_source_missing",
                f"no campaign report source for campaign {campaign_id}{detail}; fallback is forbidden",
            )
        if len(matches) != 1:
            raise ContractError(
                "campaign_source_ambiguous",
                "multiple campaign report sources require an explicit source identity",
            )
        publication = matches[0]
        if set(publication) != _PUBLICATION_FIELDS:
            raise ContractError(
                "campaign_source_publication_invalid", "campaign source publication fields differ"
            )
        try:
            source = CampaignReportSource.model_validate(publication.get("payload"), strict=True)
        except (ValidationError, ValueError) as exc:
            raise ContractError(
                "campaign_source_contract_invalid",
                f"campaign source fields or content are invalid: {exc}",
            ) from exc
        if (
            publication.get("schema") != "quant-research.publication.v1"
            or publication.get("record_type") != CAMPAIGN_SOURCE_TYPE
            or publication.get("record_id") != source.source_id
            or publication.get("artifacts") != []
        ):
            raise ContractError(
                "campaign_source_publication_identity_mismatch",
                "campaign source publication identity or artifact set differs",
            )
        expected_lineage = [
            {
                "source_kind": item.record_type,
                "source_id": item.record_id,
                "relation": "supports-campaign-report",
            }
            for item in source.sources
        ]
        if publication.get("lineage") != expected_lineage:
            raise ContractError(
                "campaign_source_publication_lineage_mismatch",
                "campaign source publication lineage differs",
            )
        self._verify_owner_readback(source)
        return source

    def _verify_owner_readback(self, source: CampaignReportSource) -> None:
        for reference in source.sources:
            try:
                if reference.record_type == "quant-research.run-record.v1":
                    owner: Mapping[str, Any] = self.workspace.client.get_run(reference.record_id)
                    observed_id = owner.get("run_id")
                    observed_type = owner.get("schema")
                else:
                    owner = self.workspace.client.get_record(reference.record_id)
                    observed_id = owner.get("record_id")
                    observed_type = owner.get("record_type")
            except Exception as exc:
                raise SourceError(
                    "campaign_source_owner_read_failed",
                    f"cannot read campaign source owner {reference.record_type}",
                ) from exc
            if observed_id != reference.record_id or observed_type != reference.record_type:
                raise ContractError(
                    "campaign_source_owner_identity_mismatch",
                    "campaign source owner identity differs from Apex lineage",
                )


class CampaignReadModelBuilder:
    """Map one verified Apex source to a frozen Reporting-owned read model."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self._source = CampaignReportSourceAdapter(workspace)

    def build(self, campaign_id: str, *, source_id: str | None = None) -> CampaignReport:
        source = self._source.read(campaign_id, source_id=source_id)
        return CampaignReport(
            title=source.campaign.title,
            subject=CampaignSubject(campaign_id=campaign_id, source_id=source.source_id),
            report_state=_report_state(source),
            objective=CampaignObjective(
                question=source.brief.question,
                constraints=source.brief.constraints,
                assumptions=source.brief.assumptions,
                source=source.brief.source.model_dump(mode="json"),
            ),
            sections=source.sections,
            evidence_lanes=_evidence_lanes(source),
            current_evidence=(
                source.current_evidence.model_dump(mode="json")
                if source.current_evidence is not None
                else None
            ),
            current_qualification=(
                source.current_qualification.model_dump(mode="json")
                if source.current_qualification is not None
                else None
            ),
            source_publication={
                "record_id": source.source_id,
                "record_type": CAMPAIGN_SOURCE_TYPE,
                "source_id": source.source_id,
            },
            source_records=[item.model_dump(mode="json") for item in source.sources],
            workspace_run_ids=source.workspace_runs,
        )


def _report_state(source: CampaignReportSource) -> CampaignReportState:
    statuses = [section.availability.status for section in source.sections]
    if "blocked" in statuses:
        return "blocked"
    if all(status == "available" for status in statuses):
        return "complete"
    if all(status == "unavailable" for status in statuses):
        return "unavailable"
    available = {
        section.name for section in source.sections if section.availability.status == "available"
    }
    if (
        available
        and available <= {"hypotheses", "candidates", "iterations"}
        and all(status in {"available", "not_evaluated"} for status in statuses)
    ):
        return "design"
    return "partial"


def _evidence_lanes(source: CampaignReportSource) -> list[CampaignEvidenceLane]:
    grouped: dict[CampaignEvidenceClass, list[CampaignEvidenceEntry]] = {
        name: [] for name in CAMPAIGN_EVIDENCE_ORDER
    }
    source_publication = {
        "record_id": source.source_id,
        "record_type": CAMPAIGN_SOURCE_TYPE,
    }
    for section in source.sections:
        facts_level = _evidence_class(section.facts.get("evidence_level"))
        if facts_level is not None:
            grouped[facts_level].append(
                _evidence_entry(section.name, source_publication, section.facts, facts_level)
            )
        for item in section.items:
            item_level = _evidence_class(item.summary.get("evidence_level"))
            if item_level is not None:
                grouped[item_level].append(
                    _evidence_entry(
                        section.name,
                        item.source.model_dump(mode="json"),
                        item.summary,
                        item_level,
                    )
                )
    return [
        CampaignEvidenceLane(evidence_class=name, entries=grouped[name])
        for name in CAMPAIGN_EVIDENCE_ORDER
    ]


def _evidence_class(value: object) -> CampaignEvidenceClass | None:
    if value in CAMPAIGN_EVIDENCE_ORDER:
        return value
    return None


def _evidence_entry(
    section: Any,
    source: dict[str, str],
    data: dict[str, Any],
    evidence_class: CampaignEvidenceClass,
) -> CampaignEvidenceEntry:
    selector = data.get("selector")
    if (
        evidence_class == "formal"
        and isinstance(selector, str)
        and not selector.startswith("formal.nautilus.")
    ):
        raise ContractError(
            "campaign_formal_selector_invalid",
            "formal campaign evidence must retain a Nautilus selector",
        )
    if evidence_class != "formal" and isinstance(selector, str) and selector.startswith("formal."):
        raise ContractError(
            "campaign_evidence_lane_contamination",
            "non-formal campaign evidence cannot use a formal selector",
        )
    return CampaignEvidenceEntry(
        section=section,
        source=source,
        data=data,
        quantitative_values=_quantitative_values(data, source=source),
    )


def _quantitative_values(
    value: object, *, source: dict[str, str], path: str = "$"
) -> list[CampaignQuantitativeValue]:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return []
    if isinstance(value, int | float):
        return [CampaignQuantitativeValue(path=path, value=value, source=source)]
    if isinstance(value, dict):
        result: list[CampaignQuantitativeValue] = []
        for key in sorted(value):
            result.extend(_quantitative_values(value[key], source=source, path=f"{path}.{key}"))
        return result
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            result.extend(_quantitative_values(item, source=source, path=f"{path}[{index}]"))
        return result
    return []
