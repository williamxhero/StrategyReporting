from __future__ import annotations

import copy
import json

import pytest
from conftest import FakeWorkspace, add_formal_run

from strategy_reporting.application import ReportingApplication
from strategy_reporting.canonical import bytes_sha256, canonical_json
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import ReportOptions


def test_formal_report_publish_verify_rebuild_is_deterministic(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace)
    app = ReportingApplication(workspace)
    first = app.render_report("formal-run", run_id, ReportOptions())
    second = app.render_report("formal-run", run_id, ReportOptions())
    assert first.envelope.report_id == second.envelope.report_id
    assert first.envelope.generated_at == second.envelope.generated_at
    assert workspace.publish_calls == 1
    assert {item.logical_role for item in first.envelope.artifacts} == {
        "report-model",
        "report-html",
        "native-tearsheet-html",
    }
    assert app.verify(first.envelope.report_id).envelope == first.envelope
    rebuilt = app.rebuild(first.envelope.report_id)
    assert (
        rebuilt["rebuilt_content_hashes"] == first.publication["payload"]["expected_content_hashes"]
    )


def test_formal_descriptor_does_not_duplicate_artifacts_or_lineage(
    workspace: FakeWorkspace,
) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    assert "artifacts" not in report.publication["payload"]
    assert "lineage" not in report.publication["payload"]
    assert [
        item.model_dump(mode="json") for item in report.envelope.artifacts
    ] == report.publication["artifacts"]
    assert [item.model_dump(mode="json") for item in report.envelope.lineage] == report.publication[
        "lineage"
    ]


def test_multi_leg_formal_run_requires_explicit_id(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace, formal_ids=("primary", "challenge"))
    app = ReportingApplication(workspace)
    with pytest.raises(SourceError, match="multiple formal legs"):
        app.render_report("formal-run", run_id, ReportOptions())
    report = app.render_report("formal-run", run_id, ReportOptions(formal_id="challenge"))
    assert report.envelope.identity.subject["formal_id"] == "challenge"


