"""Public-Workspace-only reader for the Evidence v2 study source."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.evidence_v2 import (
    EvidenceRecordRef,
    EvidenceV2ReadModel,
    EvidenceV2SourceRef,
    EvidenceV2StudySource,
    ExternalRecordReadback,
    PublicationReadback,
    RuntimeDataIdentity,
    RuntimeDataSemantic,
    RuntimeExecutionCosts,
    RuntimeFormalEvidence,
    StrategyPackageRef,
    StudyRecordRef,
    evidence_record_descriptor,
)
from strategy_reporting.errors import ContractError, ReportingError, SourceError


class EvidenceV2ReadModelBuilder:
    """Build one immutable Reporting read model without selecting or interpreting evidence."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, reference: EvidenceV2SourceRef) -> EvidenceV2ReadModel:
        if not isinstance(reference, EvidenceV2SourceRef):
            raise TypeError("Evidence v2 reader requires a typed EvidenceV2SourceRef")
        try:
            source_publication = self._read_publication(reference)
            source = EvidenceV2StudySource.model_validate(
                source_publication.payload,
                strict=True,
            )
            if source.source_id != reference.record_id:
                raise ContractError(
                    "evidence_v2_source_identity_mismatch",
                    "Evidence v2 source record_id differs from its canonical payload",
                )
            self._verify_source_publication(source_publication, source)
            evidence_publication = self._read_publication(source.evidence_ref)
            self._verify_evidence_publication(evidence_publication, source)
            external_records = self._read_external_records(source)
            self._verify_embedded_readbacks(source, external_records)
            self._verify_scope(source, external_records)
            return EvidenceV2ReadModel(
                source=source,
                source_publication=source_publication,
                evidence_publication=evidence_publication,
                external_records=external_records,
                qualification_inference="forbidden",
                production_approval_inference="forbidden",
            )
        except ReportingError:
            raise
        except ValidationError as exc:
            raise ContractError("evidence_v2_contract_invalid", str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("evidence_v2_readback_invalid", str(exc)) from exc
        except Exception as exc:
            raise SourceError(
                "evidence_v2_source_read_failed",
                f"cannot read canonical Evidence v2 source: {exc}",
            ) from exc

    def _read_publication(self, reference: StudyRecordRef) -> PublicationReadback:
        try:
            raw = self.workspace.client.get_record(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "evidence_v2_record_missing",
                f"cannot read {reference.record_type} {reference.record_id}: {exc}",
            ) from exc
        publication = PublicationReadback.model_validate(raw, strict=True)
        if (
            publication.record_id != reference.record_id
            or publication.record_type != reference.record_type
        ):
            raise ContractError(
                "evidence_v2_record_reference_mismatch",
                f"canonical record differs from reference {reference.record_id}",
            )
        return publication

    @staticmethod
    def _verify_source_publication(
        publication: PublicationReadback,
        source: EvidenceV2StudySource,
    ) -> None:
        expected_lineage = [
            {
                "source_kind": source.evidence_ref.record_type,
                "source_id": source.evidence_ref.record_id,
                "relation": "evidence-v2",
            },
            *(
                {
                    "source_kind": item.record_type,
                    "source_id": item.record_id,
                    "relation": "evidence-source",
                }
                for item in source.sources
            ),
        ]
        if (
            publication.payload != source.model_dump(mode="json", by_alias=True)
            or [item.model_dump(mode="json") for item in publication.lineage] != expected_lineage
            or publication.artifacts
        ):
            raise ContractError(
                "evidence_v2_source_publication_mismatch",
                "Evidence v2 source publication lineage, payload, or artifact set differs",
            )

    @staticmethod
    def _verify_evidence_publication(
        publication: PublicationReadback,
        source: EvidenceV2StudySource,
    ) -> None:
        evidence = source.evidence
        expected_lineage = [
            {
                "source_kind": item.record.record_type,
                "source_id": item.record.record_id,
                "relation": "evidence-source",
            }
            for item in evidence.sources
        ]
        expected_lineage.append(
            {
                "source_kind": "quant-research.strategy-package-ref.v1",
                "source_id": evidence.scope.strategy_package.package_hash,
                "relation": "evidence-strategy-package",
            }
        )
        if evidence.supersedes:
            expected_lineage.append(
                {
                    "source_kind": evidence.supersedes.record_type,
                    "source_id": evidence.supersedes.record_id,
                    "relation": "supersedes-evidence",
                }
            )
        if (
            publication.payload != evidence.model_dump(mode="json", by_alias=True)
            or [item.model_dump(mode="json") for item in publication.lineage] != expected_lineage
            or publication.artifacts
        ):
            raise ContractError(
                "evidence_v2_publication_mismatch",
                "Evidence v2 canonical publication readback differs",
            )

    def _read_external_records(
        self,
        source: EvidenceV2StudySource,
    ) -> list[ExternalRecordReadback]:
        records: list[ExternalRecordReadback] = []
        for owner_source in source.evidence.sources:
            reference = owner_source.record
            descriptor = evidence_record_descriptor(reference.record_type)
            compact = StudyRecordRef(
                record_id=reference.record_id,
                record_type=reference.record_type,
            )
            if descriptor.reference_shape == "runtime":
                run, result = self._read_runtime(reference, source)
                records.append(
                    ExternalRecordReadback(
                        reference=compact,
                        publication=None,
                        run=run,
                        result=result,
                    )
                )
                continue
            publication = self._read_publication(compact)
            self._verify_owner_publication(publication, reference)
            self._verify_claimed_artifacts(publication)
            records.append(
                ExternalRecordReadback(
                    reference=compact,
                    publication=publication,
                    run=None,
                    result=None,
                )
            )
        return records

    def _verify_owner_publication(
        self,
        publication: PublicationReadback,
        reference: EvidenceRecordRef,
    ) -> None:
        payload = publication.payload
        descriptor = evidence_record_descriptor(reference.record_type)
        if payload.get("schema") != reference.record_type:
            raise ContractError(
                "evidence_v2_owner_schema_mismatch",
                f"owner payload schema differs for {reference.record_id}",
            )
        identity_field = descriptor.identity_field
        if identity_field:
            if payload.get(identity_field) != reference.record_id:
                raise ContractError(
                    "evidence_v2_owner_identity_mismatch",
                    f"owner payload identity differs for {reference.record_id}",
                )
            identity = {key: value for key, value in payload.items() if key != identity_field}
            if canonical_sha256(identity) != reference.record_id:
                raise ContractError(
                    "evidence_v2_owner_identity_mismatch",
                    f"owner payload hash differs for {reference.record_id}",
                )
        if descriptor.reference_shape == "candidate":
            envelope = _mapping(payload.get("envelope"), "Candidate envelope")
            if (
                payload.get("semantic_id") != reference.semantic_id
                or envelope.get("family_id") != reference.family_id
                or envelope.get("revision") != reference.revision
            ):
                raise ContractError(
                    "evidence_v2_candidate_reference_mismatch",
                    "Candidate revision metadata differs from its canonical reference",
                )
        for artifact in publication.artifacts:
            self.workspace.verify_ref(artifact.model_dump(mode="json", by_alias=True))

    def _verify_claimed_artifacts(self, publication: PublicationReadback) -> None:
        payload = publication.payload
        claim_shape = evidence_record_descriptor(publication.record_type).artifact_claim
        claims: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        if claim_shape == "auxiliary":
            claims.append(
                (
                    _mapping(payload.get("artifact_owner"), "auxiliary artifact owner"),
                    [_mapping(payload.get("artifact"), "auxiliary artifact")],
                )
            )
        elif claim_shape == "raw_p_value":
            claims.append(
                (
                    _mapping(payload.get("source"), "raw p-value owner"),
                    _mapping_list(payload.get("input_artifacts"), "raw p-value artifacts"),
                )
            )
        elif claim_shape == "return_series":
            claims.append(
                (
                    _mapping(payload.get("owner"), "return-series owner"),
                    [_mapping(payload.get("artifact"), "return-series artifact")],
                )
            )
        for owner, artifacts in claims:
            owner_reference = StudyRecordRef.model_validate(owner, strict=True)
            owner_publication = self._read_publication(owner_reference)
            memberships = [
                item.model_dump(mode="json", by_alias=True) for item in owner_publication.artifacts
            ]
            for artifact in artifacts:
                if artifact not in memberships:
                    raise ContractError(
                        "evidence_v2_artifact_membership_mismatch",
                        "verified artifact does not belong to its declared owner record",
                    )
                self.workspace.verify_ref(artifact)

    def _read_runtime(
        self,
        reference: EvidenceRecordRef,
        source: EvidenceV2StudySource,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            raw_run = self.workspace.client.get_run(reference.record_id)
            raw_result = self.workspace.client.get_result(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "evidence_v2_runtime_read_failed",
                f"cannot read Runtime run {reference.record_id}: {exc}",
            ) from exc
        run = _mapping(raw_run, "Runtime run")
        result_envelope = _mapping(raw_result, "Runtime result envelope")
        _exact_keys(
            run,
            {
                "schema",
                "run_id",
                "request_hash",
                "request",
                "package",
                "status",
                "current_attempt_id",
                "created_at",
                "updated_at",
                "result",
                "error",
                "attempts",
            },
            "Runtime run",
        )
        _exact_keys(result_envelope, {"run_id", "status", "result"}, "Runtime result")
        request = _mapping(run.get("request"), "Runtime request")
        result = _mapping(run.get("result"), "Runtime result payload")
        attempts = run.get("attempts")
        if not isinstance(attempts, list):
            raise ContractError("evidence_v2_runtime_lineage_mismatch", "Runtime attempts differ")
        selected = [
            _mapping(item, "Runtime attempt")
            for item in attempts
            if isinstance(item, Mapping) and item.get("attempt_id") == reference.attempt_id
        ]
        if len(selected) != 1:
            raise ContractError(
                "evidence_v2_runtime_lineage_mismatch",
                "Runtime attempt reference is missing or ambiguous",
            )
        attempt = selected[0]
        package = _mapping(run.get("package"), "Runtime package")
        package_ref = StrategyPackageRef.model_validate(package.get("package_ref"), strict=True)
        request_package = StrategyPackageRef.model_validate(
            request.get("strategy_package"), strict=True
        )
        if (
            run.get("schema") != "quant-research.run-record.v1"
            or run.get("run_id") != reference.record_id
            or run.get("request_hash") != reference.request_hash
            or canonical_sha256(request) != reference.request_hash
            or run.get("current_attempt_id") != reference.attempt_id
            or attempt.get("run_id") != reference.record_id
            or attempt.get("attempt_id") != reference.attempt_id
            or attempt.get("result") != result
            or canonical_sha256(result) != reference.result_hash
            or result_envelope
            != {
                "run_id": reference.record_id,
                "status": run.get("status"),
                "result": result,
            }
            or package_ref != source.evidence.scope.strategy_package
            or request_package != source.evidence.scope.strategy_package
        ):
            raise ContractError(
                "evidence_v2_runtime_lineage_mismatch",
                "Runtime request/run/attempt/result lineage differs",
            )
        formal = next(
            (
                item
                for item in source.evidence.runtime_formal
                if item.run.record_id == reference.record_id
                and item.run.attempt_id == reference.attempt_id
            ),
            None,
        )
        if formal:
            self._verify_runtime_formal(formal, request, result, run, attempt)
        return run, result_envelope

    def _verify_runtime_formal(
        self,
        formal: RuntimeFormalEvidence,
        request: dict[str, Any],
        result: dict[str, Any],
        run: dict[str, Any],
        attempt: dict[str, Any],
    ) -> None:
        execution = _mapping(request.get("execution"), "Runtime execution")
        requested_backends = _mapping_list(execution.get("formal"), "Runtime formal requests")
        backend_identities = []
        for index, backend in enumerate(requested_backends):
            _exact_keys(backend, {"id", "adapter", "config"}, "Runtime formal backend")
            backend_identities.append(
                {
                    "backend_id": backend["id"],
                    "adapter": backend["adapter"],
                    "request_selector": f"execution.formal.{index}",
                    "request_hash": canonical_sha256(backend),
                }
            )
        runtime_identity = _mapping(attempt.get("runtime_identity"), "Runtime identity")
        expected_execution = {
            "run_status": run.get("status"),
            "result_outcome": result.get("outcome"),
            "attempt_number": attempt.get("attempt_number"),
            "worker_id": attempt.get("worker_id"),
            "runtime_identity": runtime_identity,
            "runtime_identity_hash": canonical_sha256(runtime_identity),
            "topology": execution.get("topology"),
            "formal_backends": backend_identities,
        }
        if formal.execution.model_dump(mode="json") != expected_execution:
            raise ContractError(
                "evidence_v2_runtime_execution_mismatch",
                "Runtime execution identity differs from the exact run attempt",
            )
        formal_results = _mapping(result.get("formal"), "Runtime formal results")
        metrics: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for backend_id in sorted(formal_results):
            backend = _mapping(formal_results[backend_id], "Runtime formal backend result")
            for name, value in sorted(_mapping(backend.get("metrics"), "Runtime metrics").items()):
                metrics.append(
                    {
                        "backend_id": backend_id,
                        "selector": f"formal.{backend_id}.metrics.{name}",
                        "value": value,
                    }
                )
            raw_artifacts = backend.get("artifacts", [])
            if not isinstance(raw_artifacts, list):
                raise ContractError(
                    "evidence_v2_runtime_artifacts_invalid",
                    "Runtime formal artifacts must be an array",
                )
            for index, artifact in enumerate(raw_artifacts):
                mapped = _mapping(artifact, "Runtime artifact")
                self.workspace.verify_ref(mapped)
                artifacts.append(
                    {
                        "backend_id": backend_id,
                        "selector": f"formal.{backend_id}.artifacts.{index}",
                        "artifact": mapped,
                    }
                )
        raw_run_artifacts = result.get("artifacts", [])
        if not isinstance(raw_run_artifacts, list):
            raise ContractError(
                "evidence_v2_runtime_artifacts_invalid",
                "Runtime result artifacts must be an array",
            )
        for index, artifact in enumerate(raw_run_artifacts):
            mapped = _mapping(artifact, "Runtime result artifact")
            self.workspace.verify_ref(mapped)
            artifacts.append(
                {
                    "backend_id": "run",
                    "selector": f"artifacts.{index}",
                    "artifact": mapped,
                }
            )
        artifacts.sort(key=lambda item: (item["selector"], item["artifact"]["sha256"]))
        if [item.model_dump(mode="json") for item in formal.metrics] != metrics:
            raise ContractError(
                "evidence_v2_runtime_metrics_mismatch",
                "Runtime metric selectors differ from the canonical result",
            )
        if [item.model_dump(mode="json", by_alias=True) for item in formal.artifacts] != artifacts:
            raise ContractError(
                "evidence_v2_artifact_membership_mismatch",
                "Runtime artifact membership differs from the exact result",
            )
        expected_data = _runtime_data_identity(request)
        expected_costs = _runtime_execution_costs(request)
        if formal.data_identity != expected_data or formal.execution_costs != expected_costs:
            raise ContractError(
                "evidence_v2_runtime_semantics_mismatch",
                "Runtime data or execution-cost semantics differ from the exact request",
            )

    @staticmethod
    def _verify_embedded_readbacks(
        source: EvidenceV2StudySource,
        records: list[ExternalRecordReadback],
    ) -> None:
        publications = {
            (item.reference.record_type, item.reference.record_id): item.publication
            for item in records
            if item.publication is not None
        }

        def publication(reference: EvidenceRecordRef) -> PublicationReadback:
            value = publications.get((reference.record_type, reference.record_id))
            if value is None:
                raise ContractError(
                    "evidence_v2_embedded_source_missing",
                    f"embedded owner record is missing: {reference.record_id}",
                )
            return value

        validation = source.evidence.validation_coverage
        if validation:
            validation_owner = publication(validation.evidence)
            payload = validation_owner.payload
            expected_cells = [
                {
                    "cell": _compact(item.cell),
                    "state": _compact(item.state) if item.state else None,
                    "status": item.source_status,
                    "reason": item.reason,
                }
                for item in validation.cells
            ]
            if (
                payload.get("protocol") != _compact(validation.protocol)
                or payload.get("matrix") != _compact(validation.matrix)
                or payload.get("denominator") != validation.denominator
                or payload.get("cells") != expected_cells
                or payload.get("status_counts") != validation.status_counts
                or payload.get("covered_cells") != validation.covered_cells
                or payload.get("complete") != validation.complete
            ):
                raise ContractError(
                    "evidence_v2_validation_readback_mismatch",
                    "validation coverage differs from its canonical aggregate record",
                )

        statistical = source.evidence.statistical_control
        if statistical:
            if publication(statistical.assessment_ref).payload != statistical.assessment:
                raise ContractError(
                    "evidence_v2_statistical_readback_mismatch",
                    "statistical assessment differs from canonical owner readback",
                )
            for raw_reference in statistical.raw_evidence:
                raw = publication(raw_reference).payload
                owner_ref = StudyRecordRef.model_validate(raw.get("source"), strict=True)
                raw_owner = publications.get((owner_ref.record_type, owner_ref.record_id))
                if raw_owner is None or (
                    raw.get("source_payload_sha256") != canonical_sha256(raw_owner.payload)
                    or raw.get("source_lineage_sha256")
                    != canonical_sha256(
                        [item.model_dump(mode="json") for item in raw_owner.lineage]
                    )
                ):
                    raise ContractError(
                        "evidence_v2_raw_owner_readback_mismatch",
                        "raw p-value owner payload or lineage differs",
                    )
            for series_reference in statistical.return_series:
                series = publication(series_reference).payload
                owner_ref = StudyRecordRef.model_validate(series.get("owner"), strict=True)
                return_owner = publications.get((owner_ref.record_type, owner_ref.record_id))
                if return_owner is None or (
                    series.get("owner_payload_sha256") != canonical_sha256(return_owner.payload)
                    or series.get("owner_lineage_sha256")
                    != canonical_sha256(
                        [item.model_dump(mode="json") for item in return_owner.lineage]
                    )
                ):
                    raise ContractError(
                        "evidence_v2_return_owner_readback_mismatch",
                        "Deflated Sharpe return owner payload or lineage differs",
                    )

    @staticmethod
    def _verify_scope(
        source: EvidenceV2StudySource,
        records: list[ExternalRecordReadback],
    ) -> None:
        publications = {
            (item.reference.record_type, item.reference.record_id): item.publication
            for item in records
            if item.publication is not None
        }
        evidence = source.evidence

        def payload(reference: EvidenceRecordRef) -> dict[str, Any]:
            publication = publications.get((reference.record_type, reference.record_id))
            if publication is None:
                raise ContractError(
                    "evidence_v2_scope_record_missing",
                    f"scope record is missing: {reference.record_id}",
                )
            return publication.payload

        campaign = payload(evidence.scope.campaign)
        protocol = payload(evidence.scope.protocol)
        candidate = payload(evidence.scope.candidate)
        compact_campaign = _compact(evidence.scope.campaign)
        compact_candidate = _compact(evidence.scope.candidate)
        if campaign.get("campaign_id") != evidence.scope.campaign.record_id:
            raise ContractError("evidence_v2_campaign_scope_mismatch", "campaign scope differs")
        if (
            protocol.get("campaign") != compact_campaign
            or protocol.get("candidate") != compact_candidate
            or protocol.get("strategy_package")
            != evidence.scope.strategy_package.model_dump(mode="json", by_alias=True)
        ):
            raise ContractError("evidence_v2_protocol_scope_mismatch", "protocol scope differs")
        if candidate.get("revision_id") != evidence.scope.candidate.record_id:
            raise ContractError("evidence_v2_candidate_scope_mismatch", "Candidate scope differs")
        if evidence.scope.hypothesis and evidence.scope.iteration:
            hypothesis = payload(evidence.scope.hypothesis)
            iteration = payload(evidence.scope.iteration)
            if (
                hypothesis.get("campaign_id") != evidence.scope.campaign.record_id
                or iteration.get("campaign_id") != evidence.scope.campaign.record_id
                or iteration.get("hypothesis_id") != evidence.scope.hypothesis.record_id
                or not _reference_matches(iteration.get("candidate"), evidence.scope.candidate)
                or iteration.get("strategy_package")
                != evidence.scope.strategy_package.model_dump(mode="json", by_alias=True)
            ):
                raise ContractError(
                    "evidence_v2_iteration_scope_mismatch",
                    "campaign iteration scope differs",
                )
        for item in records:
            if item.publication is None:
                continue
            record_payload = item.publication.payload
            descriptor = evidence_record_descriptor(item.reference.record_type)
            if (
                "campaign_id" in record_payload
                and record_payload["campaign_id"] != evidence.scope.campaign.record_id
            ):
                raise ContractError(
                    "evidence_v2_campaign_scope_mismatch",
                    "owner record campaign scope differs",
                )
            candidate_value = record_payload.get("candidate")
            if (
                isinstance(candidate_value, Mapping)
                and candidate_value.get("record_type", "").endswith("-candidate.v1")
                and not _reference_matches(candidate_value, evidence.scope.candidate)
            ):
                raise ContractError(
                    "evidence_v2_candidate_scope_mismatch",
                    "owner record Candidate scope differs",
                )
            for package_field in ("package", "strategy_package"):
                package_value = record_payload.get(package_field)
                if (
                    isinstance(package_value, Mapping)
                    and package_value.get("schema") == "quant-research.strategy-package-ref.v1"
                    and dict(package_value)
                    != evidence.scope.strategy_package.model_dump(mode="json", by_alias=True)
                ):
                    raise ContractError(
                        "evidence_v2_package_scope_mismatch",
                        "owner record strategy-package scope differs",
                    )
            if descriptor.scope_binding == "campaign_candidate_protocol" and (
                record_payload.get("campaign") != compact_campaign
                or record_payload.get("candidate") != compact_candidate
                or record_payload.get("protocol") != _compact(evidence.scope.protocol)
            ):
                raise ContractError(
                    "evidence_v2_auxiliary_scope_mismatch",
                    "auxiliary or optional evidence scope differs",
                )
            if (
                descriptor.scope_binding == "campaign"
                and record_payload.get("campaign_id") != evidence.scope.campaign.record_id
            ):
                raise ContractError(
                    "evidence_v2_failure_scope_mismatch",
                    "failure record campaign scope differs",
                )
        for formal in evidence.runtime_formal:
            trial = payload(formal.trial)
            run_record = next(
                (
                    item.run
                    for item in records
                    if evidence_record_descriptor(item.reference.record_type).reference_shape
                    == "runtime"
                    and item.reference.record_id == formal.run.record_id
                ),
                None,
            )
            if run_record is None:
                raise ContractError(
                    "evidence_v2_runtime_scope_mismatch",
                    "formal Runtime run readback is missing",
                )
            if (
                trial.get("study_id") != evidence.scope.campaign.record_id
                or trial.get("protocol_hash") != evidence.scope.protocol.record_id
                or trial.get("request_hash") != formal.run.request_hash
                or trial.get("workspace_run_id") != formal.run.record_id
                or trial.get("strategy_package_hash")
                != evidence.scope.strategy_package.package_hash
                or trial.get("topology") != formal.execution.topology
                or trial.get("run_status") != formal.execution.run_status
            ):
                raise ContractError(
                    "evidence_v2_runtime_scope_mismatch",
                    "formal trial and Runtime scope differ",
                )
            if evidence.scope.iteration:
                iteration = payload(evidence.scope.iteration)
                if (
                    iteration.get("trial") != _compact(formal.trial)
                    or iteration.get("workspace_run_id") != formal.run.record_id
                    or iteration.get("workspace_request_id") != formal.run.request_hash
                ):
                    raise ContractError(
                        "evidence_v2_runtime_scope_mismatch",
                        "campaign iteration and Runtime scope differ",
                    )


def _compact(reference: EvidenceRecordRef) -> dict[str, str]:
    return {"record_id": reference.record_id, "record_type": reference.record_type}


def _reference_matches(value: object, reference: EvidenceRecordRef) -> bool:
    if not isinstance(value, Mapping):
        return False
    mapped = dict(value)
    return mapped in (
        _compact(reference),
        reference.model_dump(mode="json", by_alias=True),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractError("evidence_v2_contract_invalid", f"{label} must be an object")
    return dict(value)


def _mapping_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError("evidence_v2_contract_invalid", f"{label} must be an array")
    return [_mapping(item, label) for item in value]


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContractError(
            "evidence_v2_contract_invalid",
            f"{label} fields differ from the public contract",
        )


def _runtime_data_identity(request: dict[str, Any]) -> RuntimeDataIdentity | None:
    snapshot_value = request.get("market_snapshot")
    if not isinstance(snapshot_value, Mapping) or snapshot_value.get("schema") != (
        "quant-research.market-snapshot-ref.v2"
    ):
        return None
    snapshot = _mapping(snapshot_value, "Runtime market snapshot")
    source = _mapping(snapshot.get("source"), "Runtime market source")
    query = _mapping(snapshot.get("query"), "Runtime market query")
    semantics = _mapping(snapshot.get("data_semantics"), "Runtime data semantics")
    verification = _mapping(snapshot.get("verification"), "Runtime data verification")
    semantic_records = {
        key: RuntimeDataSemantic.model_validate(value, strict=True)
        for key, value in semantics.items()
    }
    return RuntimeDataIdentity(
        snapshot_id=snapshot["snapshot_id"],
        snapshot_hash=canonical_sha256(snapshot),
        mode=snapshot["mode"],
        trust_policy=snapshot["trust_policy"],
        source_adapter=source["adapter"],
        source_adapter_version=source["adapter_version"],
        endpoint_contract=source["endpoint_contract"],
        base_url=source["base_url"],
        data_revision=source["data_revision"],
        source_identity_hash=canonical_sha256(source),
        instruments=list(query["instruments"]),
        start=query["start"],
        end=query["end"],
        frequency=query["frequency"],
        adjustment=query["adjustment"],
        query_hash=canonical_sha256(query),
        calendar=snapshot["calendar"],
        contract_mapping=snapshot["contract_mapping"],
        as_of=snapshot["as_of"],
        required_semantics=list(snapshot["required_semantics"]),
        field_availability=semantic_records["field_availability"],
        point_in_time=semantic_records["point_in_time"],
        time=semantic_records["time"],
        provider_lineage=semantic_records["provider_lineage"],
        data_semantics_hash=canonical_sha256(semantics),
        canonical_input_hash=verification["canonical_input_hash"],
        data_version=verification["data_version"],
        dataset_version=verification["dataset_version"],
        catalog_hash=verification["catalog_hash"],
        calendar_hash=verification["calendar_hash"],
        coverage_hash=verification["coverage_hash"],
        verification_hash=canonical_sha256(verification),
        resolved_at=snapshot["resolved_at"],
    )


def _runtime_execution_costs(request: dict[str, Any]) -> RuntimeExecutionCosts | None:
    parameters = request.get("parameters")
    if not isinstance(parameters, Mapping):
        return None
    mapping = {
        "fee_micros": "validation_fee_micros",
        "slippage_micros": "validation_slippage_micros",
        "margin_micros": "validation_margin_micros",
        "liquidity_micros": "validation_liquidity_micros",
    }
    if not all(name in parameters for name in mapping.values()):
        return None
    return RuntimeExecutionCosts.model_validate(
        {field: parameters[name] for field, name in mapping.items()},
        strict=True,
    )


__all__ = ["EvidenceV2ReadModelBuilder"]
