from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from strategy_reporting.canonical import bytes_sha256, canonical_json, canonical_sha256


class FakeWorkspaceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FakeWorkspace:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.records: dict[str, dict[str, Any]] = {}
        self.descriptors: dict[str, dict[str, Any]] = {}
        self.contents: dict[str, bytes] = {}
        self.publish_calls = 0
        self.created_at = "2026-08-24T01:02:03Z"

    def init(self) -> dict[str, Any]:
        return {"ok": True}

    def add_artifact(
        self,
        content: bytes,
        *,
        name: str,
        logical_role: str,
        media_type: str = "application/json",
        record_schema: str | None = None,
    ) -> dict[str, Any]:
        digest = bytes_sha256(content)
        descriptor = {
            "schema": "quant-research.artifact-ref.v1",
            "uri": f"workspace-artifact://sha256/{digest}",
            "sha256": digest,
            "bytes": len(content),
            "media_type": media_type,
            "record_schema": record_schema,
            "logical_role": logical_role,
            "name": name,
        }
        existing = self.descriptors.get(digest)
        if existing is not None:
            if (existing["schema"], existing["uri"], existing["sha256"], existing["bytes"]) != (
                descriptor["schema"],
                descriptor["uri"],
                descriptor["sha256"],
                descriptor["bytes"],
            ):
                raise FakeWorkspaceError("artifact_metadata_conflict", name)
        else:
            self.descriptors[digest] = descriptor
        self.contents[digest] = content
        return descriptor

    def get_run(self, run_id: str) -> dict[str, Any]:
        if run_id not in self.runs:
            raise FakeWorkspaceError("run_not_found", run_id)
        return self.runs[run_id]

    def get_result(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        return {"run_id": run_id, "status": run["status"], "result": run["result"]}

    def get_record(self, record_id: str) -> dict[str, Any]:
        if record_id not in self.records:
            raise FakeWorkspaceError("record_not_found", record_id)
        return self.records[record_id]

    def list_records(
        self, *, record_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        values = [
            item
            for item in self.records.values()
            if record_type is None or item["record_type"] == record_type
        ]
        return sorted(
            values, key=lambda item: (item["created_at"], item["record_id"]), reverse=True
        )[:limit]

    def read_artifact(self, artifact_uri: str) -> dict[str, Any]:
        digest = artifact_uri.rsplit("/", 1)[-1]
        return {
            "artifact": self.descriptors[digest],
            "encoding": "base64",
            "content": base64.b64encode(self.contents[digest]).decode("ascii"),
        }

    def materialize_artifact(self, artifact_uri: str, destination: Path) -> dict[str, Any]:
        digest = artifact_uri.rsplit("/", 1)[-1]
        destination.write_bytes(self.contents[digest])
        return {
            "artifact": self.descriptors[digest],
            "path": str(destination.resolve()),
            "materialized": True,
        }

    def verify_artifact(self, artifact_uri: str) -> dict[str, Any]:
        digest = artifact_uri.rsplit("/", 1)[-1]
        descriptor = self.descriptors[digest]
        content = self.contents[digest]
        return {
            "artifact": descriptor,
            "verified": bytes_sha256(content) == digest and len(content) == descriptor["bytes"],
        }

    def publish_record(
        self, record: dict[str, Any], *, artifacts: tuple[dict[str, Any], ...] = ()
    ) -> dict[str, Any]:
        self.publish_calls += 1
        refs = [
            self.add_artifact(
                bytes(item["source"]),
                name=str(item["name"]),
                logical_role=str(item["logical_role"]),
                media_type=str(item["media_type"]),
                record_schema=item.get("record_schema"),
            )
            for item in artifacts
        ]
        publication = {
            "schema": "quant-research.publication.v1",
            "record_id": record["record_id"],
            "record_type": record["record_type"],
            "created_at": self.created_at,
            "payload": record["payload"],
            "artifacts": refs,
            "lineage": record.get("lineage", []),
        }
        existing = self.records.get(record["record_id"])
        if existing is not None and existing != publication:
            raise FakeWorkspaceError("record_conflict", record["record_id"])
        self.records[record["record_id"]] = publication
        return publication


def add_formal_run(
    workspace: FakeWorkspace,
    *,
    run_id: str = "run_formal_1",
    formal_ids: tuple[str, ...] = ("primary",),
    returns: list[dict[str, str]] | None = None,
    malicious: bool = False,
    order_count: int = 1,
    strategy_id: str = "safe-strategy",
    package_hash: str = "p" * 64,
    parameters_hash: str = "q" * 64,
    snapshot_id: str = "sha256:" + "s" * 64,
) -> str:
    if returns is None:
        returns = [
            {"timestamp": "2026-01-02T00:00:00Z", "value": "0.01"},
            {"timestamp": "2026-01-03T00:00:00Z", "value": "-0.005"},
        ]
    all_refs: list[dict[str, Any]] = []
    formal: dict[str, Any] = {}
    formal_identity: list[dict[str, Any]] = []
    for formal_id in formal_ids:
        native = {
            "schema": "quant-runtime.nautilus-reporting-input.v1",
            "stats_pnls": {"PnL (total)": "1250.50"},
            "stats_returns": {"Sharpe Ratio (252 days)": "1.25"},
            "summary": {"Total PnL": "1250.50"},
            "total_events": 30,
            "total_orders": 1,
            "total_positions": 1,
            "stats_general": {"Win Rate": "0.60"},
            "portfolio_returns": returns,
            "run_info": {
                "trader_id": "BACKTESTER-001",
                "machine_id": "machine",
                "run_config_id": None,
                "instance_id": "instance",
                "run_id": f"native-{formal_id}",
                "run_started": "2026-01-01T00:00:00Z",
                "run_finished": "2026-01-04T00:00:00Z",
                "backtest_start": "2026-01-01T00:00:00Z",
                "backtest_end": "2026-01-04T00:00:00Z",
                "elapsed_time_seconds": "0.25",
                "iterations": 1,
                "total_events": 30,
                "total_orders": 1,
                "total_positions": 1,
            },
            "account_info": {
                "Starting balance (USD)": "100000 USD",
                "Ending balance (USD)": "101250.50 USD",
            },
            "extraction": {
                "version": "1",
                "source": "nautilus-public-api",
                "engine_version": "1.231.0",
                "interfaces": {
                    "account_info": "Account.starting_balances()/balance_total()",
                    "portfolio_returns": "PortfolioAnalyzer.portfolio_returns()",
                    "run_info": "BacktestResult",
                    "stats_general": "BacktestResult.stats_general",
                    "stats_pnls": "BacktestResult.stats_pnls",
                    "stats_returns": "BacktestResult.stats_returns",
                },
                "portfolio_returns_order": "timestamp_ascending_unique",
            },
            "availability": {
                "account_info": {"status": "available"},
                "portfolio_returns": {"status": "available"}
                if returns
                else {"status": "unavailable", "reason": "native_series_empty"},
                "run_info": {"status": "partial", "reason": "native_values_unavailable"},
                "stats_general": {"status": "available"},
                "stats_pnls": {"status": "available"},
                "stats_returns": {"status": "available"},
            },
            "unavailable": [
                {"path": "run_info.run_config_id", "reason": "native_value_unavailable"}
            ],
        }
        reason = '"><img src=x onerror="alert(1)">' if malicious else "none"
        strategy_spec_hash = canonical_sha256(
            {
                "strategy_id": strategy_id,
                "revision": 1,
                "package_hash": package_hash,
                "parameters_hash": parameters_hash,
            }
        )
        normalized_semantic = {
            "schema": "quant-runtime.nautilus-output.v1",
            "framework": "NautilusTrader",
            "framework_version": "1.231.0",
            "data_version": "fixture-data-v1",
            "dataset_version": "fixture-dataset-v1",
            "canonical_input_hash": "a" * 64,
            "strategy_spec_hash": strategy_spec_hash,
            "decision_hash": "c" * 64,
            "orders": [
                {
                    "instrument": "<script>alert(1)</script>" if malicious else f"AAPL-{index}",
                    "quantity": "1",
                }
                for index in range(order_count)
            ],
            "rejects": [{"reason": reason}] if malicious else [],
            "fills": [],
            "positions": [],
            "account_curve": [],
            "fees": [],
            "decisions": [],
            "native_statistics": native,
        }
        normalized = {
            **normalized_semantic,
            "metrics": {},
            "normalized_output_hash": bytes_sha256(canonical_json(normalized_semantic)),
        }
        prefix = f"formal/{formal_id}/"
        raw_files = {
            "native_statistics.json": canonical_json(native),
            "normalized_output.json": canonical_json(normalized),
        }
        index = {
            "schema": "quant-runtime.native-evidence-index.v1",
            "formal_id": formal_id,
            "files": [
                {"path": name, "sha256": bytes_sha256(content), "bytes": len(content)}
                for name, content in sorted(raw_files.items())
            ],
        }
        for name, content in {**raw_files, "evidence_index.json": canonical_json(index)}.items():
            all_refs.append(
                workspace.add_artifact(
                    content,
                    name=prefix + name,
                    logical_role="engine-native-evidence",
                    record_schema="quant-runtime.nautilus-reporting-input.v1"
                    if name == "native_statistics.json"
                    else None,
                )
            )
        formal[formal_id] = {
            "adapter": "nautilus",
            "metrics": {
                "sharpe": 1.25,
                "strategy_package_hash": package_hash,
                "parameters_hash": parameters_hash,
                "snapshot_id": snapshot_id,
                "formal_decision_hash": normalized["decision_hash"],
                "normalized_output_hash": normalized["normalized_output_hash"],
            },
        }
        formal_identity.append(
            {
                "formal_id": formal_id,
                "adapter": {"adapter": "nautilus", "adapter_version": "0.2.0"},
                "config_hash": "c" * 64,
            }
        )
    attempt_id = "attempt_1"
    result = {
        "schema": "quant-research.result.v2",
        "outcome": "completed",
        "summary": {
            "attempt_id": attempt_id,
            "topology": "formal_only" if len(formal_ids) == 1 else "formal_comparison",
        },
        "formal": formal,
        "artifacts": all_refs,
    }
    workspace.runs[run_id] = {
        "schema": "quant-research.run-record.v1",
        "run_id": run_id,
        "request_hash": "r" * 64,
        "request": {
            "schema": "quant-research.workspace-run-request.v2",
            "strategy_package": {
                "strategy_id": strategy_id,
                "revision": 1,
                "package_hash": package_hash,
            },
            "market_snapshot": {
                "schema": "quant-research.market-snapshot-ref.v1",
                "snapshot_id": snapshot_id,
                "source": {"adapter": "fixture"},
                "query": {
                    "instruments": ["AAPL"],
                    "start": "2026-01-01",
                    "end": "2026-01-04",
                    "frequency": "1d",
                    "adjustment": "none",
                },
                "verification": {
                    "canonical_input_hash": normalized["canonical_input_hash"],
                    "data_version": normalized["data_version"],
                    "dataset_version": normalized["dataset_version"],
                    "catalog_hash": "1" * 64,
                    "calendar_hash": "2" * 64,
                    "coverage_hash": "3" * 64,
                },
            },
            "parameters": {"lookback": 20},
            "execution": {"topology": "formal_only"},
        },
        "package": {
            "manifest": {"name": "<script>alert(1)</script>" if malicious else "Safe Strategy"}
        },
        "status": "completed",
        "current_attempt_id": attempt_id,
        "result": result,
        "attempts": [
            {
                "attempt_id": attempt_id,
                "runtime_identity": {
                    "schema": "quant-runtime.identity.v2",
                    "parameters_hash": parameters_hash,
                    "formal": formal_identity,
                },
            }
        ],
    }
    return run_id


def add_apex_source(
    workspace: FakeWorkspace, *, study_id: str = "1" * 64, discovery: bool = False
) -> str:
    protocol = {
        "schema": "apex-research.protocol.v2",
        "protocol_id": "protocol-1",
        "title": "<script>研究</script>",
        "strategy_package": {
            "schema": "quant-research.strategy-package-ref.v1",
            "strategy_id": "safe-strategy",
            "revision": 1,
            "package_hash": "b" * 64,
        },
        "topology": "discovery_formal" if discovery else "formal_only",
        "gate_specs": [
            {
                "gate": "sharpe",
                "metric": "formal.primary.metrics.sharpe",
                "operator": "gte",
                "threshold": 1.0,
            }
        ],
    }
    trial_id = "2" * 64
    run_id = "run_apex_1"
    trial_ref = {"record_id": "trial-record-1", "record_type": "apex-research.trial.v1"}
    trial = {
        "sequence": 1,
        "source": trial_ref,
        "trial_id": trial_id,
        "workspace_run_id": run_id,
        "request_hash": "3" * 64,
        "result_identity": "4" * 64,
        "run_status": "completed",
        "result_outcome": "completed",
        "topology": protocol["topology"],
        "parameters": {"lookback": 20},
        "snapshot_window": {
            "snapshot_id": "snapshot-1",
            "start": "2026-01-01",
            "end": "2026-01-31",
            "frequency": "1d",
            "adjustment": "none",
        },
        "discovery": {
            "adapter": "qlib",
            "config": {},
            "result_identity": "5" * 64,
            "metrics": {"rank": 1},
        }
        if discovery
        else None,
        "formal_legs": [
            {
                "formal_id": "primary",
                "adapter": "nautilus",
                "config": {},
                "result_identity": "6" * 64,
                "metrics": {"sharpe": 1.25},
            }
        ],
    }
    gate_value = {
        "schema": "apex-research.gate-result.v2",
        "trial_id": trial_id,
        "gate": "sharpe",
        "status": "pass",
        "metric": "formal.primary.metrics.sharpe",
        "observed": 1.25,
        "operator": "gte",
        "threshold": 1.0,
        "failure": None,
    }
    gate_value["gate_result_id"] = canonical_sha256(gate_value)
    gate_ref = {"record_id": "gate-record-1", "record_type": "apex-research.gate-result.v2"}
    evidence_ref = {"record_id": "evidence-record-1", "record_type": "apex-research.evidence.v1"}
    evidence = {
        "schema": "apex-research.evidence.v1",
        "source": evidence_ref,
        "study_id": study_id,
        "protocol_record_id": "protocol-record-1",
        "trial_record_id": trial_ref["record_id"],
        "gate_record_ids": [gate_ref["record_id"]],
        "workspace_run_ids": [run_id],
        "artifact_uris": ["workspace-artifact://sha256/" + "a" * 64],
        "artifacts_verified": True,
    }
    decision_value = {
        "schema": "apex-research.decision.v2",
        "study_id": study_id,
        "protocol_hash": canonical_sha256(protocol),
        "current_trial_id": trial_id,
        "trial_ids": [trial_id],
        "workspace_run_ids": [run_id],
        "gate_result_ids": [gate_value["gate_result_id"]],
        "evidence_record_id": evidence_ref["record_id"],
        "research_metrics": {"accepted": True},
        "status": "accept",
    }
    decision_value["decision_id"] = canonical_sha256(decision_value)
    refs = [
        {"record_id": "protocol-record-1", "record_type": "apex-research.protocol.v2"},
        trial_ref,
        gate_ref,
        evidence_ref,
        {"record_id": "decision-record-1", "record_type": "apex-research.decision.v2"},
    ]
    absent = {"status": "not_evaluated", "items": [], "reason": "no published evidence"}
    available_discovery = {"status": "available", "items": [trial_id], "reason": None}
    payload = {
        "schema": "apex-research.study-report-source.v1",
        "study_id": study_id,
        "protocol": protocol,
        "trials": [trial],
        "gate_results": [{"source": gate_ref, "result": gate_value}],
        "evidence": [evidence],
        "decision": decision_value,
        "research_metrics": dict(decision_value["research_metrics"]),
        "availability": {
            "discovery": available_discovery if discovery else absent,
            "robustness": absent,
            "sensitivity": absent,
            "capacity": absent,
        },
        "sources": refs,
        "source_record_ids": [item["record_id"] for item in refs],
        "workspace_run_ids": [run_id],
    }
    payload["source_id"] = canonical_sha256(payload)
    record_id = payload["source_id"]
    workspace.records[record_id] = {
        "schema": "quant-research.publication.v1",
        "record_id": record_id,
        "record_type": "apex-research.study-report-source.v1",
        "created_at": "2026-08-23T00:00:00Z",
        "payload": payload,
        "artifacts": [],
        "lineage": [
            {
                "source_kind": item["record_type"],
                "source_id": item["record_id"],
                "relation": "derived-from",
            }
            for item in refs
        ]
        + [{"source_kind": "workspace-run", "source_id": run_id, "relation": "reports"}],
    }
    return study_id


@pytest.fixture
def workspace() -> FakeWorkspace:
    return FakeWorkspace()
