from __future__ import annotations

from typing import Any

from markupsafe import Markup

from strategy_reporting.canonical import canonical_json
from strategy_reporting.errors import RenderError
from strategy_reporting.html.assets import research_stylesheet
from strategy_reporting.html.security import stylesheet_csp, validate_html
from strategy_reporting.models import ReportModel, ReportOptions, ResearchStudyReport
from strategy_reporting.renderers.formal_run import _environment
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle

_GATE_LABELS = {
    "completed-formal-run": "正式运行完成",
    "single-formal-backend": "单一正式后端",
    "native-fill-evidence-present": "原生成交证据存在",
    "frozen-execution-profile": "执行配置已冻结",
    "frozen-snapshot": "市场快照已冻结",
}
_OPERATOR_LABELS = {
    "eq": "=",
    "ne": "≠",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
}


class ResearchStudyRenderer:
    renderer_version = "research-html.v1+template.3.3+csp.1"

    def render(self, model: ReportModel, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, ResearchStudyReport):
            raise RenderError(
                "renderer_model_mismatch", "research renderer requires ResearchStudyReport"
            )
        model_bytes = canonical_json(model.model_dump(mode="json"))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        css = research_stylesheet()
        html = (
            _environment()
            .get_template("research.html.j2")
            .render(
                model=model,
                theme=options.theme,
                stylesheet=Markup(css),
                csp=stylesheet_csp(css),
                view=_research_view(model),
            )
            .encode("utf-8")
        )
        validate_html(html, maximum_bytes=options.max_html_bytes)
        return RenderedBundle(
            model=model,
            model_bytes=model_bytes,
            renderer_version=self.renderer_version,
            options=options,
            artifacts=(
                RenderedArtifact(
                    name="research-study-report.json",
                    media_type="application/json",
                    logical_role="report-model",
                    record_schema=model.schema_id,
                    content=model_bytes,
                ),
                RenderedArtifact(
                    name="research-study-report.html",
                    media_type="text/html; charset=utf-8",
                    logical_role="report-html",
                    record_schema=None,
                    content=html,
                ),
            ),
        )


