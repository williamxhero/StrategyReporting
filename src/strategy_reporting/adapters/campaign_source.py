from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.campaign_report import CampaignReportSource
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
