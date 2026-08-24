from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strategy_reporting.adapters import (
    ApexResearchPublicationAdapter,
    WorkspaceAdapter,
    WorkspaceClientPort,
    WorkspaceFormalRunAdapter,
)
from strategy_reporting.adapters.workspace import production_client
from strategy_reporting.canonical import bytes_sha256
from strategy_reporting.errors import ContractError
from strategy_reporting.models import (
    FormalRunReport,
    ReportKind,
    ReportModel,
    ReportOptions,
    ReportPublication,
    ResearchStudyReport,
)
from strategy_reporting.publishing import WorkspaceReportPublisher
from strategy_reporting.renderers import RendererRegistry


class ReportingApplication:
    def __init__(self, client: WorkspaceClientPort) -> None:
        self.workspace = WorkspaceAdapter(client)
        self.publisher = WorkspaceReportPublisher(self.workspace)
        self.renderers = RendererRegistry()

    def render_report(
        self, subject_kind: ReportKind, subject_id: str, options: ReportOptions
    ) -> ReportPublication:
        model: ReportModel
        if subject_kind == "formal-run":
            model = WorkspaceFormalRunAdapter(self.workspace).build_model(subject_id, options)
        elif subject_kind == "research-study":
            model = ApexResearchPublicationAdapter(self.workspace).build_model(subject_id, options)
        else:
            raise ContractError("report_kind_invalid", f"unsupported report kind: {subject_kind}")
        bundle = self.renderers.resolve(model).render(model, options)
        return self.publisher.publish(bundle)

    def inspect(self, report_id: str) -> ReportPublication:
        return self.publisher.inspect(report_id)

    def verify(self, report_id: str) -> ReportPublication:
        publication = self.publisher.verify(report_id)
        self.rebuild(report_id)
        return publication

    def rebuild(self, report_id: str) -> dict[str, Any]:
        publication = self.publisher.inspect(report_id)
        envelope = publication.envelope
        model_refs = [item for item in envelope.artifacts if item.logical_role == "report-model"]
        if len(model_refs) != 1:
            raise ContractError(
                "report_model_ambiguous", "report must contain one report-model artifact"
            )
        content = self.workspace.read_verified_bytes(model_refs[0].model_dump(mode="json"))
        if bytes_sha256(content) != envelope.identity.model_sha256:
            raise ContractError("report_model_hash_mismatch", "model hash differs from identity")
        options = ReportOptions.model_validate(envelope.identity.options, strict=True)
        model = self._parse_model(content)
        self.publisher.verify_semantic_descriptor(publication.publication, model, content)
        bundle = self.renderers.resolve(model).render(model, options)
        if bundle.renderer_version != envelope.renderer_version:
            raise ContractError("renderer_version_mismatch", "installed renderer version differs")
        self.publisher.verify_semantic_lineage(publication.publication, bundle)
        rebuilt = {item.name: bytes_sha256(item.content) for item in bundle.artifacts}
        expected = publication.publication["payload"]["expected_content_hashes"]
        if rebuilt != expected:
            raise ContractError("rebuild_hash_mismatch", "rebuilt artifact hashes differ")
        return {
            "ok": True,
            "report_id": report_id,
            "model_sha256": envelope.identity.model_sha256,
            "rebuilt_content_hashes": rebuilt,
            "published": False,
        }

    @staticmethod
    def _parse_model(content: bytes) -> ReportModel:
        try:
            raw = json.loads(content)
            if not isinstance(raw, dict):
                raise ValueError("report model root must be an object")
            schema = raw.get("schema")
            if schema == "strategy-reporting.formal-run-report.v1":
                return FormalRunReport.model_validate_json(content, strict=True)
            if schema == "strategy-reporting.research-study-report.v1":
                return ResearchStudyReport.model_validate_json(content, strict=True)
            raise ValueError(f"unsupported report model schema: {schema}")
        except (json.JSONDecodeError, ValueError) as exc:
            raise ContractError("report_model_invalid", str(exc)) from exc


def render_report(
    subject_kind: ReportKind,
    subject_id: str,
    options: ReportOptions,
) -> ReportPublication:
    """Build, render and immutably publish one report through Strategy Workspace."""
    return ReportingApplication(production_client(options.workspace_root)).render_report(
        subject_kind, subject_id, options
    )


def application_for_workspace(workspace_root: Path | None) -> ReportingApplication:
    return ReportingApplication(production_client(workspace_root))
