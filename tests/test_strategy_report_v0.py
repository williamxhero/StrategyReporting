from collections.abc import Iterable, Mapping
from typing import Any

from strategy_reporting.adapters.strategy_v0 import StrategyReportV0Adapter
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.models import ReportOptions
from strategy_reporting.renderers import RendererRegistry


class Client:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self.records: dict[str, dict[str, Any]] = {}

    def list_records(
        self, *, record_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if record_type != "apex-research.study-report-source.v2":
            return []
        return [
            {
                "record_id": "a" * 64,
                "record_type": "apex-research.study-report-source.v2",
                "payload": {
                    "schema": "apex-research.study-report-source.v2",
                    "source_id": "a" * 64,
                    "research": {"record_id": "b" * 64, "record_type": "registration"},
                    "registration": {"record_id": "b" * 64, "record_type": "registration"},
                    "versions": {
                        "strategy": "strategy-v0",
                        "data": "data-v1",
                        "execution": "execution-v1",
                        "protocol": "protocol-v1",
                    },
                    "constraints": {"scope": "200 instruments"},
                    "conclusion": {
                        "record_id": "c" * 64,
                        "record_type": "apex-research.research-conclusion.v1",
                    },
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
        ][:limit]

    def publish_record(
        self, record: Mapping[str, Any], *, artifacts: Iterable[Mapping[str, Any]] = ()
    ) -> dict[str, Any]:
        assert not tuple(artifacts)
        self.published.append(dict(record))
        publication = {
            "schema": "quant-research.publication.v1",
            "record_id": record["record_id"],
            "record_type": record["record_type"],
            "created_at": "2026-09-23T00:00:00Z",
            "payload": record["payload"],
            "artifacts": record.get("artifacts", []),
            "lineage": record.get("lineage", []),
        }
        self.records[str(record["record_id"])] = publication
        return publication

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        return self.records.get(record_id)


def test_strategy_report_v0_is_deterministic_and_marks_missing_facts() -> None:
    client = Client()
    options = ReportOptions()
    first_model = StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model("b" * 64, options)
    second_model = StrategyReportV0Adapter(WorkspaceAdapter(client)).build_model("b" * 64, options)
    registry = RendererRegistry()
    first = registry.resolve(first_model).render(first_model, options)
    second = registry.resolve(second_model).render(second_model, options)
    assert first.model_bytes == second.model_bytes
    assert first.artifacts[1].content == second.artifacts[1].content
    assert b"not_evaluated" in first.artifacts[1].content
    assert first.artifacts[0].record_schema == "strategy-reporting.strategy-report-v0.v1"
