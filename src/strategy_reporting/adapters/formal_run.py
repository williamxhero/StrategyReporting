from __future__ import annotations

import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import ijson

from strategy_reporting.adapters.workspace import WorkspaceAdapter, as_list, as_object
from strategy_reporting.canonical import canonical_json, canonical_sha256
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import (
    ArtifactRef,
    FormalPerformance,
    FormalRunReport,
    FormalSubject,
    PortfolioReturnPoint,
    ReportOptions,
    TablePreview,
)

REQUIRED_FORMAL_FILES = (
    "native_statistics.json",
    "normalized_output.json",
    "evidence_index.json",
)
TABLE_FILES = {
    "orders": "native_orders.csv",
    "fills": "native_fills.csv",
    "positions": "native_positions.csv",
    "account_curve": "native_account.csv",
}
NORMALIZED_SECTIONS = (
    "orders",
    "fills",
    "rejects",
    "positions",
    "account_curve",
    "fees",
    "decisions",
)
NORMALIZED_ROOT_FIELDS = {
    "schema",
    "framework",
    "framework_version",
    "data_version",
    "dataset_version",
    "canonical_input_hash",
    "strategy_spec_hash",
    "decision_hash",
    *NORMALIZED_SECTIONS,
    "native_statistics",
    "metrics",
    "normalized_output_hash",
}
MAX_NATIVE_STATISTICS_BYTES = 4_000_000
MAX_EVIDENCE_INDEX_BYTES = 1_000_000
MAX_NORMALIZED_METRICS_BYTES = 1_000_000
MAX_NORMALIZED_ROW_BYTES = 1_000_000


