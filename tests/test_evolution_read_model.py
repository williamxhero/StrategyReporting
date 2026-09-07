from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

import pytest

from strategy_reporting import cli
from strategy_reporting.adapters.evolution import EvolutionProgressReadModelBuilder
from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.canonical import canonical_sha256
from strategy_reporting.contracts.evolution import EvolutionIslandRef
from strategy_reporting.errors import ContractError


class FakeWorkspace:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def publish(self, payload: dict[str, Any], identity_field: str, sources=()) -> str:
        value = deepcopy(payload)
        value[identity_field] = canonical_sha256(value)
        record_id = value[identity_field]
        self.records[record_id] = {
            "schema": "quant-research.publication.v1",
            "record_id": record_id,
            "record_type": value["schema"],
            "created_at": "2026-09-07T00:00:00Z",
            "payload": value,
            "artifacts": [],
            "lineage": [
                {
                    "source_kind": record_type,
                    "source_id": source_id,
                    "relation": "evolution-input",
                }
                for record_type, source_id in sources
            ],
        }
        return record_id

    def external(self, record_id: str, record_type: str, **payload: Any) -> None:
        self.records[record_id] = {
            "schema": "quant-research.publication.v1",
            "record_id": record_id,
            "record_type": record_type,
            "created_at": "2026-09-07T00:00:00Z",
            "payload": {"schema": record_type, "status": "committed", **payload},
            "artifacts": [],
            "lineage": [],
        }

    def get_record(self, record_id: str) -> dict[str, Any]:
        return deepcopy(self.records[record_id])

    def list_records(
        self, *, record_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        values = list(self.records.values())
        if record_type is not None:
            values = [item for item in values if item["record_type"] == record_type]
        return deepcopy(values[:limit])

    def query_lineage(
        self,
        *,
        roots,
        direction,
        relations=(),
        record_types=(),
        max_depth=1,
        page_size=100,
        cursor=None,
        snapshot_token=None,
    ) -> dict[str, Any]:
        assert direction == "descendants"
        reached = {item["id"] for item in roots}
        selected: dict[str, dict[str, Any]] = {}
        for _depth in range(max_depth):
            discovered = []
            for record_id, publication in self.records.items():
                if record_id in reached:
                    continue
                if record_types and publication["record_type"] not in record_types:
                    continue
                if any(
                    edge.get("source_id") in reached
                    and (not relations or edge.get("relation") in relations)
                    for edge in publication.get("lineage", [])
                ):
                    discovered.append(record_id)
                    selected[record_id] = publication
            if not discovered:
                break
            reached.update(discovered)
        ordered = [selected[key] for key in sorted(selected)]
        token = canonical_sha256(tuple(sorted(self.records)))
        assert snapshot_token in {None, token}
        start = 0 if cursor is None else int(cursor)
        end = min(start + page_size, len(ordered))
        return {
            "records": deepcopy(ordered[start:end]),
            "next_cursor": None if end == len(ordered) else str(end),
            "snapshot_token": token,
        }


def fixture(workspace: FakeWorkspace) -> tuple[str, str]:
    evolution = "apex-research.evolution.v1"
    exploration = "apex-research.exploration-archive.v1"
    archive_policy_id = "a" * 64
    archive_snapshot_id = "b" * 64
    workspace.external(
        archive_policy_id,
        exploration,
        kind="policy",
        archive_family="exploration",
        archive_label="exploration archive",
        entry_label="discovery leader",
    )
    workspace.external(
        archive_snapshot_id,
        exploration,
        kind="snapshot",
        archive_family="exploration",
        policy={"record_id": archive_policy_id, "record_type": exploration},
        considered_niches=["niche-a", "niche-b"],
        occupied_niches=["niche-a"],
        empty_niches=["niche-b"],
        entries=[{"candidate": {"record_id": "seed-candidate"}}],
        historical_entries=[{"candidate": {"record_id": "seed-candidate"}}],
    )
    policy_id = workspace.publish(
        {
            "schema": evolution,
            "kind": "policy",
            "archive_policy": {
                "record_id": archive_policy_id,
                "record_type": exploration,
            },
            "archive_taxonomy": {"record_id": "taxonomy", "record_type": "taxonomy.v1"},
            "candidate_gate_policy": {"record_id": "gate", "record_type": "gate.v1"},
            "focused_policy": {"record_id": "focused", "record_type": "focused.v1"},
        },
        "policy_id",
    )
    island_id = workspace.publish(
        {
            "schema": evolution,
            "kind": "island",
            "policy": {"record_id": policy_id, "record_type": evolution},
            "archive_snapshot": {
                "record_id": archive_snapshot_id,
                "record_type": exploration,
            },
            "generation": 0,
            "seed_population": [{"candidate": {"record_id": "seed-candidate"}}],
            "rng": {"algorithm": "pcg64", "version": "1", "seed": "fixture"},
        },
        "island_id",
        [(evolution, policy_id), (exploration, archive_snapshot_id)],
    )
    snapshot_id = workspace.publish(
        {
            "schema": evolution,
            "kind": "generation_snapshot",
            "island": {"record_id": island_id, "record_type": evolution},
            "generation": 0,
            "policy": {"record_id": policy_id, "record_type": evolution},
            "archive_snapshot": {
                "record_id": archive_snapshot_id,
                "record_type": exploration,
            },
            "status": "active",
            "population": [{"candidate": {"record_id": "seed-candidate"}}],
            "events": [],
        },
        "snapshot_id",
        [(evolution, island_id)],
    )
    plan_id = workspace.publish(
        {
            "schema": evolution,
            "kind": "generation_plan",
            "island": {"record_id": island_id, "record_type": evolution},
            "predecessor": {"record_id": snapshot_id, "record_type": evolution},
            "generation": 1,
            "intents": [],
        },
        "plan_id",
        [(evolution, island_id), (evolution, snapshot_id)],
    )
    descendants = []
    outcomes = []
    for index, status in enumerate(("archived", "rejected", "incomparable")):
        descendant_id = workspace.publish(
            {
                "schema": evolution,
                "kind": "descendant",
                "plan": {"record_id": plan_id, "record_type": evolution},
                "candidate": {"record_id": f"candidate-{index}"},
                "disposition": "passed" if index < 2 else "rejected",
            },
            "descendant_id",
            [(evolution, plan_id)],
        )
        descendants.append(descendant_id)
        outcome_id = workspace.publish(
            {
                "schema": evolution,
                "kind": "discovery_outcome",
                "plan": {"record_id": plan_id, "record_type": evolution},
                "descendant": {"record_id": descendant_id, "record_type": evolution},
                "candidate": {"record_id": f"candidate-{index}"},
                "status": status,
            },
            "outcome_id",
            [(evolution, plan_id), (evolution, descendant_id)],
        )
        outcomes.append(outcome_id)
    frontier_id = workspace.publish(
        {
            "schema": evolution,
            "kind": "promotion_frontier",
            "plan": {"record_id": plan_id, "record_type": evolution},
            "capacity": 1,
            "outcomes": [{"record_id": item, "record_type": evolution} for item in outcomes],
            "decisions": [
                {
                    "outcome": {"record_id": outcomes[index]},
                    "candidate": {"record_id": f"candidate-{index}"},
                    "disposition": disposition,
                    "observations": [{"criterion": "novelty", "status": "comparable"}],
                    "reason": "frozen owner policy decision",
                }
                for index, disposition in enumerate(("promoted", "held", "incomparable"))
            ],
        },
        "frontier_id",
        [(evolution, plan_id), *((evolution, item) for item in outcomes)],
    )
    formal_id = workspace.publish(
        {
            "schema": evolution,
            "kind": "formal_outcome",
            "frontier": {"record_id": frontier_id, "record_type": evolution},
            "candidate": {"record_id": "candidate-0"},
            "stages": [],
            "evidence_entry": None,
            "attachments": {
                "validation": {"status": "not_evaluated", "source": None},
                "statistical": {"status": "not_evaluated", "source": None},
                "robustness": {"status": "not_evaluated", "source": None},
                "qualification": {"status": "not_evaluated", "source": None},
            },
            "research_validated": "not_evaluated",
            "research_qualified": "not_evaluated",
            "current_evidence_eligibility": "not_evaluated",
            "current_evidence_reason": "SPEC-032 exact currency owner fact unavailable",
        },
        "outcome_id",
        [(evolution, frontier_id)],
    )
    reservation_id = "r" * 64
    workspace.external(reservation_id, "apex-research.action-reservation.v1")
    workspace.publish(
        {
            "schema": evolution,
            "kind": "lifecycle_event",
            "island": {"record_id": island_id, "record_type": evolution},
            "policy": {"record_id": policy_id, "record_type": evolution},
            "archive_snapshot": {
                "record_id": archive_snapshot_id,
                "record_type": exploration,
            },
            "generation": 1,
            "action": "budget_limit",
            "candidates": [],
            "owner_refs": [
                {
                    "record_id": reservation_id,
                    "record_type": "apex-research.action-reservation.v1",
                }
            ],
            "reason": "budget reached",
        },
        "event_id",
        [(evolution, island_id), ("apex-research.action-reservation.v1", reservation_id)],
    )
    return island_id, formal_id


def test_evolution_progress_is_complete_honest_and_deterministic() -> None:
    workspace = FakeWorkspace()
    island_id, formal_id = fixture(workspace)
    for index in range(205):
        workspace.publish(
            {
                "schema": "apex-research.evolution.v1",
                "kind": "intent",
                "position": index,
                "cross_island_snapshots": [
                    {
                        "record_id": island_id,
                        "record_type": "apex-research.evolution.v1",
                    }
                ],
            },
            "intent_id",
            [("apex-research.evolution.v1", island_id)],
        )
    builder = EvolutionProgressReadModelBuilder(WorkspaceAdapter(workspace))  # type: ignore[arg-type]

    first = builder.read(EvolutionIslandRef(record_id=island_id))
    second = builder.read(EvolutionIslandRef(record_id=island_id))

    assert first == second
    assert len(first.generated) == 3
    assert len(first.rejected_or_incomparable) == 3
    assert len(first.promoted) == 1
    assert len(first.non_promoted) == 2
    assert first.lifecycle_events[0].action == "budget_limit"
    assert first.budget_owner_facts[0].record_type == "apex-research.action-reservation.v1"
    assert first.exploration_label == "exploration archive — discovery leaders"
    assert first.evidence_label == "evidence archive — historical formal evidence leaders"
    assert first.current_evidence_eligibility == "not_evaluated"
    assert first.current_evidence_reason == "SPEC-032 exact currency owner fact unavailable"
    assert first.formal_outcomes[0].research_qualified == "not_evaluated"
    assert {item.record_id for item in first.records} == {
        record_id
        for record_id, publication in workspace.records.items()
        if publication["record_type"] == "apex-research.evolution.v1"
    }
    assert first.policy.record_id == next(
        item.record_id for item in first.records if item.kind == "policy"
    )
    assert first.seed_candidate_ids == ["seed-candidate"]
    archive_snapshot = next(item for item in first.archive_owner_facts if item.kind == "snapshot")
    assert archive_snapshot.archive_family == "exploration"
    assert archive_snapshot.owner_payload["occupied_niches"] == ["niche-a"]
    assert archive_snapshot.owner_payload["empty_niches"] == ["niche-b"]
    assert first.generated[0].owner_payload["candidate"]["record_id"].startswith("candidate-")

    workspace.records[formal_id]["payload"]["research_qualified"] = "research_qualified"
    with pytest.raises(ContractError):
        builder.read(EvolutionIslandRef(record_id=island_id))
    workspace.records[formal_id]["payload"]["research_qualified"] = "not_evaluated"

    evidence_id = "e" * 64
    workspace.external(
        evidence_id,
        "apex-research.evidence-archive.v1",
        kind="event",
        archive_family="evidence",
    )
    workspace.publish(
        {
            "schema": "apex-research.evolution.v1",
            "kind": "lifecycle_event",
            "island": {"record_id": island_id, "record_type": "apex-research.evolution.v1"},
            "policy": first.policy.model_dump(mode="json"),
            "archive_snapshot": {
                "record_id": evidence_id,
                "record_type": "apex-research.evidence-archive.v1",
            },
            "generation": 1,
            "action": "budget_limit",
            "candidates": [],
            "owner_refs": [],
            "reason": "mixed-family fixture",
        },
        "event_id",
        [("apex-research.evolution.v1", island_id)],
    )
    with pytest.raises(ContractError, match="archive family"):
        builder.read(EvolutionIslandRef(record_id=island_id))


def test_evolution_cli_emits_one_deterministic_workspace_only_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = FakeWorkspace()
    island_id, _ = fixture(workspace)
    monkeypatch.setattr(cli, "production_client", lambda _: workspace)

    assert cli.main(["evolution", "--island-id", island_id]) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert len(first.out.splitlines()) == 1
    payload = json.loads(first.out)
    assert payload["result"]["current_evidence_eligibility"] == "not_evaluated"
    assert payload["result"]["formal_outcomes"][0]["research_qualified"] == "not_evaluated"
    assert cli.main(["evolution", "--island-id", island_id]) == 0
    assert capsys.readouterr().out == first.out


def test_evolution_readback_rejects_unknown_fields_and_inconsistent_lineage() -> None:
    unknown_workspace = FakeWorkspace()
    island_id, _ = fixture(unknown_workspace)
    lifecycle = next(
        item
        for item in unknown_workspace.records.values()
        if item["payload"].get("kind") == "lifecycle_event"
    )
    unknown_payload = deepcopy(lifecycle["payload"])
    unknown_payload.pop("event_id")
    unknown_payload["unexpected"] = "not owner schema"
    unknown_workspace.publish(
        unknown_payload,
        "event_id",
        [("apex-research.evolution.v1", island_id)],
    )
    with pytest.raises(ContractError, match="unknown fields"):
        EvolutionProgressReadModelBuilder(
            WorkspaceAdapter(unknown_workspace)  # type: ignore[arg-type]
        ).read(EvolutionIslandRef(record_id=island_id))

    lineage_workspace = FakeWorkspace()
    island_id, _ = fixture(lineage_workspace)
    plan = next(
        item
        for item in lineage_workspace.records.values()
        if item["payload"].get("kind") == "generation_plan"
    )
    plan["lineage"].append(
        {"source_kind": "unknown.owner.v1", "source_id": "orphan", "relation": "forged"}
    )
    with pytest.raises(ContractError, match="lineage"):
        EvolutionProgressReadModelBuilder(
            WorkspaceAdapter(lineage_workspace)  # type: ignore[arg-type]
        ).read(EvolutionIslandRef(record_id=island_id))


def test_evolution_reporting_identity_transcript_is_deterministic() -> None:
    workspace = FakeWorkspace()
    island_id, _ = fixture(workspace)
    model = EvolutionProgressReadModelBuilder(
        WorkspaceAdapter(workspace)  # type: ignore[arg-type]
    ).read(EvolutionIslandRef(record_id=island_id))
    transcript = {
        "model_sha256": canonical_sha256(model.model_dump(mode="json", by_alias=True)),
        "island_id": island_id,
        "generated": len(model.generated),
        "promoted": len(model.promoted),
        "current_evidence_eligibility": model.current_evidence_eligibility,
    }
    if os.environ.get("SPEC018_IDENTITY_TRANSCRIPT") == "1":
        print(
            "SPEC018_REPORTING_TRANSCRIPT="
            + json.dumps(transcript, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        )
