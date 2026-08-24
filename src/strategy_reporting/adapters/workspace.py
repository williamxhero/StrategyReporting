from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from strategy_reporting.canonical import bytes_sha256, parse_json_bytes
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import ArtifactRef


class WorkspaceClientPort(Protocol):
    def init(self) -> dict[str, Any]: ...
    def get_run(self, run_id: str) -> dict[str, Any]: ...
    def get_result(self, run_id: str) -> dict[str, Any]: ...
    def get_record(self, record_id: str) -> dict[str, Any]: ...
    def list_records(
        self, *, record_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]: ...
    def read_artifact(self, artifact_uri: str) -> dict[str, Any]: ...
    def materialize_artifact(self, artifact_uri: str, destination: Path) -> dict[str, Any]: ...
    def verify_artifact(self, artifact_uri: str) -> dict[str, Any]: ...
    def publish_record(
        self,
        record: Mapping[str, Any],
        *,
        artifacts: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]: ...


def production_client(workspace_root: Path | None) -> WorkspaceClientPort:
    from strategy_workspace import WorkspaceClient

    return cast(
        WorkspaceClientPort,
        WorkspaceClient(workspace_root) if workspace_root else WorkspaceClient(),
    )


class WorkspaceAdapter:
    def __init__(self, client: WorkspaceClientPort) -> None:
        self.client = client

    def read_verified_bytes(self, raw_ref: Mapping[str, Any]) -> bytes:
        ref = self.verify_ref(raw_ref)
        try:
            response = self.client.read_artifact(ref.uri)
        except (SourceError, ContractError):
            raise
        except Exception as exc:
            raise SourceError(
                "artifact_read_failed", f"cannot read artifact {ref.name}: {exc}"
            ) from exc
        if response.get("encoding") != "base64" or not isinstance(response.get("content"), str):
            raise ContractError(
                "artifact_encoding_invalid", f"artifact {ref.name} is not strict base64"
            )
        read_ref = ArtifactRef.model_validate(response.get("artifact"))
        if content_identity(read_ref) != content_identity(ref):
            raise ContractError(
                "artifact_descriptor_mismatch",
                f"Workspace read identity differs from source reference: {ref.name}",
            )
        try:
            content = base64.b64decode(response["content"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ContractError("artifact_base64_invalid", f"artifact {ref.name}: {exc}") from exc
        if len(content) != ref.bytes or bytes_sha256(content) != ref.sha256:
            raise ContractError("artifact_integrity_failed", f"artifact bytes mismatch: {ref.name}")
        return content

    def read_verified_json(self, raw_ref: Mapping[str, Any], *, maximum_bytes: int) -> Any:
        ref = ArtifactRef.model_validate(raw_ref)
        if ref.bytes > maximum_bytes:
            raise ContractError(
                "model_too_large",
                f"JSON artifact {ref.name} declares {ref.bytes} bytes; limit is {maximum_bytes}",
            )
        return parse_json_bytes(self.read_verified_bytes(raw_ref), maximum_bytes=maximum_bytes)

    def verify_ref(self, raw_ref: Mapping[str, Any]) -> ArtifactRef:
        ref = ArtifactRef.model_validate(raw_ref)
        try:
            verified = self.client.verify_artifact(ref.uri)
        except Exception as exc:
            raise SourceError(
                "artifact_verification_failed", f"cannot verify artifact {ref.name}: {exc}"
            ) from exc
        if verified.get("verified") is not True:
            raise SourceError(
                "artifact_verification_failed", f"artifact is not verified: {ref.name}"
            )
        try:
            verified_ref = ArtifactRef.model_validate(verified.get("artifact"))
        except ValueError as exc:
            raise ContractError(
                "artifact_descriptor_mismatch",
                f"Workspace returned an invalid descriptor for {ref.name}",
            ) from exc
        if content_identity(verified_ref) != content_identity(ref):
            raise ContractError(
                "artifact_descriptor_mismatch",
                f"Workspace content identity differs from source reference: {ref.name}",
            )
        return ref

    def materialize_verified(self, raw_ref: Mapping[str, Any], destination: Path) -> ArtifactRef:
        ref = self.verify_ref(raw_ref)
        try:
            response = self.client.materialize_artifact(ref.uri, destination)
        except Exception as exc:
            raise SourceError(
                "artifact_materialization_failed", f"cannot materialize {ref.name}: {exc}"
            ) from exc
        if Path(str(response.get("path"))).resolve() != destination.resolve():
            raise ContractError(
                "artifact_materialization_mismatch",
                f"Workspace materialized {ref.name} to an unexpected path",
            )
        try:
            materialized_ref = ArtifactRef.model_validate(response.get("artifact"))
        except ValueError as exc:
            raise ContractError(
                "artifact_materialization_mismatch",
                f"Workspace returned an invalid materialized descriptor for {ref.name}",
            ) from exc
        if content_identity(materialized_ref) != content_identity(ref):
            raise ContractError(
                "artifact_materialization_mismatch",
                f"Workspace materialized identity differs for {ref.name}",
            )
        return ref


def as_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("invalid_source_contract", f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def as_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError("invalid_source_contract", f"{name} must be an array")
    return value


def content_identity(ref: ArtifactRef) -> tuple[str, str, str, int]:
    return ref.schema_id, ref.uri, ref.sha256, ref.bytes
