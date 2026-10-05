"""Read the historical dossier through public Workspace records and verified artifacts."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import ValidationError

from strategy_reporting.adapters.workspace import WorkspaceAdapter, as_list
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.dossier_report import (
    CONCLUSION_TYPE,
    DOSSIER_SECTION_ORDER,
    MATRIX_TYPE,
    QUARANTINE_TYPE,
    SOURCE_TYPE,
    T2_TYPE,
    DossierArtifactRef,
    DossierEvidence,
    DossierReport,
    DossierSection,
    DossierSectionName,
    DossierSourceRefs,
    DossierValue,
    DossierValueSource,
)
from strategy_reporting.contracts.evidence_v2 import PublicationReadback, StudyRecordRef
from strategy_reporting.errors import ContractError, ReportingError, SourceError
from strategy_reporting.models import ArtifactRef

FACTS_TYPE = "apex-research.study-runtime-facts.v1"
METRICS_TYPE = "apex-research.cpa-object-performance.v1"
COMPARISON_TYPE = "apex-research.cpa-bootstrap-comparison.v1"
ATTRIBUTION_TYPE = "apex-research.cpa-object-attribution.v2"
LOCK_TYPE = "apex-research.prospective-holdout-lock.v1"
PROOF_TYPE = "apex-research.prospective-holdout-access-proof.v1"
_REGISTRATION_TYPE = "apex-research.study-registration.v1"
_EXCLUDED_TYPE = "apex-research.v1.2-s5-formal-matrix-excluded-attempts.v1"
_UNAVAILABLE_STATES = {
    "not_evaluated",
    "unavailable",
    "blocked",
    "incomparable",
    "insufficient_statistics",
}

# An explicit allowlist prevents a new upstream reference from opening holdout results.
_RECORD_SECTIONS: dict[str, DossierSectionName] = {
    SOURCE_TYPE: "source",
    MATRIX_TYPE: "experiment_matrix",
    T2_TYPE: "experiment_matrix",
    _REGISTRATION_TYPE: "lineage",
    "apex-research.sample-exposure.v1": "lineage",
    "apex-research.cpa-research-profile.v1": "lineage",
    "apex-research.cpa-bootstrap-method.v1": "lineage",
    "apex-research.cpa-regime-definition.v1": "lineage",
    "apex-research.revision-decision.v1": "lineage",
    "apex-research.cpa-revision-search-budget.v1": "lineage",
    FACTS_TYPE: "audits",
    _EXCLUDED_TYPE: "audits",
    METRICS_TYPE: "metrics",
    COMPARISON_TYPE: "comparisons",
    ATTRIBUTION_TYPE: "attributions",
    "apex-research.cpa-object-event-evidence.v1": "attributions",
    QUARANTINE_TYPE: "quarantine",
    LOCK_TYPE: "holdout_lock",
    PROOF_TYPE: "holdout_lock",
    CONCLUSION_TYPE: "limitations",
}


class DossierReportBuilder:
    """Project owner facts without selecting latest records or calculating engine metrics."""

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def read(self, refs: DossierSourceRefs) -> DossierReport:
        if not isinstance(refs, DossierSourceRefs):
            raise TypeError("dossier builder requires typed DossierSourceRefs")
        try:
            roots = {ref.record_type: self._publication(ref) for ref in refs.records()}
            self._verify_bindings(refs, roots)
            selected = self._references(roots)
            publications = {(p.record_type, p.record_id): p for p in roots.values()}
            missing: dict[tuple[str, str], str] = {}
            for key, reference in sorted(selected.items()):
                if key in publications:
                    continue
                try:
                    publications[key] = self._publication(reference)
                except SourceError as exc:
                    missing[key] = exc.message
            self._verify_scopes(roots, publications)
            grouped: dict[DossierSectionName, list[DossierEvidence]] = {
                name: [] for name in DOSSIER_SECTION_ORDER
            }
            for key, reference in sorted(selected.items()):
                publication = publications.get(key)
                if publication is None:
                    evidence = self._missing(reference, missing[key])
                else:
                    evidence = self._project(publication)
                    if reference.record_type in {COMPARISON_TYPE, ATTRIBUTION_TYPE}:
                        gap = self._comparison_gap(publication.payload, publications)
                        if gap:
                            evidence = self._missing(reference, gap, publication)
                grouped[_RECORD_SECTIONS[reference.record_type]].append(evidence)
            sections = [
                DossierSection(
                    name=name,
                    status="evaluated" if grouped[name] else "not_evaluated",
                    reason=None if grouped[name] else "no public owner evidence was supplied",
                    evidence=grouped[name],
                )
                for name in DOSSIER_SECTION_ORDER
            ]
            artifacts = {
                artifact
                for entries in grouped.values()
                for item in entries
                for artifact in item.artifacts
            }
            return DossierReport(
                source_refs=refs,
                sections=sections,
                source_records=[selected[key] for key in sorted(selected)],
                source_artifacts=sorted(artifacts, key=lambda item: (item.sha256, item.name)),
            )
        except ReportingError:
            raise
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            raise ContractError("dossier_contract_invalid", str(exc)) from exc

    def _publication(self, reference: StudyRecordRef) -> PublicationReadback:
        try:
            raw = self.workspace.client.get_record(reference.record_id)
        except Exception as exc:
            raise SourceError(
                "dossier_record_missing",
                f"cannot read {reference.record_type}:{reference.record_id}",
            ) from exc
        publication = PublicationReadback.model_validate(raw, strict=True)
        if (
            publication.record_id != reference.record_id
            or publication.record_type != reference.record_type
            or publication.payload.get("schema") != reference.record_type
        ):
            raise ContractError(
                "dossier_record_mismatch",
                "dossier owner reference differs from its public readback",
            )
        if publication.payload.get("data_role") not in {None, "development", "validation"}:
            raise ContractError(
                "dossier_role_forbidden",
                "dossier may only project development/validation owner results",
            )
        return publication

    @staticmethod
    def _verify_bindings(refs: DossierSourceRefs, roots: dict[str, PublicationReadback]) -> None:
        for reference, identity_field in zip(
            refs.records(),
            ("matrix_id", "source_id", "source_id", "quarantine_id", "conclusion_id"),
            strict=True,
        ):
            payload = roots[reference.record_type].payload
            identity = {key: value for key, value in payload.items() if key != identity_field}
            if (
                payload.get(identity_field) != reference.record_id
                or canonical_sha256(identity) != reference.record_id
            ):
                raise ContractError(
                    "dossier_identity_mismatch",
                    f"dossier {identity_field} canonical identity differs",
                )
        matrix, t2, source = (roots[k].payload for k in (MATRIX_TYPE, T2_TYPE, SOURCE_TYPE))

        def expected(ref: StudyRecordRef) -> dict[str, Any]:
            return ref.model_dump(mode="json")

        if (
            t2.get("matrix") != expected(refs.matrix)
            or matrix.get("quarantine_ref") != expected(refs.quarantine)
            or t2.get("quarantine_ref") != expected(refs.quarantine)
            or source.get("conclusion") not in (None, expected(refs.conclusion))
            or source.get("constraints", {}).get("current_matrix") != refs.matrix.record_id
            or source.get("constraints", {}).get("current_t2_source") != refs.t2.record_id
            or source.get("constraints", {}).get("quarantine") != refs.quarantine.record_id
        ):
            raise ContractError(
                "dossier_scope_mismatch", "matrix/T2/source/quarantine/conclusion bindings differ"
            )
        conclusion = roots[CONCLUSION_TYPE].payload
        required = [
            expected(ref) for ref in (refs.matrix, refs.t2, refs.report_source, refs.quarantine)
        ]
        if any(ref not in conclusion.get("evidence", []) for ref in required) or conclusion.get(
            "scope", {}
        ).get("data_roles") != ["development", "validation"]:
            raise ContractError(
                "dossier_conclusion_scope_mismatch",
                "conclusion evidence or historical roles differ",
            )
        for payload in (matrix, t2, source.get("constraints", {})):
            if (
                payload.get("data_cutoff") != "2026-09-30"
                or payload.get("holdout_guard") != "no_data_on_or_after_2026-10-01"
            ):
                raise ContractError(
                    "dossier_holdout_guard_mismatch",
                    "historical dossier cutoff or holdout guard differs",
                )
        cells = as_list(matrix.get("cells"), "matrix cells")
        t2_cells = as_list(t2.get("cells"), "T2 cells")
        if (
            len(cells) != 12
            or len(t2_cells) != 12
            or len({(c["object_label"], c["data_role"]) for c in cells}) != 12
        ):
            raise ContractError(
                "dossier_matrix_incomplete",
                "dossier requires the complete twelve-cell experiment matrix",
            )
        by_id = {cell["cell_id"]: cell for cell in cells}
        if {cell["cell_id"] for cell in t2_cells} != set(by_id):
            raise ContractError(
                "dossier_matrix_mismatch", "T2 cells differ from the explicit matrix"
            )
        for cell in t2_cells:
            original = by_id[cell["cell_id"]]
            if (
                original["data_role"] not in {"development", "validation"}
                or any(
                    cell.get(k) != original.get(k)
                    for k in ("object_label", "data_role", "package", "registration")
                )
                or cell.get("matrix_status") != original.get("status")
            ):
                raise ContractError(
                    "dossier_cell_mismatch", "T2 cell identity or role differs from its matrix"
                )
        excluded = roots[QUARANTINE_TYPE].payload.get("entries", [])
        runs = {item["run_id"] for item in excluded}
        metrics = {ref["record_id"] for item in excluded for ref in item.get("metrics", [])}
        if any(cell.get("run_id") in runs for cell in cells) or any(
            ref["record_id"] in metrics for ref in t2.get("metrics_sources", [])
        ):
            raise ContractError(
                "dossier_quarantine_violation",
                "quarantined evidence cannot enter current matrix metrics",
            )

    @staticmethod
    def _references(roots: dict[str, PublicationReadback]) -> dict[tuple[str, str], StudyRecordRef]:
        selected: dict[tuple[str, str], StudyRecordRef] = {}

        def add(raw: Any) -> None:
            if raw is None:
                return
            ref = StudyRecordRef.model_validate(raw, strict=True)
            if ref.record_type in _RECORD_SECTIONS:
                selected[(ref.record_type, ref.record_id)] = ref

        for publication in roots.values():
            add({"record_id": publication.record_id, "record_type": publication.record_type})
        matrix, t2, source = (roots[k].payload for k in (MATRIX_TYPE, T2_TYPE, SOURCE_TYPE))
        for name in ("profile", "method", "holdout_lock"):
            add(matrix.get(name))
        for name in ("excluded_attempts", "regime_definition"):
            add(t2.get(name))
        for cell in matrix["cells"]:
            for name in ("registration", "runtime_facts", "exposure"):
                add(cell.get(name))
        for name in ("metrics_sources", "comparison_sources", "attribution_sources"):
            for raw in t2.get(name, []):
                add(raw)
        for name in ("research", "registration"):
            add(source.get(name))
        for raw in source.get("references", []):
            if raw.get("record_type") in {
                PROOF_TYPE,
                "apex-research.revision-decision.v1",
                "apex-research.cpa-revision-search-budget.v1",
            }:
                add(raw)
        return selected

    @staticmethod
    def _verify_scopes(
        roots: dict[str, PublicationReadback],
        publications: dict[tuple[str, str], PublicationReadback],
    ) -> None:
        for cell in roots[MATRIX_TYPE].payload["cells"]:
            raw = cell.get("runtime_facts")
            if raw is None or (FACTS_TYPE, raw["record_id"]) not in publications:
                continue
            facts = publications[(FACTS_TYPE, raw["record_id"])].payload
            if any(
                facts.get(k) != cell.get(k)
                for k in ("run_id", "request_hash", "data_role", "registration", "exposure")
            ):
                raise ContractError(
                    "dossier_runtime_facts_mismatch",
                    "RuntimeFacts differ from their historical matrix cell",
                )
        t2_cells = roots[T2_TYPE].payload["cells"]
        for cell in t2_cells:
            raw = cell.get("metrics")
            if raw is None or (METRICS_TYPE, raw["record_id"]) not in publications:
                continue
            metrics = publications[(METRICS_TYPE, raw["record_id"])].payload
            if any(
                metrics.get(k) != cell.get(k) for k in ("object_label", "data_role", "registration")
            ):
                raise ContractError(
                    "dossier_metrics_mismatch", "published metrics differ from their T2 cell"
                )

    @staticmethod
    def _comparison_gap(
        payload: dict[str, Any], publications: dict[tuple[str, str], PublicationReadback]
    ) -> str | None:
        refs = [
            payload.get(name)
            for name in ("baseline_metrics", "comparator_metrics", "metrics")
            if payload.get(name) is not None
        ]
        identities = []
        for raw in refs:
            ref = StudyRecordRef.model_validate(raw, strict=True)
            owner = publications.get((ref.record_type, ref.record_id))
            if owner is None:
                return "comparison/attribution input has no selected public owner readback"
            registration = owner.payload.get("registration")
            if not isinstance(registration, dict):
                return "comparison/attribution input has no registered data identity"
            record = publications.get((_REGISTRATION_TYPE, str(registration.get("record_id", ""))))
            if record is None or record.payload.get("data_identity") is None:
                return "registered data identity is unavailable"
            identities.append(record.payload["data_identity"])
        if identities and any(identity != identities[0] for identity in identities):
            return "registered data identities are incomparable"
        return None

    def _project(self, publication: PublicationReadback) -> DossierEvidence:
        ref = StudyRecordRef(record_id=publication.record_id, record_type=publication.record_type)
        facts = _project_scalars(publication.payload, ref)
        artifacts: list[DossierArtifactRef] = []
        if publication.record_type == FACTS_TYPE:
            for index, raw in enumerate(publication.payload.get("artifacts", [])):
                descriptor = ArtifactRef.model_validate(raw, strict=True)
                # Only verbatim native statistics and account rows; never orders/positions-derived metrics.
                if not descriptor.name.endswith(
                    ("/native_statistics.json", "/native_account.csv", "runtime_manifest.json")
                ):
                    continue
                prefix = f"/native_artifacts/{index}"
                try:
                    if descriptor.bytes > 4_000_000:
                        raise ContractError(
                            "dossier_artifact_too_large",
                            "native artifact exceeds the bounded preview limit",
                        )
                    verified = self.workspace.verify_ref(raw)
                    citation = DossierArtifactRef(
                        uri=verified.uri,
                        sha256=verified.sha256,
                        name=verified.name,
                        record_schema=verified.record_schema,
                    )
                    if descriptor.name.endswith(".csv"):
                        rows = list(
                            csv.DictReader(
                                io.StringIO(self.workspace.read_verified_bytes(raw).decode("utf-8"))
                            )
                        )
                        content: Any = rows[:1_000]
                        facts.extend(
                            _project_scalars(content, ref, prefix=prefix, artifact=citation)
                        )
                        facts.extend(
                            _project_scalars(
                                {
                                    "total_rows": len(rows),
                                    "omitted_rows": max(0, len(rows) - 1_000),
                                },
                                ref,
                                prefix=prefix + "/preview",
                                artifact=citation,
                                native=False,
                            )
                        )
                    else:
                        content = self.workspace.read_verified_json(raw, maximum_bytes=4_000_000)
                        if descriptor.name.endswith("/native_statistics.json") and (
                            descriptor.record_schema != "quant-runtime.nautilus-reporting-input.v1"
                            or not isinstance(content, dict)
                            or content.get("schema") != descriptor.record_schema
                        ):
                            raise ContractError(
                                "dossier_native_schema_invalid",
                                "native reporting input schema differs",
                            )
                        facts.extend(
                            _project_scalars(content, ref, prefix=prefix, artifact=citation)
                        )
                    artifacts.append(citation)
                except (ReportingError, ValueError) as exc:
                    facts.append(_unavailable(prefix, ref, str(exc)))
        return DossierEvidence(
            source=ref,
            payload_sha256=canonical_sha256(publication.payload),
            lineage=publication.lineage,
            artifacts=sorted(set(artifacts), key=lambda item: (item.sha256, item.name)),
            facts=sorted(facts, key=lambda item: item.path),
        )

    @staticmethod
    def _missing(
        ref: StudyRecordRef, reason: str, publication: PublicationReadback | None = None
    ) -> DossierEvidence:
        return DossierEvidence(
            source=ref,
            payload_sha256=canonical_sha256(publication.payload) if publication else None,
            lineage=publication.lineage if publication else [],
            artifacts=[],
            facts=[_unavailable("/evidence", ref, reason)],
        )


def _unavailable(path: str, ref: StudyRecordRef, reason: str) -> DossierValue:
    return DossierValue(
        path=path,
        value=None,
        status="not_evaluated",
        derivation="not_evaluated",
        derivation_reason="no comparable verified owner value",
        sources=[DossierValueSource(record=ref, selector=path)],
        reason=reason,
    )


def _project_scalars(
    value: Any,
    ref: StudyRecordRef,
    *,
    prefix: str = "",
    artifact: DossierArtifactRef | None = None,
    native: bool = True,
) -> list[DossierValue]:
    result = []
    for pointer, item, reason in _scalars(value):
        path = prefix + pointer
        source = DossierValueSource(record=ref, selector=pointer, artifact=artifact)
        result.append(
            DossierValue(
                path=path,
                value=None if reason else item,
                status="not_evaluated" if reason else "evaluated",
                derivation="not_evaluated"
                if reason
                else "Runtime-native"
                if artifact and native
                else "presentation-derived",
                derivation_reason="copied verbatim from verified Runtime artifact"
                if artifact and native
                else "public owner fact copied without metric recomputation; preview counts only describe displayed rows",
                sources=[source],
                reason=reason,
            )
        )
    return sorted(result, key=lambda item: item.path)


def _scalars(
    value: Any, pointer: str = "", inherited: str | None = None
) -> Iterator[tuple[str, Any, str | None]]:
    if isinstance(value, Mapping):
        state = value.get("status")
        absent = (
            str(value.get("reason") or f"owner status is {state}")
            if isinstance(state, str) and state in _UNAVAILABLE_STATES
            else inherited
        )
        for key in sorted(value):
            path = pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
            yield from _scalars(value[key], path, None if key in {"status", "reason"} else absent)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _scalars(item, f"{pointer}/{index}", inherited)
    else:
        yield (
            pointer or "/",
            value,
            inherited or ("owner value is unavailable" if value is None else None),
        )


__all__ = ["DossierReportBuilder"]
