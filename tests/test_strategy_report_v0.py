from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

import pytest
from conftest import FakeWorkspace

from strategy_reporting import cli
from strategy_reporting.adapters.strategy_v0 import (
    LEGACY_SOURCE_TYPE,
    V2_SOURCE_TYPE,
    StrategyReportV0Adapter,
)
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.application import ReportingApplication
from strategy_reporting.errors import ContractError
from strategy_reporting.models import ReportOptions
from strategy_reporting.renderers import RendererRegistry

SUBJECT_ID = "b" * 64
LEGACY_SOURCE_ID = "a" * 64
V2_SOURCE_ID = "d" * 64
CONCLUSION_ID = "c" * 64
ASSESSMENT_ID = "e" * 64
PREREQUISITE_ID = "f" * 64
RUNTIME_FACTS_ID = "9" * 64
CONCLUSION_TYPE = "apex-research.research-conclusion.v1"


class Client:
    def __init__(self, *, legacy: bool = True) -> None:
        self.published: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.v2_source_id: str | None = None
        self.records: dict[str, dict[str, Any]] = {
            SUBJECT_ID: self._publication(
                SUBJECT_ID,
                "registration",
                {"schema": "registration", "registration_id": SUBJECT_ID},
            ),
            CONCLUSION_ID: self._publication(
                CONCLUSION_ID,
                CONCLUSION_TYPE,
                {
                    "schema": CONCLUSION_TYPE,
                    "conclusion_id": CONCLUSION_ID,
                    "decision": "supports",
                    "evidence_level": "candidate_evidence",
                    "limitations": [],
                },
            ),
        }
        self.legacy_source = self._legacy_source() if legacy else None

    @staticmethod
    def _publication(record_id: str, record_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": "quant-research.publication.v1",
            "record_id": record_id,
            "record_type": record_type,
            "created_at": "2026-09-23T00:00:00Z",
            "payload": payload,
            "artifacts": [],
            "lineage": [],
        }

    def _legacy_source(self) -> dict[str, Any]:
        return {
            "record_id": LEGACY_SOURCE_ID,
            "record_type": LEGACY_SOURCE_TYPE,
            "payload": {
                "schema": LEGACY_SOURCE_TYPE,
                "source_id": LEGACY_SOURCE_ID,
                "research": {"record_id": SUBJECT_ID, "record_type": "registration"},
                "registration": {"record_id": SUBJECT_ID, "record_type": "registration"},
                "versions": {
                    "strategy": "strategy-v0",
                    "data": "data-v1",
                    "execution": "execution-v1",
                    "protocol": "protocol-v1",
                },
                "constraints": {"scope": "200 instruments"},
                "conclusion": {"record_id": CONCLUSION_ID, "record_type": CONCLUSION_TYPE},
                "sections": [
                    {
                        "section_id": "scope",
                        "status": "available",
                        "facts": {"instruments": 200},
                    },
                    {
                        "section_id": "statistics",
                        "status": "not_evaluated",
                        "reason": "no statistical assessment was published",
                    },
                ],
                "differences": {},
            },
            "artifacts": [],
            "lineage": [],
        }

    def add_v2_source(self) -> str:
        self.records[ASSESSMENT_ID] = self._publication(
            ASSESSMENT_ID,
            "apex-research.protocol-assessment.v1",
            {"schema": "apex-research.protocol-assessment.v1", "assessment_id": ASSESSMENT_ID},
        )
        self.records[PREREQUISITE_ID] = self._publication(
            PREREQUISITE_ID,
            "apex-research.framework-change-prerequisite.v1",
            {
                "schema": "apex-research.framework-change-prerequisite.v1",
                "prerequisite_id": PREREQUISITE_ID,
            },
        )
        self.records[RUNTIME_FACTS_ID] = self._publication(
            RUNTIME_FACTS_ID,
            "apex-research.study-runtime-facts.v1",
            {"schema": "apex-research.study-runtime-facts.v1", "facts_id": RUNTIME_FACTS_ID},
        )
        self.records[V2_SOURCE_ID] = self._publication(
            V2_SOURCE_ID,
            V2_SOURCE_TYPE,
            {
                "schema": V2_SOURCE_TYPE,
                "source_id": V2_SOURCE_ID,
                "research": {"record_id": SUBJECT_ID, "record_type": "registration"},
                "registration": {"record_id": SUBJECT_ID, "record_type": "registration"},
                "versions": {
                    "strategy": "strategy-v1",
                    "data": "data-v2",
                    "execution": "execution-v2",
                    "protocol": "protocol-v2",
                },
                "constraints": {"scope": "declared universe", "h4": "deferred"},
                "assessments": [
                    {
                        "record_id": ASSESSMENT_ID,
                        "record_type": "apex-research.protocol-assessment.v1",
                    }
                ],
                "runtime_facts": [
                    {
                        "record_id": RUNTIME_FACTS_ID,
                        "record_type": "apex-research.study-runtime-facts.v1",
                    }
                ],
                "conclusion": {"record_id": CONCLUSION_ID, "record_type": CONCLUSION_TYPE},
                "conclusion_history": [
                    {"record_id": CONCLUSION_ID, "record_type": CONCLUSION_TYPE}
                ],
                "framework_prerequisites": [
                    {
                        "record_id": PREREQUISITE_ID,
                        "record_type": "apex-research.framework-change-prerequisite.v1",
                    }
                ],
                "differences": {"source": "declared", "metrics": "not inferred"},
                "sections": [
                    {
                        "section_id": "scope",
                        "status": "available",
                        "facts": {"universe": "declared"},
                    },
                    {
                        "section_id": "conclusion-ledger",
                        "status": "available",
                        "facts": {
                            "current": "published conclusion",
                            "history": "published conclusion history",
                            "differences": "source-declared only",
                        },
                    },
                    {
                        "section_id": "statistics",
                        "status": "not_evaluated",
                        "reason": "no statistical assessment was published",
                    },
                ],
            },
        )
        self.records[CONCLUSION_ID]["payload"]["limitations"] = ["H4 remains deferred"]
        self.v2_source_id = V2_SOURCE_ID
        return V2_SOURCE_ID

    def list_records(
        self, *, record_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if record_type == LEGACY_SOURCE_TYPE:
            return ([] if self.legacy_source is None else [self.legacy_source])[:limit]
        if record_type == V2_SOURCE_TYPE and self.v2_source_id is not None:
            return [self.records[self.v2_source_id]][:limit]
        return []

    def publish_record(
        self, record: Mapping[str, Any], *, artifacts: Iterable[Mapping[str, Any]] = ()
    ) -> dict[str, Any]:
        assert not tuple(artifacts)
        self.published.append(dict(record))
        publication = self._publication(
            str(record["record_id"]), str(record["record_type"]), dict(record["payload"])
        )
        publication["artifacts"] = list(record.get("artifacts", []))
        publication["lineage"] = list(record.get("lineage", []))
        self.records[str(record["record_id"])] = publication
        return publication

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        self.get_calls.append(record_id)
        return self.records.get(record_id)


def test_strategy_report_v0_cli_command_carries_explicit_source_identity() -> None:
    parsed = cli.parser().parse_args(
        [
            "render-strategy-v0",
            "--subject-id",
            SUBJECT_ID,
            "--source-id",
            LEGACY_SOURCE_ID,
        ]
    )
    assert parsed.command == "render-strategy-v0"
    assert parsed.subject_id == SUBJECT_ID
    assert parsed.source_id == LEGACY_SOURCE_ID


def test_legacy_v1_strategy_report_remains_deterministic_and_marks_missing_facts() -> None:
    client = Client()
    options = ReportOptions()
    first_model = StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model(SUBJECT_ID, options)
    second_model = StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model(
        SUBJECT_ID, options
    )
    assert first_model.decision == "supports"
    assert first_model.evidence_level == "candidate_evidence"
    assert first_model.source_publication["record_type"] == LEGACY_SOURCE_TYPE
    assert first_model.source_records is None
    assert first_model.source_record_ids == [LEGACY_SOURCE_ID, SUBJECT_ID, CONCLUSION_ID]
    registry = RendererRegistry()
    first = registry.resolve(first_model).render(first_model, options)
    second = registry.resolve(second_model).render(second_model, options)
    assert first.model_bytes == second.model_bytes
    assert first.artifacts[1].content == second.artifacts[1].content
    assert b"not_evaluated" in first.artifacts[1].content
    assert first.artifacts[0].record_schema == "strategy-reporting.strategy-report-v0.v1"


def test_v2_strategy_report_requires_an_explicit_source_id() -> None:
    client = Client(legacy=False)
    client.add_v2_source()

    with pytest.raises(ContractError, match="requires --source-id"):
        StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model(SUBJECT_ID, ReportOptions())

    assert client.get_calls == []


def test_v2_strategy_report_validates_publication_readback() -> None:
    client = Client(legacy=False)
    source_id = client.add_v2_source()
    client.records[source_id]["schema"] = "wrong-publication-schema"

    with pytest.raises(ContractError, match="source publication identity differs"):
        StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model(
            SUBJECT_ID, ReportOptions(source_id=source_id)
        )


def test_v2_strategy_report_validates_every_public_reference() -> None:
    client = Client(legacy=False)
    source_id = client.add_v2_source()
    client.records[ASSESSMENT_ID]["record_type"] = "tampered-type"

    with pytest.raises(ContractError, match="source reference readback differs"):
        StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model(
            SUBJECT_ID, ReportOptions(source_id=source_id)
        )


def test_v2_strategy_report_rejects_reference_payload_schema_mismatch() -> None:
    client = Client(legacy=False)
    source_id = client.add_v2_source()
    client.records[ASSESSMENT_ID]["payload"]["schema"] = "tampered-payload-schema"

    with pytest.raises(ContractError, match="source reference readback differs"):
        StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model(
            SUBJECT_ID, ReportOptions(source_id=source_id)
        )


def test_v2_strategy_report_preserves_source_facts_and_is_deterministic() -> None:
    client = Client(legacy=False)
    source_id = client.add_v2_source()
    options = ReportOptions(source_id=source_id)
    adapter = StrategyReportV0Adapter(WorkspaceAdapter(client))
    first_model = adapter.build_model(SUBJECT_ID, options)
    second_model = adapter.build_model(SUBJECT_ID, options)

    assert first_model.applicability == {"scope": "declared universe", "h4": "deferred"}
    assert first_model.decision == "supports"
    assert first_model.evidence_level == "candidate_evidence"
    assert first_model.limitations == [
        "no statistical assessment was published",
        "H4 remains deferred",
    ]
    assert first_model.sections[1]["facts"] == {
        "current": "published conclusion",
        "history": "published conclusion history",
        "differences": "source-declared only",
    }
    assert first_model.source_records == [
        {
            "record_id": PREREQUISITE_ID,
            "record_type": "apex-research.framework-change-prerequisite.v1",
        },
        {
            "record_id": ASSESSMENT_ID,
            "record_type": "apex-research.protocol-assessment.v1",
        },
        {
            "record_id": CONCLUSION_ID,
            "record_type": CONCLUSION_TYPE,
        },
        {
            "record_id": RUNTIME_FACTS_ID,
            "record_type": "apex-research.study-runtime-facts.v1",
        },
        {"record_id": SUBJECT_ID, "record_type": "registration"},
    ]
    assert first_model.source_record_ids == [
        RUNTIME_FACTS_ID,
        SUBJECT_ID,
        CONCLUSION_ID,
        V2_SOURCE_ID,
        ASSESSMENT_ID,
        PREREQUISITE_ID,
    ]
    registry = RendererRegistry()
    first = registry.resolve(first_model).render(first_model, options)
    second = registry.resolve(second_model).render(second_model, options)
    assert first.model_bytes == second.model_bytes
    assert first.artifacts[1].content == second.artifacts[1].content


def test_v2_strategy_report_publication_lineage_uses_source_record_type() -> None:
    client = Client(legacy=False)
    source_id = client.add_v2_source()
    workspace = FakeWorkspace()
    workspace.records.update(copy.deepcopy(client.records))

    report = ReportingApplication(workspace).render_report(
        "strategy-report-v0", SUBJECT_ID, ReportOptions(source_id=source_id)
    )
    lineage = {
        (item.source_kind, item.source_id, item.relation) for item in report.envelope.lineage
    }

    assert (V2_SOURCE_TYPE, source_id, "derived-from") in lineage
    assert ("registration", SUBJECT_ID, "derived-from") in lineage
    assert (
        "apex-research.protocol-assessment.v1",
        ASSESSMENT_ID,
        "derived-from",
    ) in lineage
    assert (
        "apex-research.framework-change-prerequisite.v1",
        PREREQUISITE_ID,
        "derived-from",
    ) in lineage
    assert (CONCLUSION_TYPE, CONCLUSION_ID, "derived-from") in lineage
    assert (
        "apex-research.study-runtime-facts.v1",
        RUNTIME_FACTS_ID,
        "derived-from",
    ) in lineage
    assert (LEGACY_SOURCE_TYPE, source_id, "derived-from") not in lineage
    assert not any(kind == "apex-report-source-record" for kind, _, _ in lineage)
