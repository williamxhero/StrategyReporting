from copy import deepcopy
from typing import Any

import pytest

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.application import ReportingApplication
from strategy_reporting.contracts.genome_coverage import GenomeCoverageSource
from strategy_reporting.errors import ContractError


class Workspace:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.record = {
            "record_id": "source",
            "record_type": "apex-research.genome-report-source.v1",
            "payload": payload,
        }

    def get_record(self, record_id: str) -> dict[str, Any]:
        assert record_id == "source"
        return deepcopy(self.record)


def test_public_application_consumes_exact_comparison_and_unavailable_sections() -> None:
    workspace = Workspace(
        {
            "identities": {"candidate": {"record_id": "c"}, "genome": {"record_id": "g"}},
            "lifecycle": {
                "preparation": "prepared",
                "publication": "published",
                "qualification": "not_evaluated",
            },
            "comparison": {
                "result": "incomparable",
                "semantic_paths": ["rules.filter"],
                "changed_components": ["rules.filter"],
                "verified_unchanged_components": [],
                "coverage": "redacted",
            },
            "research_brief": {},
            "links": [{"record_id": "validation", "record_type": "validation.v1"}],
        }
    )
    model = ReportingApplication(workspace).read_genome_coverage("source")  # type: ignore[arg-type]
    assert model.comparison["result"] == "incomparable"
    assert model.comparison["verified_unchanged_components"] == []
    assert model.availability["research_brief"] == "available"
    assert model.lifecycle["qualification"] == "not_evaluated"
    assert model.links[0].record_id == "validation"


def test_invalid_link_fails_closed_and_unknown_source_type_is_rejected() -> None:
    workspace = Workspace({"links": [{"record_id": "bad"}]})
    with pytest.raises(ContractError):
        __import__(
            "strategy_reporting.adapters.genome_coverage",
            fromlist=["GenomeCoverageReadModelBuilder"],
        ).GenomeCoverageReadModelBuilder(WorkspaceAdapter(workspace)).read(
            GenomeCoverageSource(
                record_id="source", record_type="apex-research.genome-report-source.v1"
            )
        )  # type: ignore[arg-type]
