from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from strategy_reporting.models import FormalRunReport, ResearchStudyReport


def formal_view(model: FormalRunReport) -> dict[str, Any]:
    """Select published facts for the human report without deriving metrics."""
    snapshot = _mapping(model.market.get("snapshot"))
    query = _mapping(snapshot.get("query"))
    verification = _mapping(snapshot.get("verification"))
    return {
        "strategy_id": str(model.strategy.get("strategy_id") or "unknown"),
        "outcome": _outcome_label(model.subject.outcome),
        "run_id": model.subject.workspace_run_id,
        "attempt_id": model.subject.attempt_id,
        "formal_id": model.subject.formal_id,
        "account": _items(model.account_info),
        "native_metrics": _native_metrics(model),
        "execution_counts": [
            {"label": label, "value": model.execution[name].total_rows}
            for name, label in (
                ("orders", "订单"),
                ("fills", "成交"),
                ("positions", "持仓记录"),
                ("fees", "费用记录"),
            )
        ],
        "market": {
            "instruments": "、".join(str(item) for item in query.get("instruments", [])),
            "start": query.get("start"),
            "end": query.get("end"),
            "frequency": query.get("frequency"),
            "adjustment": query.get("adjustment"),
            "snapshot_id": model.market.get("snapshot_id"),
            "dataset_version": verification.get("dataset_version"),
            "coverage_hash": verification.get("coverage_hash"),
        },
        "cost": [
            {"label": label, "value": model.execution_performance.get(key)}
            for key, label in (
                ("futures_cost_semantics", "费用语义"),
                ("futures_slippage_semantics", "滑点语义"),
            )
            if model.execution_performance.get(key) is not None
        ],
    }


def research_view(model: ResearchStudyReport) -> dict[str, Any]:
    partial = _partial_coverage(model)
    strategy_id = str(model.strategy_package.get("strategy_id") or "unknown")
    return {
        "strategy_id": strategy_id,
        "decision": _decision_label(str(model.final_decision.get("status"))),
        "run_count": len(model.trials),
        "run_ids": [str(item.get("workspace_run_id")) for item in model.trials],
        "partial": partial,
        "gate_results": [_gate_view(item) for item in model.gate_results],
        "availability": [
            {"label": label, "status": item.status, "reason": item.reason}
            for label, item in (
                ("样本外 (OOS)", model.robustness),
                ("稳健性", model.robustness),
                ("参数敏感性", model.sensitivity),
                ("压力测试", model.robustness),
                ("容量", model.capacity),
            )
        ],
        "legacy_candidate": _legacy_candidate(model),
        "is_s000012": strategy_id.endswith("s000012"),
    }


def _native_metrics(model: FormalRunReport) -> list[dict[str, Any]]:
    groups = (
        ("损益", model.performance.stats_pnls),
        ("收益风险", model.performance.stats_returns),
        ("一般统计", model.performance.stats_general),
    )
    rows: list[dict[str, Any]] = []
    for group, values in groups:
        for name, value in _flatten(values):
            rows.append({"group": group, "label": name, "value": value})
    return rows


def _flatten(value: Mapping[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key, item in value.items():
        label = f"{prefix} · {key}" if prefix else str(key)
        if isinstance(item, Mapping):
            rows.extend(_flatten(item, label))
        else:
            rows.append((label, item))
    return rows


def _partial_coverage(model: ResearchStudyReport) -> dict[str, Any] | None:
    if not model.trials:
        return None
    legs = model.trials[-1].get("formal_legs")
    if not isinstance(legs, list) or len(legs) != 1 or not isinstance(legs[0], Mapping):
        return None
    partial = _mapping(_mapping(legs[0].get("config")).get("partial_coverage"))
    if partial.get("classification") != "partial_coverage":
        return None
    query = _mapping(partial.get("accepted_query"))
    universe = _mapping(partial.get("actual_universe"))
    return {
        "classification": "部分覆盖 (partial_coverage)",
        "instruments": "、".join(str(item) for item in query.get("instruments", [])),
        "start": query.get("start"),
        "end": query.get("end"),
        "frequency": query.get("frequency"),
        "total_rows": partial.get("total_actual_rows"),
        "instruments_count": len(universe),
        "open_interest": _open_interest_status(universe),
        "limitations": [_limitation_text(item) for item in partial.get("residual_limitations", [])],
    }


def _legacy_candidate(model: ResearchStudyReport) -> str | None:
    if not model.trials:
        return None
    legs = model.trials[-1].get("formal_legs")
    if not isinstance(legs, list) or len(legs) != 1 or not isinstance(legs[0], Mapping):
        return None
    config = _mapping(legs[0].get("config"))
    profile = _mapping(_mapping(config.get("execution")).get("profile"))
    source_id = str(_mapping(profile.get("commission_margin")).get("source_id") or "")
    match = re.search(r"(?:^|[\\/])(C\d{6})(?:[\\/]|$)", source_id)
    return match.group(1) if match else None


def _open_interest_status(universe: Mapping[str, Any]) -> str | None:
    states = {
        str(_mapping(item).get("open_interest"))
        for item in universe.values()
        if isinstance(item, Mapping)
    }
    if states == {"absent_for_all_rows_not_required_by_s000012"}:
        return "全部缺失; 上游声明本策略不要求持仓量。"
    return None


def _limitation_text(value: Any) -> str:
    raw = str(value)
    if raw.startswith("The original 23-product 2012-01-01..2026-08-11 request"):
        return "原 23 品种、2012-01-01 至 2026-08-11 的请求仍不可用, 且没有重试。"
    if raw.startswith("This result is limited to CF/MA/TA/SA"):
        return "本结果仅覆盖 CF、MA、TA、SA 及已接受窗口, 不能推广为完整 S000012 品种池或历史范围。"
    return raw


def _gate_view(item: Mapping[str, Any]) -> dict[str, Any]:
    result = _mapping(item.get("result"))
    labels = {
        "completed-formal-run": "正式运行已完成",
        "single-formal-backend": "单一正式执行后端",
        "partial-coverage-row-evidence": "部分覆盖行数证据",
        "native-fill-evidence": "原生成交证据",
        "frozen-partial-snapshot": "冻结部分覆盖快照",
        "original-full-range-reproduction": "原完整范围复现",
    }
    return {
        "label": labels.get(str(result.get("gate")), result.get("gate")),
        "status": "通过" if result.get("status") == "pass" else "未通过",
        "failure": result.get("failure"),
    }


def _outcome_label(value: str) -> str:
    return {"completed": "已完成", "rejected": "已拒绝"}.get(value, value)


def _decision_label(value: str) -> str:
    return {"accept": "接受", "reject": "拒绝"}.get(value, value)


def _items(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"label": str(key), "value": item} for key, item in value.items()]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
