from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import bytes_sha256, canonical_sha256
from strategy_reporting.errors import ContractError, PublicationError, SourceError
from strategy_reporting.models import (
    FormalRunReport,
    LineageEdge,
    ReportDescriptor,
    ReportEnvelope,
    ReportIdentity,
    ReportModel,
    ReportOptions,
    ReportPublication,
)
from strategy_reporting.renderers.interface import RenderedBundle

DESCRIPTOR_TYPE = "strategy-reporting.report-descriptor.v1"


class WorkspaceReportPublisher:
    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def publish(self, bundle: RenderedBundle) -> ReportPublication:
        identity = self._identity(bundle)
        report_id = "report_" + canonical_sha256(identity.model_dump(mode="json"))
        hashes = {item.name: bytes_sha256(item.content) for item in bundle.artifacts}
        descriptor = ReportDescriptor(
            report_id=report_id,
            report_kind=identity.report_kind,
            subject_id=self._subject_id(bundle),
            title=bundle.model.title,
            payload_schema=bundle.model.schema_id,
            renderer_version=bundle.renderer_version,
            identity=identity,
            expected_content_hashes=hashes,
        )
        lineage = self._lineage(bundle)
        existing = self._get_optional(report_id)
        if existing is not None:
            return self._validate_publication(existing, descriptor, lineage)
        record = {
            "record_id": report_id,
            "record_type": DESCRIPTOR_TYPE,
            "payload": descriptor.model_dump(mode="json"),
            "lineage": [item.model_dump(mode="json") for item in lineage],
        }
        specs = tuple(
            {
                "source": artifact.content,
                "media_type": artifact.media_type,
                "record_schema": artifact.record_schema,
                "logical_role": artifact.logical_role,
                "name": artifact.name,
            }
            for artifact in bundle.artifacts
        )
        try:
            publication = self.workspace.client.publish_record(record, artifacts=specs)
        except Exception as exc:
            if getattr(exc, "code", None) != "record_conflict":
                raise PublicationError("workspace_publish_failed", str(exc)) from exc
            winner = self._get_optional(report_id)
            if winner is None:
                raise PublicationError(
                    "publication_race_lost", "conflict winner could not be loaded"
                ) from exc
            publication = winner
        return self._validate_publication(publication, descriptor, lineage)

    def inspect(self, report_id: str) -> ReportPublication:
        try:
            publication = self.workspace.client.get_record(report_id)
        except Exception as exc:
            raise SourceError("report_not_found", f"report not found: {report_id}") from exc
        descriptor = self._descriptor(publication)
        return self._validate_publication(
            publication,
            descriptor,
            [LineageEdge.model_validate(item) for item in publication.get("lineage", [])],
        )

    def verify(self, report_id: str) -> ReportPublication:
        return self.inspect(report_id)

    def verify_semantic_lineage(
        self, publication: Mapping[str, Any], bundle: RenderedBundle
    ) -> None:
        actual = [LineageEdge.model_validate(item) for item in publication.get("lineage", [])]
        expected = self._lineage(bundle)
        if actual != expected:
            raise ContractError(
                "lineage_mismatch", "publication lineage differs from persisted report model"
            )

    def verify_semantic_descriptor(
        self,
        publication: Mapping[str, Any],
        model: ReportModel,
        model_bytes: bytes,
    ) -> None:
        """Bind every descriptor claim to the persisted model, not to itself."""
        actual = self._descriptor(publication)
        try:
            options = ReportOptions.model_validate(actual.identity.options, strict=True)
        except ValueError as exc:
            raise ContractError("descriptor_model_mismatch", str(exc)) from exc
        expected_identity = self._identity_for_model(
            model,
            model_bytes=model_bytes,
            renderer_version=actual.renderer_version,
            options=options,
        )
        expected = (
            expected_identity.report_kind,
            self._subject_id_for_model(model),
            model.title,
            model.schema_id,
            expected_identity,
        )
        observed = (
            actual.report_kind,
            actual.subject_id,
            actual.title,
            actual.payload_schema,
            actual.identity,
        )
        if observed != expected:
            raise ContractError(
                "descriptor_model_mismatch",
                "report descriptor claims differ from the persisted report model",
            )

    def _validate_publication(
        self,
        publication: Mapping[str, Any],
        expected: ReportDescriptor,
        expected_lineage: list[LineageEdge],
    ) -> ReportPublication:
        if (
            publication.get("record_type") != DESCRIPTOR_TYPE
            or publication.get("record_id") != expected.report_id
        ):
            raise ContractError(
                "publication_identity_mismatch", "publication record identity differs"
            )
        actual = self._descriptor(publication)
        if actual != expected:
            raise ContractError("descriptor_conflict", "persisted report descriptor differs")
        if "artifacts" in actual.model_dump() or "lineage" in actual.model_dump():
            raise ContractError(
                "descriptor_duplicate_truth", "descriptor duplicates publication truth"
            )
        actual_lineage = [
            LineageEdge.model_validate(item) for item in publication.get("lineage", [])
        ]
        if actual_lineage != expected_lineage:
            raise ContractError("lineage_mismatch", "publication lineage differs")
        artifacts = publication.get("artifacts")
        if not isinstance(artifacts, list):
            raise ContractError(
                "publication_artifacts_invalid", "publication artifacts must be an array"
            )
        by_name: dict[str, dict[str, Any]] = {}
        for raw in artifacts:
            if not isinstance(raw, Mapping):
                raise ContractError("publication_artifacts_invalid", "artifact must be an object")
            name = str(raw.get("name", ""))
            if name in by_name:
                raise ContractError("artifact_name_ambiguous", f"duplicate report artifact {name}")
            by_name[name] = dict(raw)
        if set(by_name) != set(expected.expected_content_hashes):
            raise ContractError("report_artifact_set_mismatch", "report artifact set differs")
        for name, digest in expected.expected_content_hashes.items():
            ref = by_name[name]
            if ref.get("sha256") != digest:
                raise ContractError("report_artifact_hash_mismatch", f"hash differs for {name}")
            self.workspace.verify_ref(ref)
        envelope = ReportEnvelope.model_validate(
            {
                "report_id": actual.report_id,
                "report_kind": actual.report_kind,
                "subject_id": actual.subject_id,
                "title": actual.title,
                "generated_at": publication.get("created_at"),
                "payload_schema": actual.payload_schema,
                "renderer_version": actual.renderer_version,
                "identity": actual.identity,
                "artifacts": list(by_name.values()),
                "lineage": actual_lineage,
            }
        )
        return ReportPublication(envelope=envelope, publication=dict(publication))

    @staticmethod
    def _identity(bundle: RenderedBundle) -> ReportIdentity:
        return WorkspaceReportPublisher._identity_for_model(
            bundle.model,
            model_bytes=bundle.model_bytes,
            renderer_version=bundle.renderer_version,
            options=bundle.options,
        )

    @staticmethod
    def _identity_for_model(
        model: ReportModel,
        *,
        model_bytes: bytes,
        renderer_version: str,
        options: ReportOptions,
    ) -> ReportIdentity:
        if isinstance(model, FormalRunReport):
            kind: Literal["formal-run", "research-study"] = "formal-run"
            subject: dict[str, Any] = model.subject.model_dump(mode="json")
            sources = [item.sha256 for item in model.source_artifacts]
        else:
            kind = "research-study"
            subject = model.subject.model_dump(mode="json")
            sources = [
                model.source_publication["record_id"],
                *model.source_record_ids,
                *model.workspace_run_ids,
            ]
        return ReportIdentity(
            report_kind=kind,
            subject=subject,
            source_identities=sources,
            model_sha256=bytes_sha256(model_bytes),
            renderer_version=renderer_version,
            options=options.normalized(),
        )

    @staticmethod
    def _subject_id(bundle: RenderedBundle) -> str:
        return WorkspaceReportPublisher._subject_id_for_model(bundle.model)

    @staticmethod
    def _subject_id_for_model(model: ReportModel) -> str:
        if isinstance(model, FormalRunReport):
            return f"workspace-run:{model.subject.workspace_run_id}#attempt:{model.subject.attempt_id}#formal:{model.subject.formal_id}"
        return f"apex-study:{model.subject.study_id}#decision:{model.subject.decision_id}"

    @staticmethod
    def _lineage(bundle: RenderedBundle) -> list[LineageEdge]:
        model = bundle.model
        raw: list[tuple[str, str, str]] = []
        if isinstance(model, FormalRunReport):
            raw.extend(
                (
                    ("workspace-run", model.subject.workspace_run_id, "reports"),
                    ("workspace-attempt", model.subject.attempt_id, "reports"),
                    ("strategy-package", str(model.strategy.get("package_hash")), "uses"),
                    ("market-snapshot", str(model.market.get("snapshot_id")), "uses"),
                )
            )
            raw.extend(
                ("workspace-artifact", item.sha256, "derived-from")
                for item in model.source_artifacts
            )
        else:
            raw.append((APEX_SOURCE_KIND, model.source_publication["record_id"], "derived-from"))
            raw.append(
                ("apex-study-source-model", model.source_publication["source_id"], "derived-from")
            )
            raw.extend(
                (item["record_type"], item["record_id"], "derived-from")
                for item in model.source_records
            )
            raw.extend(("workspace-run", item, "reports") for item in model.workspace_run_ids)
            for link in model.related_formal_reports:
                raw.extend(
                    ("strategy-reporting.report-descriptor.v1", item, "derived-from")
                    for item in link["report_ids"]
                )
        unique = sorted(set(raw))
        return [
            LineageEdge(source_kind=kind, source_id=source_id, relation=relation)
            for kind, source_id, relation in unique
        ]

    def _get_optional(self, report_id: str) -> dict[str, Any] | None:
        try:
            return self.workspace.client.get_record(report_id)
        except Exception as exc:
            if getattr(exc, "code", None) == "record_not_found":
                return None
            raise PublicationError("workspace_read_failed", str(exc)) from exc

    @staticmethod
    def _descriptor(publication: Mapping[str, Any]) -> ReportDescriptor:
        try:
            descriptor = ReportDescriptor.model_validate(publication.get("payload"), strict=True)
        except ValueError as exc:
            raise ContractError("descriptor_invalid", str(exc)) from exc
        calculated = "report_" + canonical_sha256(descriptor.identity.model_dump(mode="json"))
        if calculated != descriptor.report_id:
            raise ContractError("report_identity_invalid", "report_id does not match identity")
        return descriptor


APEX_SOURCE_KIND = "apex-research.study-report-source.v1"
