from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import bytes_sha256, canonical_sha256
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import (
    Availability,
    FormalRunReport,
    ReportOptions,
    ResearchStudyReport,
    ResearchSubject,
    StrictModel,
)

APEX_SOURCE_TYPE = "apex-research.study-report-source.v1"
Scalar = str | int | float | bool | None


class SourceRef(StrictModel):
    record_id: str = Field(min_length=1)
    record_type: str = Field(min_length=1)


class StrategyPackageRef(StrictModel):
    schema_id: Literal["quant-research.strategy-package-ref.v1"] = Field(alias="schema")
    strategy_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    package_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class GateSpec(StrictModel):
    gate: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    threshold: Scalar


class Protocol(StrictModel):
    schema_id: Literal["apex-research.protocol.v2"] = Field(alias="schema")
    protocol_id: str = Field(min_length=1)
    title: str | None = None
    strategy_package: StrategyPackageRef
    topology: Literal["formal_only", "discovery_formal", "formal_comparison", "agreement_gate"]
    gate_specs: list[GateSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_unique_gates(self) -> Protocol:
        names = [item.gate for item in self.gate_specs]
        if len(names) != len(set(names)):
            raise ValueError("protocol gate names must be unique")
        return self


class SnapshotWindow(StrictModel):
    snapshot_id: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None
    frequency: str | None = None
    adjustment: str | None = None


class DiscoveryLeg(StrictModel):
    adapter: str = Field(min_length=1)
    config: dict[str, Any]
    result_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, Scalar]


class FormalLeg(StrictModel):
    formal_id: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    config: dict[str, Any]
    result_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, Scalar]


class Trial(StrictModel):
    sequence: int = Field(ge=1)
    source: SourceRef
    trial_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_run_id: str = Field(min_length=1)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_status: str = Field(min_length=1)
    result_outcome: str = Field(min_length=1)
    topology: Literal["formal_only", "discovery_formal", "formal_comparison", "agreement_gate"]
    parameters: dict[str, Any]
    snapshot_window: SnapshotWindow
    discovery: DiscoveryLeg | None
    formal_legs: list[FormalLeg] = Field(min_length=1)


class GateResultValue(StrictModel):
    schema_id: Literal["apex-research.gate-result.v2"] = Field(alias="schema")
    gate_result_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate: str = Field(min_length=1)
    status: Literal["pass", "fail"]
    metric: str = Field(min_length=1)
    observed: Scalar
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    threshold: Scalar
    failure: Literal["missing", "nonfinite", "incomparable", "threshold"] | None

    @model_validator(mode="after")
    def verify_identity(self) -> GateResultValue:
        if self.gate_result_id != canonical_sha256(
            self.model_dump(mode="json", exclude={"gate_result_id"})
        ):
            raise ValueError("gate_result_id does not match canonical identity")
        if (self.status == "pass") != (self.failure is None):
            raise ValueError("gate status and failure reason disagree")
        return self


class GateResult(StrictModel):
    source: SourceRef
    result: GateResultValue


class Evidence(StrictModel):
    schema_id: Literal["apex-research.evidence.v1"] = Field(alias="schema")
    source: SourceRef
    study_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_record_id: str = Field(min_length=1)
    trial_record_id: str = Field(min_length=1)
    gate_record_ids: list[str] = Field(min_length=1)
    workspace_run_ids: list[str] = Field(min_length=1)
    artifact_uris: list[str] = Field(min_length=1)
    artifacts_verified: Literal[True]


class Decision(StrictModel):
    schema_id: Literal["apex-research.decision.v2"] = Field(alias="schema")
    decision_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    study_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_trial_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_ids: list[str] = Field(min_length=1)
    workspace_run_ids: list[str] = Field(min_length=1)
    gate_result_ids: list[str] = Field(min_length=1)
    evidence_record_id: str = Field(min_length=1)
    research_metrics: dict[str, Scalar]
    status: Literal["accept", "reject"]

    @model_validator(mode="after")
    def verify_identity(self) -> Decision:
        if self.current_trial_id != self.trial_ids[-1]:
            raise ValueError("current trial is not the final trial")
        if self.decision_id != canonical_sha256(
            self.model_dump(mode="json", exclude={"decision_id"})
        ):
            raise ValueError("decision_id does not match canonical identity")
        return self


class SourceSectionAvailability(StrictModel):
    status: Literal["available", "not_evaluated"]
    items: list[str]
    reason: str | None

    @model_validator(mode="after")
    def verify_status(self) -> SourceSectionAvailability:
        if self.status == "available" and (not self.items or self.reason is not None):
            raise ValueError("available source section requires items and no reason")
        if self.status == "not_evaluated" and (self.items or not self.reason):
            raise ValueError("not_evaluated source section requires reason and no items")
        return self


