from __future__ import annotations

import json

from conftest import FakeWorkspace, add_apex_source

from strategy_reporting.application import ReportingApplication
from strategy_reporting.html.presentation import research_view
from strategy_reporting.models import ReportOptions, ResearchStudyReport


def test_partial_coverage_is_presented_as_limited_evidence() -> None:
    workspace = FakeWorkspace()
    report = ReportingApplication(workspace).render_report(
        "research-study", add_apex_source(workspace), ReportOptions()
    )
    model_ref = next(
        item for item in report.envelope.artifacts if item.logical_role == "report-model"
    )
    model = ResearchStudyReport.model_validate_json(
        workspace.contents[model_ref.sha256], strict=True
    )
    trial = json.loads(json.dumps(model.trials[0]))
    trial["formal_legs"][0]["config"] = {
        "partial_coverage": {
            "classification": "partial_coverage",
            "accepted_query": {
                "instruments": ["CFL0", "MAL0", "TAL0", "SAL0"],
                "start": "2026-06-29",
                "end": "2026-08-09",
                "frequency": "1m",
            },
            "actual_universe": {
                instrument: {"open_interest": "absent_for_all_rows_not_required_by_s000012"}
                for instrument in ("CFL0", "MAL0", "TAL0", "SAL0")
            },
            "total_actual_rows": 41_400,
            "residual_limitations": [
                "The original 23-product 2012-01-01..2026-08-11 request remains unavailable",
                "This result is limited to CF/MA/TA/SA in the accepted window",
            ],
        }
    }
    view = research_view(model.model_copy(update={"trials": [trial]}))

    assert view["decision"] == "接受"
    assert view["partial"] == {
        "classification": "部分覆盖 (partial_coverage)",
        "instruments": "CFL0、MAL0、TAL0、SAL0",
        "start": "2026-06-29",
        "end": "2026-08-09",
        "frequency": "1m",
        "total_rows": 41_400,
        "instruments_count": 4,
        "open_interest": "全部缺失; 上游声明本策略不要求持仓量。",
        "limitations": [
            "原 23 品种、2012-01-01 至 2026-08-11 的请求仍不可用, 且没有重试。",
            "本结果仅覆盖 CF、MA、TA、SA 及已接受窗口, 不能推广为完整 S000012 品种池或历史范围。",
        ],
    }
