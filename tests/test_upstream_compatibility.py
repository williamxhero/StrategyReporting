from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from conftest import FakeWorkspace, add_formal_run

from strategy_reporting.adapters import (
    ApexResearchPublicationAdapter,
    WorkspaceAdapter,
    WorkspaceFormalRunAdapter,
)
from strategy_reporting.application import ReportingApplication
from strategy_reporting.canonical import bytes_sha256, canonical_json
from strategy_reporting.models import ReportOptions

ROOT = Path(__file__).parents[2]


def _load_support(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


@pytest.mark.connected
def test_pushed_apex_source_publication_maps_without_private_state(tmp_path: Path) -> None:
    apex = ROOT / "apex-research"
    sys.path.insert(0, str(apex / "src"))
    try:
        support = _load_support("apex_upstream_support", apex / "tests" / "conftest.py")
        from apex_research.canonical import canonical_sha256 as apex_canonical_sha256
        from apex_research.models import TrialTopology
        from apex_research.state import StudyStateStore

        topology = TrialTopology.FORMAL_ONLY
        workspace = support.FakeWorkspace(support.result_value(topology))
        runtime = support.FakeRuntime(workspace)
        application = support.TestResearchApplication(
            StudyStateStore(tmp_path / "state"),
            tmp_path / "workspace",
            workspace,
            runtime,
            governance=support.FakeGovernance(),
        )
        protocol = support.write_json(
            tmp_path / "protocol.json",
            support.protocol_value(topology, "formal.formal-1.metrics.score"),
        )
        request = support.write_json(tmp_path / "request.json", support.request_value(topology))
        study_id = application.create_study(protocol)
        application.run_study(study_id, request)
        application.report(study_id)
        model = ApexResearchPublicationAdapter(WorkspaceAdapter(workspace)).build_model(
            study_id, ReportOptions()
        )
        assert model.subject.study_id == study_id
        assert model.protocol["gate_specs"][0]["operator"] == "gte"
        assert model.source_publication["record_id"] == model.source_publication["source_id"]

        source_publication = next(
            item
            for item in workspace.records.values()
            if item["record_type"] == "apex-research.study-report-source.v1"
        )
        zero_payload = deepcopy(source_publication["payload"])
        zero_payload["decision"]["research_metrics"]["regression.zero"] = 0.0
        zero_payload["research_metrics"]["regression.zero"] = 0.0
        zero_payload["decision"]["decision_id"] = apex_canonical_sha256(
            {key: value for key, value in zero_payload["decision"].items() if key != "decision_id"}
        )
        zero_payload["source_id"] = apex_canonical_sha256(
            {
                key: value
                for key, value in zero_payload.items()
                if key != "source_id"
                and not (key in {"validation", "statistical"} and value is None)
            }
        )
        workspace.publish_record(
            {
                "record_id": zero_payload["source_id"],
                "record_type": "apex-research.study-report-source.v1",
                "payload": zero_payload,
                "lineage": source_publication["lineage"],
            },
            artifacts=[],
        )
        zero_model = ApexResearchPublicationAdapter(WorkspaceAdapter(workspace)).build_model(
            study_id,
            ReportOptions(decision_id=zero_payload["decision"]["decision_id"]),
        )
        assert zero_model.research_metrics["regression.zero"] == 0.0
    finally:
        sys.path.remove(str(apex / "src"))


@pytest.mark.connected
def test_pushed_runtime_reporting_input_renders_from_artifact_only() -> None:
    runtime = ROOT / "quant-runtime"
    script = """
import json,sys
sys.path.insert(0, 'tests')
from test_nautilus_reporting_input import Analyzer, Account, result
import pandas as pd
from quant_runtime.adapters.formal.nautilus.reporting_input import extract_reporting_input
value = extract_reporting_input(
    result=result(),
    analyzer=Analyzer(pd.Series([0.01], index=[pd.Timestamp('2026-01-02', tz='UTC')])),
    account=Account(),
)
print(json.dumps(value, allow_nan=False, sort_keys=True))
"""
    completed = subprocess.run(
        [str(runtime / ".venv" / "Scripts" / "python.exe"), "-c", script],
        cwd=runtime,
        check=True,
        capture_output=True,
        text=True,
    )
    native = json.loads(completed.stdout)
    try:
        workspace = FakeWorkspace()
        run_id = add_formal_run(workspace)
        refs = workspace.runs[run_id]["result"]["artifacts"]
        normalized = next(item for item in refs if item["name"].endswith("normalized_output.json"))
        retained = [
            item
            for item in refs
            if not item["name"].endswith(
                ("native_statistics.json", "normalized_output.json", "evidence_index.json")
            )
        ]
        native_bytes = canonical_json(native)
        native_ref = workspace.add_artifact(
            native_bytes,
            name="formal/primary/native_statistics.json",
            logical_role="engine-native-evidence",
            record_schema="quant-runtime.nautilus-reporting-input.v1",
        )
        normalized_value = json.loads(workspace.contents[normalized["sha256"]])
        normalized_value["native_statistics"] = native
        normalized_value["metrics"] = {"runtime_metric": "1.25"}
        normalized_value["normalized_output_hash"] = bytes_sha256(
            canonical_json(
                {
                    key: value
                    for key, value in normalized_value.items()
                    if key not in {"metrics", "normalized_output_hash"}
                }
            )
        )
        workspace.runs[run_id]["result"]["formal"]["primary"]["metrics"][
            "normalized_output_hash"
        ] = normalized_value["normalized_output_hash"]
        normalized_bytes = canonical_json(normalized_value)
        normalized_ref = workspace.add_artifact(
            normalized_bytes,
            name="formal/primary/normalized_output.json",
            logical_role="engine-native-evidence",
        )
        index = {
            "schema": "quant-runtime.native-evidence-index.v1",
            "formal_id": "primary",
            "files": [
                {
                    "path": "native_statistics.json",
                    "sha256": bytes_sha256(native_bytes),
                    "bytes": len(native_bytes),
                },
                {
                    "path": "normalized_output.json",
                    "sha256": bytes_sha256(normalized_bytes),
                    "bytes": len(normalized_bytes),
                },
            ],
        }
        index_ref = workspace.add_artifact(
            canonical_json(index),
            name="formal/primary/evidence_index.json",
            logical_role="engine-native-evidence",
        )
        workspace.runs[run_id]["result"]["artifacts"] = [
            *retained,
            native_ref,
            normalized_ref,
            index_ref,
        ]
        model = WorkspaceFormalRunAdapter(WorkspaceAdapter(workspace)).build_model(
            run_id, ReportOptions()
        )
        assert model.engine["engine_version"] == "1.231.0"
        assert len(model.performance.portfolio_returns) == 1
        assert model.execution_performance == {"runtime_metric": "1.25"}
        application = ReportingApplication(workspace)
        publication = application.render_report("formal-run", run_id, ReportOptions())
        native_html = next(
            item
            for item in publication.envelope.artifacts
            if item.logical_role == "native-tearsheet-html"
        )
        verified = application.verify(publication.envelope.report_id)
        rebuilt = application.rebuild(publication.envelope.report_id)
        assert verified.envelope.report_id == publication.envelope.report_id
        assert rebuilt["rebuilt_content_hashes"]["nautilus-tearsheet.html"] == native_html.sha256
    finally:
        assert "runtime_upstream_support" not in sys.modules