class SourceAvailability(StrictModel):
    discovery: SourceSectionAvailability
    robustness: SourceSectionAvailability
    sensitivity: SourceSectionAvailability
    capacity: SourceSectionAvailability


class ApexStudyReportSource(StrictModel):
    schema_id: Literal["apex-research.study-report-source.v1"] = Field(alias="schema")
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    study_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol: Protocol
    trials: list[Trial] = Field(min_length=1)
    gate_results: list[GateResult] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    decision: Decision
    research_metrics: dict[str, Scalar]
    availability: SourceAvailability
    sources: list[SourceRef] = Field(min_length=1)
    source_record_ids: list[str] = Field(min_length=1)
    workspace_run_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_identity_and_references(self) -> ApexStudyReportSource:
        if self.source_id != canonical_sha256(self.model_dump(mode="json", exclude={"source_id"})):
            raise ValueError("source_id does not match canonical source payload")
        if self.study_id != self.decision.study_id:
            raise ValueError("source study differs from decision")
        if canonical_sha256(self.protocol.model_dump(mode="json")) != self.decision.protocol_hash:
            raise ValueError("source protocol differs from decision")
        if [item.trial_id for item in self.trials] != self.decision.trial_ids:
            raise ValueError("trials do not follow decision order")
        if [item.workspace_run_id for item in self.trials] != self.workspace_run_ids:
            raise ValueError("workspace runs do not follow trial order")
        if self.workspace_run_ids != self.decision.workspace_run_ids:
            raise ValueError("workspace runs differ from decision")
        if self.research_metrics != self.decision.research_metrics:
            raise ValueError("research metrics differ from decision")
        if [item.record_id for item in self.sources] != self.source_record_ids:
            raise ValueError("source records differ from source refs")
        expected_types = [
            "apex-research.protocol.v2",
            *("apex-research.trial.v1" for _ in self.trials),
            *("apex-research.gate-result.v2" for _ in self.gate_results),
            *("apex-research.evidence.v1" for _ in self.evidence),
            "apex-research.decision.v2",
        ]
        if [item.record_type for item in self.sources] != expected_types:
            raise ValueError("source record types or order differ from public contract")
        embedded_sources = [
            *(item.source for item in self.trials),
            *(item.source for item in self.gate_results),
            *(item.source for item in self.evidence),
        ]
        if self.sources[1:-1] != embedded_sources:
            raise ValueError("source refs do not match structured source records")
        embedded_ids = {
            *(item.source.record_id for item in self.trials),
            *(item.source.record_id for item in self.gate_results),
            *(item.source.record_id for item in self.evidence),
        }
        if not embedded_ids <= set(self.source_record_ids):
            raise ValueError("embedded source refs are absent from ordered sources")
        if [item.sequence for item in self.trials] != list(range(1, len(self.trials) + 1)):
            raise ValueError("trial sequence is not contiguous")
        gate_ids = {item.result.gate_result_id for item in self.gate_results}
        if any(item not in gate_ids for item in self.decision.gate_result_ids):
            raise ValueError("decision gate result is missing")
        if self.decision.evidence_record_id not in {
            item.source.record_id for item in self.evidence
        }:
            raise ValueError("decision evidence is missing")
        trial_ids = {item.trial_id for item in self.trials}
        if any(item.result.trial_id not in trial_ids for item in self.gate_results):
            raise ValueError("gate result references an unknown trial")
        trial_record_ids = {item.source.record_id for item in self.trials}
        gate_record_ids = {item.source.record_id for item in self.gate_results}
        run_ids = set(self.workspace_run_ids)
        for item in self.evidence:
            if item.protocol_record_id != self.sources[0].record_id:
                raise ValueError("evidence references an unknown protocol record")
            if item.trial_record_id not in trial_record_ids:
                raise ValueError("evidence references an unknown trial record")
            if any(record_id not in gate_record_ids for record_id in item.gate_record_ids):
                raise ValueError("evidence references an unknown gate record")
            if any(run_id not in run_ids for run_id in item.workspace_run_ids):
                raise ValueError("evidence references an unknown Workspace run")
        return self