def _research_view(model: ResearchStudyReport) -> dict[str, Any]:
    gate_views: list[dict[str, Any]] = []
    for item in model.gate_results:
        result = _mapping(item.get("result"))
        gate = str(result.get("gate") or "unknown")
        gate_views.append(
            {
                "name": gate,
                "label": _GATE_LABELS.get(gate, gate),
                "status": str(result.get("status") or "unknown"),
                "metric": str(result.get("metric") or "unknown"),
                "observed": _display(result.get("observed")),
                "operator": _OPERATOR_LABELS.get(
                    str(result.get("operator")), str(result.get("operator") or "?")
                ),
                "threshold": _display(result.get("threshold")),
                "record_id": str(_mapping(item.get("source")).get("record_id") or "unknown"),
            }
        )

    trial_views: list[dict[str, Any]] = []
    for trial in model.trials:
        snapshot = _mapping(trial.get("snapshot_window"))
        formal_legs = _list_of_mappings(trial.get("formal_legs"))
        trial_views.append(
            {
                "sequence": trial.get("sequence"),
                "trial_id": trial.get("trial_id"),
                "workspace_run_id": trial.get("workspace_run_id"),
                "status": trial.get("run_status"),
                "outcome": trial.get("result_outcome"),
                "topology": trial.get("topology"),
                "snapshot": snapshot,
                "parameters": _mapping(trial.get("parameters")),
                "formal_legs": [_formal_leg_view(leg) for leg in formal_legs],
            }
        )

    links: list[dict[str, Any]] = []
    for raw_link in model.related_formal_reports:
        link = _mapping(raw_link)
        links.append(
            {
                **link,
                "report_ids": [str(item) for item in _list(link.get("report_ids"))],
            }
        )

    evidence_views: list[dict[str, Any]] = []
    for raw_evidence in model.evidence:
        evidence = _mapping(raw_evidence)
        evidence_views.append(
            {
                "record_id": _mapping(evidence.get("source")).get("record_id"),
                "artifacts_verified": evidence.get("artifacts_verified"),
                "artifact_uris": [str(item) for item in _list(evidence.get("artifact_uris"))],
                "workspace_run_ids": [
                    str(item) for item in _list(evidence.get("workspace_run_ids"))
                ],
            }
        )

    protocol = _mapping(model.protocol)
    decision = _mapping(model.final_decision)
    pass_count = sum(item["status"] == "pass" for item in gate_views)
    snapshot_states = sorted(
        {
            str(item.get("snapshot_verification"))
            for item in links
            if item.get("snapshot_verification") is not None
        }
    )
    rate_policies = sorted(
        {
            str(leg.get("historical_rate_policy"))
            for trial in trial_views
            for leg in _list_of_mappings(trial.get("formal_legs"))
            if leg.get("historical_rate_policy") is not None
        }
    )
    effective_dates = sorted(
        {
            str(leg.get("effective_at"))
            for trial in trial_views
            for leg in _list_of_mappings(trial.get("formal_legs"))
            if leg.get("effective_at") is not None
        }
    )
    validation = _mapping(model.validation)
    validation_view = None
    if validation:
        validation_view = {
            "evidence_id": validation.get("evidence_id"),
            "complete": validation.get("complete"),
            "denominator": validation.get("denominator"),
            "covered_cells": validation.get("covered_cells"),
            "status_counts": sorted(_mapping(validation.get("status_counts")).items()),
            "gaps": _list_of_mappings(validation.get("gaps")),
            "metric_groups": [
                {
                    "metric": group.get("metric"),
                    "group_id": group.get("group_id"),
                    "comparability": _mapping(group.get("comparability")),
                    "cells": _list_of_mappings(group.get("cells")),
                    "values_micros": _list(group.get("values_micros")),
                }
                for group in _list_of_mappings(validation.get("metric_groups"))
            ],
            "aggregation_policy": validation.get("aggregation_policy"),
        }
    return {
        "strategy_id": model.strategy_package.get("strategy_id") or "unknown",
        "revision": model.strategy_package.get("revision") or "—",
        "protocol_id": protocol.get("protocol_id") or "unknown",
        "topology": protocol.get("topology") or "unknown",
        "decision_status": decision.get("status") or "unknown",
        "pass_count": pass_count,
        "gate_count": len(gate_views),
        "gate_views": gate_views,
        "trial_views": trial_views,
        "links": links,
        "evidence_views": evidence_views,
        "artifact_count": sum(len(_list(item.get("artifact_uris"))) for item in evidence_views),
        "source_record_count": len(model.source_record_ids),
        "snapshot_states": snapshot_states,
        "rate_policies": rate_policies,
        "effective_dates": effective_dates,
        "research_metrics": [
            (str(key), _display(value)) for key, value in sorted(model.research_metrics.items())
        ],
        "validation": validation_view,
        "availability": (
            ("探索阶段", model.discovery),
            ("稳健性", model.robustness),
            ("敏感性", model.sensitivity),
            ("容量", model.capacity),
        ),
    }


def _formal_leg_view(leg: dict[str, Any]) -> dict[str, Any]:
    config = _mapping(leg.get("config"))
    execution = _mapping(config.get("execution"))
    metrics = _mapping(leg.get("metrics"))
    contracts = _mapping(execution.get("contracts"))
    profile = _mapping(execution.get("profile"))
    commission = _mapping(profile.get("commission_margin"))
    return {
        "formal_id": leg.get("formal_id"),
        "adapter": leg.get("adapter"),
        "contract_count": len(contracts),
        "contracts": sorted(contracts),
        "native_fill_rows": metrics.get("native_fill_report_rows"),
        "execution_profile_hash": metrics.get("futures_execution_profile_hash"),
        "historical_rate_policy": profile.get("historical_rate_policy"),
        "effective_at": commission.get("effective_at"),
        "slippage_ticks": execution.get("slippage_ticks"),
        "initial_cash_cny": execution.get("initial_cash_cny"),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    return [item for item in _list(value) if isinstance(item, dict)]


def _display(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.6g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)
