from __future__ import annotations

import hashlib
import json
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


def scenario_campaign_source(scenario: str) -> dict[str, Any]:
    source = complete_campaign_source()
    source["campaign"]["title"] = f"{scenario.title()} campaign"
    sections = {item["name"]: item for item in source["sections"]}
    if scenario == "complete":
        for section in sections.values():
            section["availability"] = {"status": "available", "reason": None}
            if not section["items"]:
                section["facts"] = {"status": "published"}
    elif scenario == "partial":
        pass
    elif scenario in {"blocked", "unavailable"}:
        status = scenario
        reason = "upstream blocked" if scenario == "blocked" else "owner source unavailable"
        for section in sections.values():
            section["availability"] = {"status": status, "reason": reason}
            section["items"] = []
            section["facts"] = {}
    elif scenario == "failed":
        for section in sections.values():
            section["availability"] = {
                "status": "unavailable",
                "reason": "campaign failed before publication",
            }
            section["items"] = []
            section["facts"] = {}
        sections["failures"] = {
            "name": "failures",
            "availability": {"status": "available", "reason": None},
            "items": [],
            "facts": {"status": "failed", "reason": "formal run failed"},
        }
    elif scenario == "retired":
        sections["qualification"] = {
            "name": "qualification",
            "availability": {"status": "available", "reason": None},
            "items": [],
            "facts": {"maturity": "retired", "currency": "current"},
        }
    elif scenario == "diversity":
        for name, record_type in (
            ("exploration_archive", "apex-research.exploration-archive.v1"),
            ("evidence_archive", "apex-research.evidence-archive.v1"),
        ):
            sections[name] = {
                "name": name,
                "availability": {"status": "available", "reason": None},
                "items": [],
                "facts": {"record_type": record_type, "active_entries": ["niche-a"]},
            }
    elif scenario == "auxiliary":
        sections["auxiliary_evidence"] = {
            "name": "auxiliary_evidence",
            "availability": {"status": "available", "reason": None},
            "items": [],
            "facts": {"evidence_level": "auxiliary", "status": "corroborated"},
        }
    else:
        raise ValueError(f"unknown scenario: {scenario}")
    source["sections"] = [sections[name] for name in SECTION_NAMES]
    body = {key: value for key, value in source.items() if key != "source_id"}
    source["source_id"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return source


def evidence_lane_campaign_source() -> dict[str, Any]:
    source = complete_campaign_source()
    sections = {item["name"]: item for item in source["sections"]}
    references = {
        "formal": {
            "record_id": "run-formal-1",
            "record_type": "quant-research.run-record.v1",
        },
        "empirical": {
            "record_id": "d" * 64,
            "record_type": "apex-research.empirical-result.v1",
        },
        "benchmark": {
            "record_id": "e" * 64,
            "record_type": "apex-research.benchmark-result.v1",
        },
        "auxiliary": {
            "record_id": "f" * 64,
            "record_type": "apex-research.auxiliary-validation.v1",
        },
    }
    sections["packages_and_runs"] = {
        "name": "packages_and_runs",
        "availability": {"status": "available", "reason": None},
        "items": [
            {
                "source": references["formal"],
                "ordinal": 1,
                "summary": {
                    "evidence_level": "formal",
                    "selector": "formal.nautilus.metrics.sharpe",
                    "observed": 1.25,
                },
            }
        ],
        "facts": {},
    }
    sections["exploration_archive"] = {
        "name": "exploration_archive",
        "availability": {"status": "available", "reason": None},
        "items": [],
        "facts": {"evidence_level": "discovery", "entry_count": 9},
    }
    sections["auxiliary_evidence"] = {
        "name": "auxiliary_evidence",
        "availability": {"status": "available", "reason": None},
        "items": [
            {
                "source": references[level],
                "ordinal": ordinal,
                "summary": {
                    "evidence_level": level,
                    "selector": f"{level}.metrics.score",
                    "observed": observed,
                },
            }
            for ordinal, (level, observed) in enumerate(
                (("empirical", 0.71), ("benchmark", 0.63), ("auxiliary", 0.55)), start=1
            )
        ],
        "facts": {},
    }
    sections["qualification"] = {
        "name": "qualification",
        "availability": {"status": "available", "reason": None},
        "items": [],
        "facts": {"qualification_maturity": "research_validated"},
    }
    source["sections"] = [sections[name] for name in SECTION_NAMES]
    source["sources"] = sorted(
        [*source["sources"], *references.values()],
        key=lambda item: (item["record_type"], item["record_id"]),
    )
    source["workspace_runs"] = ["run-formal-1"]
    body = {key: value for key, value in source.items() if key != "source_id"}
    source["source_id"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return source