class ApexResearchPublicationAdapter:
    kind: Literal["research-study"] = "research-study"

    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace

    def build_model(self, subject_id: str, options: ReportOptions) -> ResearchStudyReport:
        try:
            records = self.workspace.client.list_records(record_type=APEX_SOURCE_TYPE, limit=10_000)
        except Exception as exc:
            raise SourceError(
                "apex_source_read_failed", f"cannot list Apex report sources: {exc}"
            ) from exc
        if len(records) == 10_000:
            raise ContractError(
                "apex_source_list_truncated",
                "Apex source list reached the 10,000 record hard cap",
            )
        matches = [
            record for record in records if record.get("payload", {}).get("study_id") == subject_id
        ]
        if not matches:
            raise SourceError(
                "apex_source_missing",
                f"no {APEX_SOURCE_TYPE} publication for study {subject_id}; Markdown fallback is forbidden",
            )
        selected = self._select_source(matches, options.decision_id)
        if selected.get("record_type") != APEX_SOURCE_TYPE:
            raise ContractError("record_type_mismatch", "Apex source record_type differs")
        try:
            source = ApexStudyReportSource.model_validate(selected.get("payload"), strict=True)
        except ValueError as exc:
            raise ContractError("apex_source_contract_invalid", str(exc)) from exc
        if source.study_id != subject_id:
            raise ContractError("study_identity_mismatch", "Apex source study_id differs")
        if selected.get("record_id") != source.source_id:
            raise ContractError(
                "source_publication_identity_mismatch",
                "Apex source record_id differs from source_id",
            )
        expected_lineage = [
            {
                "source_kind": item.record_type,
                "source_id": item.record_id,
                "relation": "derived-from",
            }
            for item in source.sources
        ] + [
            {"source_kind": "workspace-run", "source_id": item, "relation": "reports"}
            for item in source.workspace_run_ids
        ]
        if selected.get("lineage") != expected_lineage or selected.get("artifacts") != []:
            raise ContractError(
                "source_publication_lineage_mismatch",
                "Apex source publication top-level lineage or artifact set differs",
            )
        if options.decision_id and options.decision_id != source.decision.decision_id:
            raise SourceError("decision_not_found", f"decision not found: {options.decision_id}")
        return ResearchStudyReport(
            title=(f"{source.protocol.strategy_package.strategy_id} · 正式复现研究评审"),
            subject=ResearchSubject(
                study_id=source.study_id,
                decision_id=source.decision.decision_id,
                protocol_hash=source.decision.protocol_hash,
            ),
            strategy_package=source.protocol.strategy_package.model_dump(mode="json"),
            hypothesis=(
                "验证冻结策略包在指定市场快照与执行配置下是否完成一次"
                "可追溯的正式运行, 并通过协议声明的证据完整性门槛。"
            ),
            protocol=source.protocol.model_dump(mode="json"),
            gate_specs=[item.model_dump(mode="json") for item in source.protocol.gate_specs],
            trials=[item.model_dump(mode="json") for item in source.trials],
            discovery=Availability.model_validate(
                source.availability.discovery.model_dump(mode="json")
            ),
            formal_runs=[
                {
                    "trial_id": trial.trial_id,
                    "workspace_run_id": trial.workspace_run_id,
                    "formal_legs": [leg.model_dump(mode="json") for leg in trial.formal_legs],
                }
                for trial in source.trials
            ],
            gate_results=[item.model_dump(mode="json") for item in source.gate_results],
            evidence=[item.model_dump(mode="json") for item in source.evidence],
            research_metrics=source.research_metrics,
            robustness=Availability.model_validate(
                source.availability.robustness.model_dump(mode="json")
            ),
            sensitivity=Availability.model_validate(
                source.availability.sensitivity.model_dump(mode="json")
            ),
            capacity=Availability.model_validate(
                source.availability.capacity.model_dump(mode="json")
            ),
            final_decision=source.decision.model_dump(mode="json"),
            related_formal_reports=self._formal_links(source.workspace_run_ids),
            unavailable_sections=[
                Availability.model_validate(item.model_dump(mode="json"))
                for item in (
                    source.availability.discovery,
                    source.availability.robustness,
                    source.availability.sensitivity,
                    source.availability.capacity,
                )
                if item.status != "available"
            ],
            source_publication={
                "record_id": str(selected.get("record_id")),
                "record_type": APEX_SOURCE_TYPE,
                "source_id": source.source_id,
            },
            source_records=[item.model_dump(mode="json") for item in source.sources],
            source_record_ids=source.source_record_ids,
            workspace_run_ids=source.workspace_run_ids,
        )

    @staticmethod
    def _select_source(records: list[dict[str, Any]], decision_id: str | None) -> dict[str, Any]:
        if decision_id:
            matches = [
                record
                for record in records
                if record.get("payload", {}).get("decision", {}).get("decision_id") == decision_id
            ]
            if len(matches) != 1:
                raise SourceError(
                    "decision_not_found", f"expected one source for decision {decision_id}"
                )
            return matches[0]
        return sorted(
            records,
            key=lambda item: (str(item.get("created_at", "")), str(item.get("record_id", ""))),
        )[-1]

    def _formal_links(self, run_ids: list[str]) -> list[dict[str, Any]]:
        try:
            reports = self.workspace.client.list_records(
                record_type="strategy-reporting.report-descriptor.v1", limit=10_000
            )
        except Exception as exc:
            raise SourceError("formal_report_lookup_failed", str(exc)) from exc
        if len(reports) == 10_000:
            raise ContractError(
                "formal_report_list_truncated",
                "formal report list reached the 10,000 record hard cap",
            )
        from strategy_reporting.publishing import WorkspaceReportPublisher

        publisher = WorkspaceReportPublisher(self.workspace)
        validated: list[tuple[str, str, FormalRunReport, str]] = []
        for raw in reports:
            report_id = str(raw.get("record_id", ""))
            publication = publisher.inspect(report_id)
            if publication.envelope.report_kind != "formal-run":
                continue
            model_refs = [
                item
                for item in publication.envelope.artifacts
                if item.logical_role == "report-model"
            ]
            if len(model_refs) != 1:
                raise ContractError(
                    "formal_link_model_ambiguous",
                    f"formal report model is missing or ambiguous: {report_id}",
                )
            content = self.workspace.read_verified_bytes(model_refs[0].model_dump(mode="json"))
            if bytes_sha256(content) != publication.envelope.identity.model_sha256:
                raise ContractError(
                    "formal_link_model_mismatch", f"formal report model hash differs: {report_id}"
                )
            try:
                model = FormalRunReport.model_validate_json(content, strict=True)
            except ValueError as exc:
                raise ContractError(
                    "formal_link_model_invalid", f"formal report model is invalid: {report_id}"
                ) from exc
            publisher.verify_semantic_descriptor(publication.publication, model, content)
            validated.append(
                (
                    str(raw.get("created_at", "")),
                    report_id,
                    model,
                    publication.envelope.generated_at.isoformat(),
                )
            )
        links: list[dict[str, Any]] = []
        for run_id in run_ids:
            latest_by_formal: dict[str, tuple[str, str, FormalRunReport, str]] = {}
            for item in validated:
                model = item[2]
                if model.subject.workspace_run_id != run_id:
                    continue
                previous = latest_by_formal.get(model.subject.formal_id)
                if previous is None or (item[3], item[0], item[1]) > (
                    previous[3],
                    previous[0],
                    previous[1],
                ):
                    latest_by_formal[model.subject.formal_id] = item
            matches = sorted(latest_by_formal.values(), key=lambda item: item[1])
            snapshot_states = sorted(
                {
                    str(model.quality.get("snapshot_verification"))
                    for _, _, model, _ in matches
                    if model.quality.get("snapshot_verification") is not None
                }
            )
            rate_policies = sorted(
                {
                    str(
                        model.engine.get("execution_config", {})
                        .get("execution", {})
                        .get("profile", {})
                        .get("historical_rate_policy")
                    )
                    for _, _, model, _ in matches
                    if model.engine.get("execution_config", {})
                    .get("execution", {})
                    .get("profile", {})
                    .get("historical_rate_policy")
                    is not None
                }
            )
            effective_dates = sorted(
                {
                    str(
                        model.engine.get("execution_config", {})
                        .get("execution", {})
                        .get("profile", {})
                        .get("commission_margin", {})
                        .get("effective_at")
                    )
                    for _, _, model, _ in matches
                    if model.engine.get("execution_config", {})
                    .get("execution", {})
                    .get("profile", {})
                    .get("commission_margin", {})
                    .get("effective_at")
                    is not None
                }
            )
            links.append(
                {
                    "workspace_run_id": run_id,
                    "status": "rendered" if matches else "not_rendered",
                    "report_ids": [report_id for _, report_id, _, _ in matches],
                    "snapshot_verification": _one_or_ambiguous(snapshot_states),
                    "historical_rate_policy": _one_or_ambiguous(rate_policies),
                    "execution_profile_effective_at": _one_or_ambiguous(effective_dates),
                }
            )
        return links


def _one_or_ambiguous(values: list[str]) -> str | None:
    if not values:
        return None
    return values[0] if len(values) == 1 else "ambiguous"