class WorkspaceFormalRunAdapter:
    kind: Literal["formal-run"] = "formal-run"

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def build_model(self, subject_id: str, options: ReportOptions) -> FormalRunReport:
        try:
            run = self.workspace.client.get_run(subject_id)
            result_response = self.workspace.client.get_result(subject_id)
        except Exception as exc:
            raise SourceError(
                "run_not_found", f"cannot read Workspace run {subject_id}: {exc}"
            ) from exc
        if run.get("run_id") != subject_id or result_response.get("run_id") != subject_id:
            raise ContractError(
                "run_identity_mismatch", "Workspace returned a different run identity"
            )
        status = str(run.get("status", ""))
        if status not in {"completed", "rejected"}:
            raise SourceError("run_not_terminal", f"run status is not reportable: {status}")
        result = as_object(result_response.get("result"), "result")
        if result.get("outcome") not in {"completed", "rejected"}:
            raise ContractError("result_outcome_invalid", "terminal run lacks a canonical result")
        formal = as_object(result.get("formal"), "result.formal")
        formal_id = self._select_formal_id(formal, options.formal_id)
        leg = as_object(formal[formal_id], f"formal.{formal_id}")
        if leg.get("adapter") != "nautilus":
            raise SourceError(
                "unsupported_formal_adapter", "only Nautilus formal legs are supported"
            )

        refs = self._formal_refs(result, leg, formal_id)
        selected = {name: self._exact_ref(refs, formal_id, name) for name in REQUIRED_FORMAL_FILES}
        if (
            selected["native_statistics.json"].get("record_schema")
            != "quant-runtime.nautilus-reporting-input.v1"
        ):
            raise ContractError(
                "reporting_input_schema_mismatch",
                "native_statistics.json ArtifactRef does not declare the frozen reporting input schema",
            )
        index = as_object(
            self.workspace.read_verified_json(
                selected["evidence_index.json"], maximum_bytes=MAX_EVIDENCE_INDEX_BYTES
            ),
            "evidence index",
        )
        self._verify_index(index, formal_id, refs)
        consumed = [ArtifactRef.model_validate(ref) for ref in refs]

        native = as_object(
            self.workspace.read_verified_json(
                selected["native_statistics.json"], maximum_bytes=MAX_NATIVE_STATISTICS_BYTES
            ),
            "native statistics",
        )
        expected_native_keys = {
            "schema",
            "stats_pnls",
            "stats_returns",
            "summary",
            "total_events",
            "total_orders",
            "total_positions",
            "stats_general",
            "portfolio_returns",
            "run_info",
            "account_info",
            "extraction",
            "availability",
            "unavailable",
        }
        if (
            set(native) != expected_native_keys
            or native.get("schema") != "quant-runtime.nautilus-reporting-input.v1"
        ):
            raise ContractError(
                "reporting_input_schema_mismatch", "native reporting input v1 fields differ"
            )
        execution_performance, execution_rows, normalized_facts = self._stream_normalized(
            selected["normalized_output.json"], refs, formal_id, native, options
        )
        extraction = as_object(native.get("extraction"), "extraction")
        engine_version = str(extraction.get("engine_version") or "")
        if engine_version != "1.231.0":
            raise ContractError(
                "engine_version_mismatch",
                f"expected Nautilus 1.231.0, got {engine_version or 'missing'}",
            )
        stats_general = as_object(native.get("stats_general"), "stats_general")
        returns = self._portfolio_returns(native.get("portfolio_returns"))
        run_info = self._available_object(native.get("run_info"), "run_info")
        account_info = self._available_object(native.get("account_info"), "account_info")
        request = as_object(run.get("request"), "run.request")
        runtime_identity = self._runtime_identity(run)
        attempt_id = str(run.get("current_attempt_id") or "")
        if not attempt_id:
            raise ContractError("attempt_identity_missing", "run has no current attempt identity")
        summary = as_object(result.get("summary"), "result.summary")
        if summary.get("attempt_id") != attempt_id:
            raise ContractError(
                "attempt_identity_mismatch", "result attempt differs from run attempt"
            )

        package_ref = as_object(request.get("strategy_package"), "strategy_package")
        parameters = as_object(request.get("parameters", {}), "parameters")
        snapshot = as_object(request.get("market_snapshot"), "market_snapshot")
        self._verify_identity_mirrors(
            leg,
            package_ref,
            runtime_identity,
            snapshot,
            normalized_facts,
        )
        title = str(
            run.get("package", {}).get("manifest", {}).get("name")
            or package_ref.get("strategy_id")
            or formal_id
        )
        return FormalRunReport(
            title=f"{title} · 正式回测报告",
            subject=FormalSubject(
                workspace_run_id=subject_id,
                attempt_id=attempt_id,
                formal_id=formal_id,
                request_hash=str(run.get("request_hash", "")),
                status=status,
                outcome=str(result["outcome"]),
                topology=str(
                    summary.get("topology")
                    or request.get("execution", {}).get("topology")
                    or "unknown"
                ),
            ),
            strategy={
                "strategy_package": package_ref,
                "strategy_id": package_ref.get("strategy_id"),
                "revision": package_ref.get("revision"),
                "package_hash": package_ref.get("package_hash"),
                "parameters": parameters,
                "parameters_hash": runtime_identity.get("parameters_hash"),
            },
            market={
                "snapshot": snapshot,
                "snapshot_id": snapshot.get("snapshot_id"),
                "verification_status": "verified",
            },
            engine={
                "adapter": "nautilus",
                "adapter_version": self._formal_identity(runtime_identity, formal_id).get(
                    "adapter_version"
                ),
                "engine_name": "NautilusTrader",
                "engine_version": engine_version,
                "runtime_identity_schema": runtime_identity.get("schema"),
                "execution_config_hash": self._formal_identity(runtime_identity, formal_id).get(
                    "config_hash"
                ),
            },
            performance=FormalPerformance(
                stats_pnls=as_object(native.get("stats_pnls"), "stats_pnls"),
                stats_returns=as_object(native.get("stats_returns"), "stats_returns"),
                stats_general=stats_general,
                portfolio_returns=returns,
                sources={
                    "stats_pnls": "native_statistics.json#stats_pnls",
                    "stats_returns": "native_statistics.json#stats_returns",
                    "stats_general": "native_statistics.json#stats_general",
                    "portfolio_returns": "native_statistics.json#portfolio_returns",
                },
                availability={
                    key: {
                        str(k): str(v) for k, v in as_object(value, f"availability.{key}").items()
                    }
                    for key, value in as_object(native.get("availability"), "availability").items()
                },
                unavailable=[
                    {str(k): str(v) for k, v in as_object(item, "unavailable item").items()}
                    for item in as_list(native.get("unavailable"), "unavailable")
                ],
            ),
            run_info=run_info,
            account_info=account_info,
            execution=execution_rows,
            quality={
                "artifact_verification": "verified",
                "evidence_index_verification": "verified",
                "source_file_count": len(refs),
            },
            execution_performance=execution_performance,
            source_artifacts=sorted(consumed, key=lambda item: (item.name, item.sha256)),
        )

    @staticmethod
    def _select_formal_id(formal: dict[str, Any], requested: str | None) -> str:
        if requested is not None:
            if requested not in formal:
                raise SourceError("formal_id_not_found", f"formal leg not found: {requested}")
            return requested
        if len(formal) != 1:
            raise SourceError(
                "formal_id_required", "run has multiple formal legs; specify formal_id"
            )
        return next(iter(formal))

    @staticmethod
    def _formal_refs(
        result: dict[str, Any], leg: dict[str, Any], formal_id: str
    ) -> list[dict[str, Any]]:
        raw = [*as_list(result.get("artifacts", []), "result.artifacts")]
        raw.extend(as_list(leg.get("artifacts", []), f"formal.{formal_id}.artifacts"))
        refs: list[dict[str, Any]] = []
        prefix = f"formal/{formal_id}/"
        for item in raw:
            ref = ArtifactRef.model_validate(item)
            if ref.name.startswith(prefix):
                refs.append(ref.model_dump(mode="json"))
        if not refs:
            raise SourceError(
                "formal_artifacts_missing", f"no artifacts for formal leg {formal_id}"
            )
        names = [str(item["name"]) for item in refs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise SourceError(
                "artifact_name_ambiguous",
                f"duplicate formal artifact names: {', '.join(duplicates)}",
            )
        return refs

    @staticmethod
    def _exact_ref(refs: list[dict[str, Any]], formal_id: str, leaf_name: str) -> dict[str, Any]:
        exact = f"formal/{formal_id}/{leaf_name}"
        matches = [ref for ref in refs if ref.get("name") == exact]
        if len(matches) != 1:
            raise SourceError(
                "artifact_name_ambiguous",
                f"expected exactly one {exact}, found {len(matches)}",
            )
        return matches[0]

    def _verify_index(
        self, index: dict[str, Any], formal_id: str, refs: list[dict[str, Any]]
    ) -> None:
        if set(index) != {"schema", "formal_id", "files"}:
            raise ContractError(
                "evidence_index_schema_mismatch", "evidence index root fields differ"
            )
        if index.get("schema") != "quant-runtime.native-evidence-index.v1":
            raise ContractError("evidence_index_schema_mismatch", "evidence index schema differs")
        if index.get("formal_id") != formal_id:
            raise ContractError(
                "evidence_index_identity_mismatch", "evidence index formal_id differs"
            )
        indexed = as_list(index.get("files"), "evidence_index.files")
        by_name = {str(ref["name"]): ref for ref in refs}
        prefix = f"formal/{formal_id}/"
        for item_raw in indexed:
            item = as_object(item_raw, "evidence index item")
            if set(item) != {"path", "sha256", "bytes"}:
                raise ContractError(
                    "evidence_index_schema_mismatch", "evidence index item fields differ"
                )
            full_name = prefix + str(item.get("path", ""))
            ref = by_name.get(full_name)
            if ref is None:
                raise SourceError(
                    "indexed_artifact_missing", f"indexed artifact missing: {full_name}"
                )
            if ref.get("sha256") != item.get("sha256") or ref.get("bytes") != item.get("bytes"):
                raise ContractError("evidence_index_mismatch", f"index mismatch for {full_name}")
            self.workspace.verify_ref(ref)
        expected_names = {
            str(ref["name"])
            for ref in refs
            if ref.get("name") != f"formal/{formal_id}/evidence_index.json"
        }
        indexed_names = {
            prefix + str(as_object(item, "evidence index item").get("path", "")) for item in indexed
        }
        if indexed_names != expected_names:
            raise ContractError(
                "evidence_index_incomplete",
                "evidence index does not cover the exact formal artifact set",
            )

    @staticmethod
    def _portfolio_returns(value: Any) -> list[PortfolioReturnPoint]:
        points = as_list(value, "portfolio_returns")
        result: list[PortfolioReturnPoint] = []
        for raw in points:
            item = as_object(raw, "portfolio return")
            timestamp = item.get("timestamp")
            if isinstance(timestamp, int | float):
                timestamp = datetime.fromtimestamp(float(timestamp) / 1_000_000_000, tz=UTC)
            result.append(
                PortfolioReturnPoint.model_validate(
                    {
                        "timestamp": timestamp,
                        "value": item.get("value", item.get("return")),
                        "frequency": "native-portfolio-period",
                        "timezone": "UTC",
                        "source": "nautilus-analyzer",
                    }
                )
            )
        return result

    @staticmethod
    def _available_object(value: Any, name: str) -> dict[str, Any]:
        item = as_object(value, name)
        if item.get("status") in {"unavailable", "not_evaluated"}:
            if not item.get("reason"):
                raise ContractError("availability_reason_missing", f"{name} lacks a reason")
            return item
        return as_object(item.get("value", item), name)

    @staticmethod
    def _runtime_identity(run: dict[str, Any]) -> dict[str, Any]:
        attempt_id = run.get("current_attempt_id")
        attempts = as_list(run.get("attempts"), "run.attempts")
        matches = [
            item
            for item in attempts
            if isinstance(item, Mapping) and item.get("attempt_id") == attempt_id
        ]
        if len(matches) != 1:
            raise ContractError("attempt_identity_missing", "current attempt was not found")
        return as_object(matches[0].get("runtime_identity"), "runtime_identity")

    @staticmethod
    def _formal_identity(identity: dict[str, Any], formal_id: str) -> dict[str, Any]:
        values = as_list(identity.get("formal"), "runtime_identity.formal")
        matches = [
            as_object(item, "formal identity")
            for item in values
            if isinstance(item, Mapping) and item.get("formal_id") == formal_id
        ]
        if len(matches) != 1:
            raise ContractError(
                "formal_identity_mismatch", "formal runtime identity is missing or ambiguous"
            )
        adapter = matches[0].get("adapter")
        if isinstance(adapter, Mapping):
            matches[0] = {**matches[0], **as_object(adapter, "adapter identity")}
        return matches[0]

    def _stream_normalized(
        self,
        ref: dict[str, Any],
        refs: list[dict[str, Any]],
        formal_id: str,
        native: dict[str, Any],
        options: ReportOptions,
    ) -> tuple[dict[str, Any], dict[str, TablePreview], dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="strategy-reporting-normalized-") as root:
            path = Path(root) / "normalized_output.json"
            self.workspace.materialize_verified(ref, path)
            keys = self._top_level_keys(path)
            if keys != NORMALIZED_ROOT_FIELDS:
                raise ContractError(
                    "normalized_output_schema_mismatch",
                    "normalized output root fields differ",
                )
            self._validate_section_types(path)
            schema = self._stream_single(path, "schema")
            if schema != "quant-runtime.nautilus-output.v1":
                raise ContractError(
                    "normalized_output_schema_mismatch", "normalized output schema differs"
                )
            if self._stream_single(path, "framework") != "NautilusTrader":
                raise ContractError(
                    "normalized_output_schema_mismatch", "normalized output framework differs"
                )
            if self._stream_single(path, "framework_version") != "1.231.0":
                raise ContractError(
                    "normalized_output_schema_mismatch",
                    "normalized output framework version differs",
                )
            self._enforce_value_budget(path, "native_statistics", MAX_NATIVE_STATISTICS_BYTES)
            embedded_native = as_object(
                self._stream_single(path, "native_statistics"),
                "normalized_output.native_statistics",
            )
            if canonical_json(embedded_native) != canonical_json(native):
                raise ContractError(
                    "normalized_native_statistics_mismatch",
                    "normalized output native statistics differ from the dedicated artifact",
                )
            self._enforce_value_budget(path, "metrics", MAX_NORMALIZED_METRICS_BYTES)
            metrics = as_object(self._stream_single(path, "metrics"), "normalized_output.metrics")
            if len(canonical_json(metrics)) > MAX_NORMALIZED_METRICS_BYTES:
                raise ContractError(
                    "normalized_metrics_too_large", "normalized output metrics exceed source cap"
                )
            execution = {
                section: self._stream_preview(path, section, refs, formal_id, options)
                for section in NORMALIZED_SECTIONS
            }
            facts = {
                key: self._stream_single(path, key)
                for key in (
                    "canonical_input_hash",
                    "data_version",
                    "dataset_version",
                    "decision_hash",
                    "strategy_spec_hash",
                    "normalized_output_hash",
                )
            }
            calculated_hash = self._normalized_semantic_hash(path)
            if facts["normalized_output_hash"] != calculated_hash:
                raise ContractError(
                    "normalized_output_identity_mismatch",
                    "normalized output hash does not match semantic payload",
                )
            return metrics, execution, facts

    @staticmethod
    def _top_level_keys(path: Path) -> set[str]:
        keys: set[str] = set()
        with path.open("rb") as stream:
            for prefix, event, value in ijson.parse(stream, use_float=True):
                if prefix == "" and event == "map_key":
                    key = str(value)
                    if key in keys:
                        raise ContractError(
                            "normalized_output_schema_mismatch",
                            f"normalized output has duplicate root field {key}",
                        )
                    keys.add(key)
        return keys

    @staticmethod
    def _validate_section_types(path: Path) -> None:
        boundaries: dict[str, list[str]] = {section: [] for section in NORMALIZED_SECTIONS}
        active_rows = {section: False for section in NORMALIZED_SECTIONS}
        row_sizes = {section: 0 for section in NORMALIZED_SECTIONS}
        with path.open("rb") as stream:
            for prefix, event, value in ijson.parse(stream, use_float=True):
                if prefix in boundaries:
                    boundaries[prefix].append(event)
                for section in NORMALIZED_SECTIONS:
                    item_prefix = f"{section}.item"
                    if prefix == item_prefix:
                        if event == "start_map":
                            if active_rows[section]:
                                raise ContractError(
                                    "normalized_output_schema_mismatch",
                                    f"normalized output {section} has an invalid nested row",
                                )
                            active_rows[section] = True
                            row_sizes[section] = 0
                        elif event == "end_map":
                            active_rows[section] = False
                        elif event == "map_key" and active_rows[section]:
                            pass
                        else:
                            raise ContractError(
                                "normalized_output_schema_mismatch",
                                f"normalized output {section} rows must be objects",
                            )
                    if active_rows[section] and prefix.startswith(item_prefix):
                        row_sizes[section] += len(prefix.encode("utf-8")) + len(
                            str(value).encode("utf-8")
                        )
                        if row_sizes[section] > MAX_NORMALIZED_ROW_BYTES:
                            raise ContractError(
                                "normalized_row_too_large",
                                f"normalized {section} row exceeds source cap",
                            )
        for section, events in boundaries.items():
            if events != ["start_array", "end_array"]:
                raise ContractError(
                    "normalized_output_schema_mismatch",
                    f"normalized output {section} must be an array",
                )

    @staticmethod
    def _enforce_value_budget(path: Path, prefix: str, maximum_bytes: int) -> None:
        measured = 0
        with path.open("rb") as stream:
            for item_prefix, _, value in ijson.parse(stream, use_float=True):
                if item_prefix == prefix or item_prefix.startswith(prefix + "."):
                    measured += len(item_prefix.encode("utf-8")) + len(str(value).encode("utf-8"))
                    if measured > maximum_bytes:
                        raise ContractError(
                            "normalized_value_too_large",
                            f"normalized output {prefix} exceeds source cap",
                        )

    @staticmethod
    def _stream_single(path: Path, prefix: str) -> Any:
        with path.open("rb") as stream:
            values = ijson.items(stream, prefix, use_float=True)
            try:
                value = next(values)
            except StopIteration as exc:
                raise ContractError(
                    "normalized_output_schema_mismatch",
                    f"normalized output lacks {prefix}",
                ) from exc
            try:
                next(values)
            except StopIteration:
                return value
        raise ContractError(
            "normalized_output_schema_mismatch",
            f"normalized output repeats {prefix}",
        )

    @staticmethod
    def _normalized_semantic_hash(path: Path) -> str:
        digest = sha256()
        semantic_fields = sorted(NORMALIZED_ROOT_FIELDS - {"metrics", "normalized_output_hash"})
        digest.update(b"{")
        for field_index, field in enumerate(semantic_fields):
            if field_index:
                digest.update(b",")
            digest.update(canonical_json(field))
            digest.update(b":")
            if field in NORMALIZED_SECTIONS:
                digest.update(b"[")
                with path.open("rb") as stream:
                    for item_index, item in enumerate(
                        ijson.items(stream, f"{field}.item", use_float=True)
                    ):
                        if item_index:
                            digest.update(b",")
                        digest.update(canonical_json(item))
                digest.update(b"]")
            else:
                digest.update(canonical_json(WorkspaceFormalRunAdapter._stream_single(path, field)))
        digest.update(b"}")
        return digest.hexdigest()

    @staticmethod
    def _verify_identity_mirrors(
        leg: dict[str, Any],
        package_ref: dict[str, Any],
        runtime_identity: dict[str, Any],
        snapshot: dict[str, Any],
        normalized: dict[str, Any],
    ) -> None:
        metrics = as_object(leg.get("metrics"), "formal leg metrics")
        expected = {
            "strategy_package_hash": package_ref.get("package_hash"),
            "parameters_hash": runtime_identity.get("parameters_hash"),
            "snapshot_id": snapshot.get("snapshot_id"),
            "formal_decision_hash": normalized["decision_hash"],
            "normalized_output_hash": normalized["normalized_output_hash"],
        }
        for key, value in expected.items():
            if metrics.get(key) != value:
                raise ContractError("formal_identity_mismatch", f"formal leg metric {key} differs")
        strategy_spec_hash = canonical_sha256(
            {
                "strategy_id": package_ref.get("strategy_id"),
                "revision": package_ref.get("revision"),
                "package_hash": package_ref.get("package_hash"),
                "parameters_hash": runtime_identity.get("parameters_hash"),
            }
        )
        if normalized["strategy_spec_hash"] != strategy_spec_hash:
            raise ContractError(
                "formal_identity_mismatch", "normalized strategy specification hash differs"
            )
        verification = snapshot.get("verification")
        if isinstance(verification, Mapping):
            for normalized_key, snapshot_key in (
                ("canonical_input_hash", "canonical_input_hash"),
                ("data_version", "data_version"),
                ("dataset_version", "dataset_version"),
            ):
                if normalized[normalized_key] != verification.get(snapshot_key):
                    raise ContractError(
                        "formal_identity_mismatch",
                        f"normalized {normalized_key} differs from snapshot verification",
                    )

    @staticmethod
    def _stream_preview(
        path: Path,
        section: str,
        refs: list[dict[str, Any]],
        formal_id: str,
        options: ReportOptions,
    ) -> TablePreview:
        total = 0
        preview: list[dict[str, Any]] = []
        with path.open("rb") as stream:
            for raw in ijson.items(stream, f"{section}.item", use_float=True):
                row = as_object(raw, f"{section} row")
                if len(canonical_json(row)) > MAX_NORMALIZED_ROW_BYTES:
                    raise ContractError(
                        "normalized_row_too_large", f"normalized {section} row exceeds source cap"
                    )
                total += 1
                if len(preview) < options.detail_row_limit:
                    preview.append(row)
        leaf = TABLE_FILES.get(section)
        source = None
        if leaf:
            exact = f"formal/{formal_id}/{leaf}"
            matches = [ArtifactRef.model_validate(ref) for ref in refs if ref.get("name") == exact]
            if len(matches) > 1:
                raise SourceError("artifact_name_ambiguous", f"duplicate artifact: {exact}")
            source = matches[0] if matches else None
        return TablePreview(
            total_rows=total,
            rows=preview,
            omitted_count=total - len(preview),
            source_artifact=source,
        )