def test_missing_formal_artifact_fails_closed(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace)
    result = workspace.runs[run_id]["result"]
    result["artifacts"] = [
        item for item in result["artifacts"] if not item["name"].endswith("normalized_output.json")
    ]
    with pytest.raises(SourceError, match="expected exactly one"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


@pytest.mark.parametrize("attempt_id", [None, "different-attempt"])
def test_result_attempt_must_exactly_match_current_attempt(
    workspace: FakeWorkspace, attempt_id
) -> None:
    run_id = add_formal_run(workspace)
    workspace.runs[run_id]["result"]["summary"]["attempt_id"] = attempt_id
    with pytest.raises(ContractError, match="result attempt differs"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_duplicate_formal_artifact_name_fails_closed(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace)
    result = workspace.runs[run_id]["result"]
    original = next(
        item for item in result["artifacts"] if item["name"].endswith("native_statistics.json")
    )
    duplicate = {**original, "sha256": "f" * 64, "uri": "workspace-artifact://sha256/" + "f" * 64}
    result["artifacts"].append(duplicate)
    with pytest.raises(SourceError, match="duplicate formal artifact names"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_same_name_and_hash_across_result_and_leg_fails_closed(
    workspace: FakeWorkspace,
) -> None:
    run_id = add_formal_run(workspace)
    result = workspace.runs[run_id]["result"]
    original = next(
        item for item in result["artifacts"] if item["name"].endswith("native_statistics.json")
    )
    result["formal"]["primary"]["artifacts"] = [original]
    with pytest.raises(SourceError, match="duplicate formal artifact names"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_empty_returns_and_empty_execution_are_valid(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace, returns=[])
    report = ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = workspace.contents[model_ref.sha256].decode("utf-8")
    assert '"portfolio_returns":[]' in model
    assert '"reason":"native_series_empty"' in model


def test_single_short_return_series_is_valid(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run",
        add_formal_run(
            workspace,
            returns=[{"timestamp": "2026-01-02T00:00:00Z", "value": "0.01"}],
        ),
        ReportOptions(),
    )
    assert any(item.logical_role == "native-tearsheet-html" for item in report.envelope.artifacts)


def test_detail_rows_are_bounded_with_omitted_count(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run",
        add_formal_run(workspace, order_count=5),
        ReportOptions(detail_row_limit=2),
    )
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = workspace.contents[model_ref.sha256].decode("utf-8")
    assert '"orders":{"omitted_count":3' in model


def test_unordered_or_duplicate_returns_fail_closed(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(
        workspace,
        returns=[
            {"timestamp": "2026-01-03T00:00:00Z", "value": "0.01"},
            {"timestamp": "2026-01-02T00:00:00Z", "value": "0.02"},
        ],
    )
    with pytest.raises(ValueError, match="ordered"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_artifact_tamper_is_detected(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    html_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-html"
    )
    workspace.contents[html_ref.sha256] += b"tamper"
    with pytest.raises(SourceError, match="not verified"):
        ReportingApplication(workspace).verify(report.envelope.report_id)


def test_lineage_tamper_is_detected_from_persisted_model(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    workspace.records[report.envelope.report_id]["lineage"][0]["source_id"] = "tampered"
    with pytest.raises(ContractError, match="persisted report model"):
        ReportingApplication(workspace).verify(report.envelope.report_id)


def test_generated_at_is_not_in_report_identity(workspace: FakeWorkspace) -> None:
    report = ReportingApplication(workspace).render_report(
        "formal-run", add_formal_run(workspace), ReportOptions()
    )
    identity = copy.deepcopy(report.publication["payload"]["identity"])
    assert "generated_at" not in identity
    assert "created_at" not in identity


def test_evidence_index_schema_and_fields_are_exact(workspace: FakeWorkspace) -> None:
    run_id = add_formal_run(workspace)
    _rewrite_index(workspace, run_id, lambda value: value.update(schema="wrong.v1"))
    with pytest.raises(ContractError, match="index schema differs"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())

    workspace = FakeWorkspace()
    run_id = add_formal_run(workspace)
    _rewrite_index(
        workspace,
        run_id,
        lambda value: value["files"][0].update(unexpected=True),
    )
    with pytest.raises(ContractError, match="item fields differ"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_normalized_output_identity_and_native_statistics_are_exact(
    workspace: FakeWorkspace,
) -> None:
    run_id = add_formal_run(workspace)
    _rewrite_normalized(workspace, run_id, lambda value: value.update(schema="wrong.v1"))
    with pytest.raises(ContractError, match="schema differs"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())

    workspace = FakeWorkspace()
    run_id = add_formal_run(workspace)
    _rewrite_normalized(
        workspace,
        run_id,
        lambda value: value["native_statistics"]["summary"].update(Total="different"),
    )
    with pytest.raises(ContractError, match="dedicated artifact"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


@pytest.mark.parametrize("wrong_value", [{}, None, "not-an-array"])
def test_normalized_execution_sections_must_be_arrays(
    workspace: FakeWorkspace, wrong_value
) -> None:
    run_id = add_formal_run(workspace)
    _rewrite_normalized(
        workspace,
        run_id,
        lambda value: value.update(orders=wrong_value),
    )
    with pytest.raises(ContractError, match="orders must be an array"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_large_normalized_output_is_streamed_before_bounded_preview(
    workspace: FakeWorkspace, monkeypatch
) -> None:
    run_id = add_formal_run(workspace, order_count=60_000)
    normalized_ref = next(
        item
        for item in workspace.runs[run_id]["result"]["artifacts"]
        if item["name"].endswith("normalized_output.json")
    )
    assert normalized_ref["bytes"] > ReportOptions().max_model_bytes
    original_read = workspace.read_artifact

    def guarded_read(uri: str):
        if uri == normalized_ref["uri"]:
            raise AssertionError("large normalized source must not use read_artifact")
        return original_read(uri)

    monkeypatch.setattr(workspace, "read_artifact", guarded_read)
    report = ReportingApplication(workspace).render_report(
        "formal-run", run_id, ReportOptions(detail_row_limit=3)
    )
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = json.loads(workspace.contents[model_ref.sha256])
    assert model["execution"]["orders"]["total_rows"] == 60_000
    assert len(model["execution"]["orders"]["rows"]) == 3
    assert model["execution"]["orders"]["omitted_count"] == 59_997


@pytest.mark.parametrize(
    "metric",
    [
        "strategy_package_hash",
        "parameters_hash",
        "snapshot_id",
        "formal_decision_hash",
        "normalized_output_hash",
    ],
)
def test_formal_leg_identity_mirrors_are_exact(workspace: FakeWorkspace, metric: str) -> None:
    run_id = add_formal_run(workspace)
    workspace.runs[run_id]["result"]["formal"]["primary"]["metrics"][metric] = "wrong"
    with pytest.raises(ContractError, match=f"metric {metric} differs"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def test_normalized_semantic_hash_and_strategy_identity_are_exact(
    workspace: FakeWorkspace,
) -> None:
    run_id = add_formal_run(workspace)
    _rewrite_normalized(
        workspace,
        run_id,
        lambda value: value.update(normalized_output_hash="0" * 64),
        recompute_identity=False,
    )
    with pytest.raises(ContractError, match="semantic payload"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())

    workspace = FakeWorkspace()
    run_id = add_formal_run(workspace)
    _rewrite_normalized(
        workspace,
        run_id,
        lambda value: value.update(strategy_spec_hash="0" * 64),
    )
    with pytest.raises(ContractError, match="strategy specification hash"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


@pytest.mark.parametrize("field", ["canonical_input_hash", "data_version", "dataset_version"])
def test_normalized_snapshot_verification_mirrors_are_exact(
    workspace: FakeWorkspace, field: str
) -> None:
    run_id = add_formal_run(workspace)
    _rewrite_normalized(
        workspace,
        run_id,
        lambda value: value.update({field: "wrong"}),
    )
    with pytest.raises(ContractError, match=f"normalized {field} differs"):
        ReportingApplication(workspace).render_report("formal-run", run_id, ReportOptions())


def _rewrite_index(workspace: FakeWorkspace, run_id: str, mutate) -> None:
    result = workspace.runs[run_id]["result"]
    old = next(item for item in result["artifacts"] if item["name"].endswith("evidence_index.json"))
    value = json.loads(workspace.contents[old["sha256"]])
    mutate(value)
    _replace_artifact(workspace, result["artifacts"], old, canonical_json(value))


def _rewrite_normalized(
    workspace: FakeWorkspace, run_id: str, mutate, *, recompute_identity: bool = True
) -> None:
    result = workspace.runs[run_id]["result"]
    normalized = next(
        item for item in result["artifacts"] if item["name"].endswith("normalized_output.json")
    )
    value = json.loads(workspace.contents[normalized["sha256"]])
    mutate(value)
    if recompute_identity:
        value["normalized_output_hash"] = bytes_sha256(
            canonical_json(
                {
                    key: item
                    for key, item in value.items()
                    if key not in {"metrics", "normalized_output_hash"}
                }
            )
        )
        workspace.runs[run_id]["result"]["formal"]["primary"]["metrics"][
            "normalized_output_hash"
        ] = value["normalized_output_hash"]
    content = canonical_json(value)
    replacement = _replace_artifact(workspace, result["artifacts"], normalized, content)
    index_ref = next(
        item for item in result["artifacts"] if item["name"].endswith("evidence_index.json")
    )
    index = json.loads(workspace.contents[index_ref["sha256"]])
    indexed = next(item for item in index["files"] if item["path"] == "normalized_output.json")
    indexed["sha256"] = replacement["sha256"]
    indexed["bytes"] = replacement["bytes"]
    _replace_artifact(workspace, result["artifacts"], index_ref, canonical_json(index))


def _replace_artifact(
    workspace: FakeWorkspace,
    artifacts: list[dict],
    old: dict,
    content: bytes,
) -> dict:
    replacement = workspace.add_artifact(
        content,
        name=old["name"],
        logical_role=old["logical_role"],
        media_type=old["media_type"],
        record_schema=old["record_schema"],
    )
    artifacts[artifacts.index(old)] = replacement
    assert replacement["sha256"] == bytes_sha256(content)
    return replacement
