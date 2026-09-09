from __future__ import annotations

from copy import deepcopy
from typing import Any

from conftest import FakeWorkspace

SECTION_NAMES = (
    "hypotheses",
    "candidates",
    "iterations",
    "quality_gates",
    "packages_and_runs",
    "validation_and_evidence",
    "qualification",
    "failures",
    "budget",
    "exploration_archive",
    "evidence_archive",
    "auxiliary_evidence",
    "limitations",
)
CAMPAIGN_ID = "a" * 64
BRIEF_ID = "b" * 64
HYPOTHESIS_ID = "c" * 64
SOURCE_ID = "0fbcf7af899343235430fdd3c5bbc7c20fb7919eb2539e0acae73dda551752b8"


def complete_campaign_source() -> dict[str, Any]:
    absent_sections = [
        {
            "name": name,
            "availability": {
                "status": "not_evaluated",
                "reason": f"no public {name} owner facts",
            },
            "items": [],
            "facts": {},
        }
        for name in SECTION_NAMES[1:]
    ]
    return {
        "schema": "apex-research.campaign-report-source.v1",
        "source_id": SOURCE_ID,
        "campaign": {
            "source": {
                "record_id": CAMPAIGN_ID,
                "record_type": "apex-research.campaign.v1",
            },
            "brief_id": BRIEF_ID,
            "title": "Frozen campaign",
        },
        "brief": {
            "source": {
                "record_id": BRIEF_ID,
                "record_type": "apex-research.research-brief.v1",
            },
            "question": "Can the candidate survive formal validation?",
            "constraints": ["Nautilus is formal truth"],
            "assumptions": ["Published records are immutable"],
        },
        "sections": [
            {
                "name": "hypotheses",
                "availability": {"status": "available", "reason": None},
                "items": [
                    {
                        "source": {
                            "record_id": HYPOTHESIS_ID,
                            "record_type": "apex-research.hypothesis.v1",
                        },
                        "ordinal": 1,
                        "summary": {
                            "hypothesis_id": HYPOTHESIS_ID,
                            "statement": "Momentum persists after costs.",
                            "status": "active",
                        },
                    }
                ],
                "facts": {},
            },
            *absent_sections,
        ],
        "sources": [
            {
                "record_id": CAMPAIGN_ID,
                "record_type": "apex-research.campaign.v1",
            },
            {
                "record_id": HYPOTHESIS_ID,
                "record_type": "apex-research.hypothesis.v1",
            },
            {
                "record_id": BRIEF_ID,
                "record_type": "apex-research.research-brief.v1",
            },
        ],
        "workspace_runs": [],
        "current_evidence": None,
        "current_qualification": None,
        "record_ordering": "semantic-sequence-then-public-identity",
        "current_selection": "explicit-supersession-and-currency",
        "failure_policy": "include-all-within-bounded-public-graph",
        "reporting_interpretation": "forbidden",
        "runtime_invocation": "forbidden",
    }


def publish_campaign_source(
    workspace: FakeWorkspace, source: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = deepcopy(source or complete_campaign_source())
    for reference in payload["sources"]:
        workspace.records.setdefault(
            reference["record_id"],
            {
                "schema": "quant-research.publication.v1",
                "record_id": reference["record_id"],
                "record_type": reference["record_type"],
                "created_at": "2026-09-09T00:00:00Z",
                "payload": {"schema": reference["record_type"]},
                "artifacts": [],
                "lineage": [],
            },
        )
    publication = {
        "schema": "quant-research.publication.v1",
        "record_id": payload["source_id"],
        "record_type": "apex-research.campaign-report-source.v1",
        "created_at": "2026-09-09T00:01:00Z",
        "payload": payload,
        "artifacts": [],
        "lineage": [
            {
                "source_kind": item["record_type"],
                "source_id": item["record_id"],
                "relation": "supports-campaign-report",
            }
            for item in payload["sources"]
        ],
    }
    workspace.records[payload["source_id"]] = publication
    return publication
