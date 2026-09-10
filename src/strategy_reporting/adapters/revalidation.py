"""Workspace-only assembly of the SPEC-032 presentation model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.contracts.evidence_v2 import PublicationReadback
from strategy_reporting.contracts.revalidation import (
    RevalidationReadModel,
    RevalidationRecordRef,
)
from strategy_reporting.errors import ContractError, SourceError

_PLAN = "apex-research.revalidation-plan.v1"
_CURRENCY = "apex-research.evidence-currency.v1"
_OUTCOME = "apex-research.revalidation-stage-outcome.v1"
_DECAY = "apex-research.decay-evaluation.v1"
_ARCHIVE = "apex-research.evidence-archive-current.v1"
_EVIDENCE_PUBLICATION = "apex-research.revalidation-evidence-publication.v1"
_QUALIFICATION = "apex-research.qualification-revalidation.v1"


class RevalidationReadModelBuilder:
    """Copy exact owner facts into a deterministic read model; never score or qualify."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, reference: RevalidationRecordRef) -> RevalidationReadModel:
        if not isinstance(reference, RevalidationRecordRef):
            raise TypeError("revalidation reader requires a RevalidationRecordRef")
        publications: dict[str, PublicationReadback] = {}
        closure = self._required(reference.record_id, reference.record_type, publications)
        closure_payload = closure.payload
        self._require_fields(
            closure_payload,
            {
                "schema",
                "closure_id",
                "plan",
                "outcomes",
                "decays",
                "prior_currency",
                "disposition",
                "resulting_currency",
                "supersedes_evidence",
                "replacement_evidence",
                "reason",
            },
            "revalidation closure",
        )
        if closure_payload.get("closure_id") != reference.record_id:
            raise ContractError("revalidation_identity_mismatch", "closure identity drifted")

        missing: list[str] = []
        plan = self._referenced(closure_payload.get("plan"), _PLAN, publications, missing, "plan")
        currency = self._referenced(
            closure_payload.get("prior_currency"),
            _CURRENCY,
            publications,
            missing,
            "currency",
        )
        outcomes = self._reference_list(
            closure_payload.get("outcomes"), _OUTCOME, publications, missing, "outcome"
        )
        decays = self._reference_list(
            closure_payload.get("decays"), _DECAY, publications, missing, "decay"
        )

        plan_payload = plan.payload if plan is not None else None
        currency_payload = currency.payload if currency is not None else None
        stage_plans = self._dict_list(
            plan_payload.get("stages") if plan_payload is not None else [], "revalidation stages"
        )
        outcome_payloads = [item.payload for item in outcomes]
        stages = [
            {"plan": stage, "outcome": outcome_payloads[index] if index < len(outcomes) else None}
            for index, stage in enumerate(stage_plans)
        ]
        if len(outcomes) > len(stage_plans):
            raise ContractError(
                "revalidation_stage_mismatch", "stage outcomes exceed the frozen campaign"
            )

        related = self._related_publications()
        evidence_publication_record = self._matching_publication(
            related, _EVIDENCE_PUBLICATION, "closure", reference.record_id
        )
        qualification_record = self._matching_publication(
            related, _QUALIFICATION, "closure", reference.record_id
        )
        replacement_evidence = closure_payload.get("replacement_evidence")
        if replacement_evidence is None and evidence_publication_record is not None:
            replacement_evidence = evidence_publication_record.payload.get("evidence")
        evidence_ids = {
            value
            for value in (
                self._reference_id(closure_payload.get("supersedes_evidence")),
                self._reference_id(replacement_evidence),
            )
            if value is not None
        }
        archive_candidates = [
            item
            for item in related
            if item.record_type == _ARCHIVE
            and evidence_ids
            & {
                self._reference_id(entry)
                for entry in self._list(item.payload.get("historical_entries"), "archive history")
            }
        ]
        superseded_archive_ids = {
            value
            for item in archive_candidates
            if (value := self._reference_id(item.payload.get("supersedes"))) is not None
        }
        archive_tips = [
            item for item in archive_candidates if item.record_id not in superseded_archive_ids
        ]
        if len(archive_tips) > 1:
            raise ContractError(
                "revalidation_archive_ambiguous",
                "multiple current currency-aware archive views are not ordered",
            )
        archive_record = archive_tips[0] if archive_tips else None
        for item in (archive_record, evidence_publication_record, qualification_record):
            if item is not None:
                publications[item.record_id] = item
        archive = archive_record.payload if archive_record is not None else None
        evidence_publication = (
            evidence_publication_record.payload if evidence_publication_record is not None else None
        )
        qualification = qualification_record.payload if qualification_record is not None else None
        if archive is None:
            missing.append("active/historical archive")
        if evidence_publication is None:
            missing.append("replacement Evidence publication")
        if qualification is None:
            missing.append("qualification revalidation")

        budget = [
            item
            for stage in stage_plans
            for item in self._dict_list(stage.get("budget"), "stage budget")
        ]
        model = RevalidationReadModel(
            root=reference,
            read_status="blocked" if missing else "complete",
            reason=(
                "missing owner facts: " + ", ".join(sorted(set(missing)))
                if missing
                else str(closure_payload["reason"])
            ),
            maturity=(
                str(currency_payload.get("qualification_maturity"))
                if currency_payload is not None
                and isinstance(currency_payload.get("qualification_maturity"), str)
                else None
            ),
            currency=(
                str(currency_payload.get("currency"))
                if currency_payload is not None
                and isinstance(currency_payload.get("currency"), str)
                else None
            ),
            trigger_observations=self._dict_list(
                currency_payload.get("observations") if currency_payload is not None else [],
                "currency observations",
            ),
            campaign=plan_payload,
            budget=budget,
            stages=stages,
            decays=[item.payload for item in decays],
            comparison={
                "disposition": closure_payload["disposition"],
                "resulting_currency": closure_payload["resulting_currency"],
                "reason": closure_payload["reason"],
            },
            supersession={
                "supersedes_evidence": closure_payload["supersedes_evidence"],
                "replacement_evidence": replacement_evidence,
            },
            archive=archive,
            evidence_publication=evidence_publication,
            qualification_revalidation=qualification,
            missing_facts=sorted(set(missing)),
            owner_publications=[publications[key] for key in sorted(publications)],
        )
        return model

    def _required(
        self,
        record_id: str,
        record_type: str,
        publications: dict[str, PublicationReadback],
    ) -> PublicationReadback:
        try:
            raw = self.workspace.client.get_record(record_id)
        except Exception as exc:
            raise SourceError(
                "revalidation_record_missing", f"record unavailable: {record_id}"
            ) from exc
        try:
            publication = PublicationReadback.model_validate(raw, strict=True)
        except ValidationError as exc:
            raise ContractError("revalidation_publication_invalid", str(exc)) from exc
        if publication.record_id != record_id or publication.record_type != record_type:
            raise ContractError("revalidation_schema_unknown", "owner record schema is unexpected")
        if publication.artifacts:
            raise ContractError(
                "revalidation_artifact_unexpected", "owner fact must be inline JSON"
            )
        publications[publication.record_id] = publication
        return publication

    def _referenced(
        self,
        raw: object,
        expected_type: str,
        publications: dict[str, PublicationReadback],
        missing: list[str],
        label: str,
    ) -> PublicationReadback | None:
        reference = self._reference(raw, label)
        if reference[1] != expected_type:
            raise ContractError("revalidation_schema_unknown", f"{label} schema is unexpected")
        try:
            return self._required(reference[0], reference[1], publications)
        except SourceError:
            missing.append(label)
            return None

    def _reference_list(
        self,
        raw: object,
        expected_type: str,
        publications: dict[str, PublicationReadback],
        missing: list[str],
        label: str,
    ) -> list[PublicationReadback]:
        result: list[PublicationReadback] = []
        for index, item in enumerate(self._list(raw, f"{label} references")):
            publication = self._referenced(
                item, expected_type, publications, missing, f"{label}[{index}]"
            )
            if publication is not None:
                result.append(publication)
        return result

    def _related_publications(self) -> list[PublicationReadback]:
        values: list[PublicationReadback] = []
        for record_type in (_ARCHIVE, _EVIDENCE_PUBLICATION, _QUALIFICATION):
            for raw in self.workspace.client.list_records(record_type=record_type, limit=1000):
                try:
                    publication = PublicationReadback.model_validate(raw, strict=True)
                except ValidationError as exc:
                    raise ContractError("revalidation_publication_invalid", str(exc)) from exc
                if publication.record_type != record_type:
                    raise ContractError(
                        "revalidation_schema_unknown", "listed owner schema drifted"
                    )
                values.append(publication)
        return sorted(values, key=lambda item: item.record_id)

    @staticmethod
    def _matching_publication(
        publications: list[PublicationReadback], record_type: str, field: str, record_id: str
    ) -> PublicationReadback | None:
        matches = [
            item
            for item in publications
            if item.record_type == record_type
            and RevalidationReadModelBuilder._reference_id(item.payload.get(field)) == record_id
        ]
        if len(matches) > 1:
            raise ContractError(
                "revalidation_publication_ambiguous", f"multiple {record_type} facts"
            )
        return matches[0] if matches else None

    @staticmethod
    def _require_fields(payload: Mapping[str, Any], fields: set[str], label: str) -> None:
        if set(payload) != fields:
            raise ContractError("revalidation_payload_invalid", f"{label} fields are not exact")

    @staticmethod
    def _reference(raw: object, label: str) -> tuple[str, str]:
        if not isinstance(raw, Mapping) or set(raw) != {"record_id", "record_type"}:
            raise ContractError("revalidation_reference_invalid", f"{label} reference is invalid")
        record_id = raw.get("record_id")
        record_type = raw.get("record_type")
        if not isinstance(record_id, str) or not isinstance(record_type, str):
            raise ContractError("revalidation_reference_invalid", f"{label} reference is invalid")
        return record_id, record_type

    @classmethod
    def _reference_id(cls, raw: object) -> str | None:
        if raw is None:
            return None
        return cls._reference(raw, "record")[0]

    @staticmethod
    def _list(raw: object, label: str) -> list[Any]:
        if not isinstance(raw, list):
            raise ContractError("revalidation_payload_invalid", f"{label} must be an array")
        return raw

    @classmethod
    def _dict_list(cls, raw: object, label: str) -> list[dict[str, Any]]:
        values = cls._list(raw, label)
        if not all(isinstance(item, Mapping) for item in values):
            raise ContractError("revalidation_payload_invalid", f"{label} must contain objects")
        return [dict(item) for item in values]


__all__ = ["RevalidationReadModelBuilder"]
