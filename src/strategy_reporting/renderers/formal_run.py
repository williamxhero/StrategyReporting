from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape
from markupsafe import Markup

from strategy_reporting.canonical import canonical_json
from strategy_reporting.errors import RenderError
from strategy_reporting.html.assets import stylesheet
from strategy_reporting.html.security import stylesheet_csp, validate_html
from strategy_reporting.models import FormalRunReport, ReportModel, ReportOptions, TablePreview
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle
from strategy_reporting.renderers.nautilus_tearsheet import NativeTearsheetRenderer

METRIC_LABELS = {
    "PnL (total)": "累计净收益",
    "PnL% (total)": "累计净收益率",
    "Win Rate": "盈利交易占比",
    "Expectancy": "单笔期望",
    "Avg Winner": "平均盈利",
    "Avg Loser": "平均亏损",
    "Max Winner": "最大单笔盈利",
    "Max Loser": "最大单笔亏损",
    "Min Winner": "最小单笔盈利",
    "Min Loser": "最小单笔亏损",
    "Average (Return)": "平均周期收益",
    "Average Win (Return)": "平均正收益",
    "Average Loss (Return)": "平均负收益",
    "Profit Factor": "盈亏因子",
    "Returns Volatility (252 days)": "年化波动率 (252 日)",
    "Risk Return Ratio": "风险收益比",
    "Sharpe Ratio (252 days)": "夏普比率 (252 日)",
    "Sortino Ratio (252 days)": "索提诺比率 (252 日)",
    "Long Ratio": "多头占比",
}
PERCENT_METRICS = {
    "Win Rate",
    "Average (Return)",
    "Average Win (Return)",
    "Average Loss (Return)",
    "Returns Volatility (252 days)",
    "Long Ratio",
}
PERCENT_ALREADY_METRICS = {"PnL% (total)"}
EXECUTION_LABELS = {
    "orders": "订单",
    "fills": "成交",
    "rejects": "拒单",
    "positions": "仓位事件",
    "account_curve": "账户快照",
    "fees": "费用",
    "decisions": "策略决策",
}
PARAMETER_LABELS = {
    "candidate_profile": "候选配置",
    "initial_equity": "初始权益",
    "compound_rate": "复利仓位",
    "band_std_dev": "布林带标准差",
    "m30_close_minutes": "30 分钟收盘分钟",
    "long_entries_enabled": "允许做多",
    "short_entries_enabled": "允许做空",
    "loss_multiplier_enabled": "连续亏损缩放",
    "portfolio_risk_mode": "组合风险模式",
    "fixed_entry_risk_stop_enabled": "固定入场风险止损",
    "protective_stop_resets_failure_streak_enabled": "保护止损重置失败计数",
    "losing_breakout_bandwidth_invalidation_enabled": "亏损突破带宽失效",
    "trailing_activation_ratio": "移动止盈启动比例",
    "trailing_drawdown_ratio": "移动止盈回撤比例",
    "trailing_drawdown_cap": "移动止盈回撤上限",
    "signal_uses_adjustment_offset": "信号使用复权偏移",
}


class FormalRunRenderer:
    renderer_version = "formal-html.v2+template.4+csp.2+nautilus.1.231.0"

    def __init__(self) -> None:
        self.native = NativeTearsheetRenderer()

    def render(self, model: ReportModel, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, FormalRunReport):
            raise RenderError("renderer_model_mismatch", "formal renderer requires FormalRunReport")
        model_bytes = canonical_json(model.model_dump(mode="json"))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        template = _environment().get_template("formal.html.j2")
        css = stylesheet()
        html = template.render(
            model=model,
            theme=options.theme,
            stylesheet=Markup(css),
            csp=stylesheet_csp(css),
            view=_formal_view(model),
        ).encode("utf-8")
        validate_html(html, maximum_bytes=options.max_html_bytes)
        native = self.native.render(model, options)
        return RenderedBundle(
            model=model,
            model_bytes=model_bytes,
            renderer_version=self.renderer_version,
            options=options,
            artifacts=(
                RenderedArtifact(
                    name="formal-run-report.json",
                    media_type="application/json",
                    logical_role="report-model",
                    record_schema=model.schema_id,
                    content=model_bytes,
                ),
                RenderedArtifact(
                    name="formal-run-report.html",
                    media_type="text/html; charset=utf-8",
                    logical_role="report-html",
                    record_schema=None,
                    content=html,
                ),
                native,
            ),
        )


def _environment() -> Environment:
    root = files("strategy_reporting.html").joinpath("templates")
    from jinja2 import FileSystemLoader

    return Environment(
        loader=FileSystemLoader(str(root)),
        autoescape=select_autoescape(enabled_extensions=("html", "j2"), default=True),
        undefined=StrictUndefined,
    )


def _formal_view(model: FormalRunReport) -> dict[str, Any]:
    snapshot = _mapping(model.market.get("snapshot"))
    query = _mapping(snapshot.get("query"))
    instruments = [str(item) for item in _list(query.get("instruments"))]
    analytics = _mapping(model.analytics)
    portfolio_path = _mapping(analytics.get("portfolio_path"))
    activity = _mapping(analytics.get("activity"))
    execution_config = _mapping(model.engine.get("execution_config"))
    futures_execution = _mapping(execution_config.get("execution"))
    contracts = _mapping(futures_execution.get("contracts"))
    pnl_currency, pnl_metrics = _pnl_metrics(model.performance.stats_pnls)
    max_drawdown = portfolio_path.get("max_drawdown")
    current_scope = (
        f"{len(instruments)} 个连续合约 · {query.get('start', '—')} 至 {query.get('end', '—')}"
    )
    metric_rows = _metric_rows(pnl_metrics, model.performance.stats_returns)
    general_rows = _metric_rows(model.performance.stats_general)
    fee_totals = _mapping(activity.get("fee_totals"))
    headline = [
        {
            "label": "期末权益",
            "value": _format_account_value(_account_value(model.account_info, "Ending balance")),
            "note": "Nautilus 原生账户口径",
        },
        {
            "label": "累计净收益率",
            "value": _format_metric("PnL% (total)", pnl_metrics.get("PnL% (total)")),
            "note": f"{pnl_currency or '账户币种'} · 原生 PnL",
        },
        {
            "label": "夏普比率",
            "value": _format_metric(
                "Sharpe Ratio (252 days)",
                model.performance.stats_returns.get("Sharpe Ratio (252 days)"),
            ),
            "note": "252 日 · Nautilus 原生统计",
        },
        {
            "label": "最大回撤",
            "value": _percent(max_drawdown),
            "note": "由原生组合收益序列复合得到",
        },
        {
            "label": "订单 / 成交",
            "value": (
                f"{model.execution['orders'].total_rows:,} / "
                f"{model.execution['fills'].total_rows:,}"
            ),
            "note": f"拒单 {model.execution['rejects'].total_rows:,} 笔",
        },
    ]
    execution_sections = [
        {
            "name": name,
            "label": EXECUTION_LABELS[name],
            "total_rows": preview.total_rows,
            "shown_rows": min(len(preview.rows), 16),
            "omitted_count": max(preview.total_rows - min(len(preview.rows), 16), 0),
            "columns": _table_columns(preview),
            "rows": _table_rows(preview),
        }
        for name, preview in model.execution.items()
        if name in EXECUTION_LABELS
    ]
    execution_sections.sort(key=lambda item: list(EXECUTION_LABELS).index(str(item["name"])))
    return {
        "display_title": _display_title(model),
        "scope": current_scope,
        "instruments": instruments,
        "headline": headline,
        "portfolio_available": portfolio_path.get("status") == "available",
        "equity_svg": _line_chart(portfolio_path, "cumulative_return", "组合累计收益曲线"),
        "drawdown_svg": _line_chart(portfolio_path, "drawdown", "组合回撤曲线", fill=True),
        "path_start": _first_timestamp(portfolio_path),
        "path_end": _last_timestamp(portfolio_path),
        "source_point_count": portfolio_path.get("source_point_count", 0),
        "max_drawdown": _percent(max_drawdown),
        "drawdown_peak": portfolio_path.get("drawdown_peak") or "—",
        "drawdown_trough": portfolio_path.get("drawdown_trough") or "—",
        "drawdown_recovery": portfolio_path.get("drawdown_recovery") or "尚未恢复 / 无法判定",
        "annual_returns": [
            {
                "year": item.get("year"),
                "value": _percent(item.get("return")),
                "tone": _tone(item.get("return")),
            }
            for item in _object_list(portfolio_path.get("annual_returns"))
        ],
        "metric_rows": metric_rows,
        "general_rows": general_rows,
        "activity_rows": [
            {**item, "fee_display": _currency_values(_mapping(item.get("fees")))}
            for item in _object_list(activity.get("instruments"))
        ],
        "decision_reasons": _object_list(activity.get("decision_reasons")),
        "commission_tags": _object_list(activity.get("commission_tags")),
        "fee_totals": _currency_values(fee_totals) or "—",
        "execution_semantics": [
            ("成本归类", model.execution_performance.get("futures_cost_semantics", "—")),
            ("滑点模型", model.execution_performance.get("futures_slippage_semantics", "—")),
            ("滑点参数", _unit(futures_execution.get("slippage_ticks"), " ticks")),
            ("初始资金", _money(futures_execution.get("initial_cash_cny"), "CNY")),
            ("合约配置", f"{len(contracts) or len(instruments)} 个品种"),
            ("数据读取", model.execution_performance.get("read_method", "—")),
        ],
        "contract_costs": _contract_cost_rows(contracts),
        "parameters": [
            {
                "name": PARAMETER_LABELS.get(str(key), str(key)),
                "value": _human_value(value),
            }
            for key, value in model.strategy.get("parameters", {}).items()
        ],
        "coverage": [
            ("研究区间", f"{query.get('start', '—')} — {query.get('end', '—')}"),
            ("频率 / 复权", f"{query.get('frequency', '—')} / {query.get('adjustment', '—')}"),
            ("品种数量", f"{len(instruments)}"),
            ("快照可信策略", snapshot.get("trust_policy", "—")),
            ("快照状态", model.market.get("verification_status", "—")),
            ("MarketHub 数据版本", _data_version(snapshot)),
            (
                "合约目录版本",
                model.execution_performance.get("futures_contract_catalog_dataset_version", "—"),
            ),
            ("原生事件流", _integer(model.execution_performance.get("streamed_native_events"))),
        ],
        "availability": [
            {
                "name": key,
                "status": value.get("status", "unknown"),
                "reason": value.get("reason"),
            }
            for key, value in model.performance.availability.items()
        ],
        "quality": [
            ("Artifact 完整性", model.quality.get("artifact_verification", "—")),
            ("Evidence index", model.quality.get("evidence_index_verification", "—")),
            ("Reporting input", model.quality.get("reporting_input_schema", "—")),
            ("源文件数", model.quality.get("source_file_count", "—")),
        ],
        "legacy_comparison": [
            ("研究范围", "单品种 · 半年 · 结构验证", current_scope),
            (
                "指标快照",
                "累计收益率 148.47% · Sharpe 0.78 (旧范围 / 旧口径)",
                "累计收益率 "
                + _format_metric("PnL% (total)", pnl_metrics.get("PnL% (total)"))
                + " · Sharpe "
                + _format_metric(
                    "Sharpe Ratio (252 days)",
                    model.performance.stats_returns.get("Sharpe Ratio (252 days)"),
                ),
            ),
            (
                "回答的问题",
                "链路与执行结构是否可运行",
                "长期多品种组合在冻结数据与真实成本语义下如何表现",
            ),
            (
                "绩效证据",
                "旧指标不沿用; 也不用于推断本次收益",
                "Nautilus 原生组合指标、原生每日收益、订单与成交证据",
            ),
            (
                "可审计性",
                "局部窗口结构证据",
                "run / attempt / snapshot / MarketHub 数据与目录版本全部绑定",
            ),
        ],
        "execution_sections": execution_sections,
        "run_rows": _object_rows(model.run_info),
        "account_rows": _object_rows(model.account_info),
        "artifacts": [
            {
                "name": item.name,
                "role": item.logical_role,
                "schema": item.record_schema or "—",
                "sha256": item.sha256,
                "uri": item.uri,
                "bytes": f"{item.bytes:,}",
            }
            for item in model.source_artifacts
        ],
    }


def _display_title(model: FormalRunReport) -> str:
    strategy_id = str(model.strategy.get("strategy_id") or "策略")
    profile = str(_mapping(model.strategy.get("parameters")).get("candidate_profile") or "")
    name = strategy_id.removeprefix("futures.").replace("-", " ").title()
    if "/" in profile:
        primary, secondary = profile.split("/", 1)
        if primary.lower() in name.lower():
            return f"{name} / {secondary}"
    return f"{name} / {profile}" if profile and profile.lower() not in name.lower() else name


def _pnl_metrics(value: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    for key, item in value.items():
        if isinstance(item, Mapping):
            return str(key), {str(name): raw for name, raw in item.items()}
    return "", {str(key): item for key, item in value.items()}


def _metric_rows(*groups: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group in groups:
        for name, value in group.items():
            rows.append(
                {
                    "name": METRIC_LABELS.get(str(name), str(name)),
                    "value": _format_metric(str(name), value),
                    "source": "Nautilus 原生统计",
                }
            )
    return rows


def _format_metric(name: str, value: Any) -> str:
    if value is None:
        return "—"
    if name in PERCENT_ALREADY_METRICS:
        return _decimal_display(value, suffix="%", digits=2)
    if name in PERCENT_METRICS:
        return _percent(value)
    if name in {
        "Profit Factor",
        "Risk Return Ratio",
        "Sharpe Ratio (252 days)",
        "Sortino Ratio (252 days)",
    }:
        return _decimal_display(value, digits=3)
    return _decimal_display(value, digits=2)


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_display(value: Any, *, suffix: str = "", digits: int = 2) -> str:
    number = _decimal(value)
    if number is None:
        return str(value) if value is not None else "—"
    return f"{number:,.{digits}f}{suffix}"


def _percent(value: Any) -> str:
    number = _decimal(value)
    return f"{number * 100:,.2f}%" if number is not None else "—"


def _tone(value: Any) -> str:
    number = _decimal(value)
    if number is None or number == 0:
        return "flat"
    return "positive" if number > 0 else "negative"


def _line_chart(
    portfolio_path: Mapping[str, Any], key: str, label: str, *, fill: bool = False
) -> Markup:
    points = _object_list(portfolio_path.get("chart_points"))
    values = [_decimal(item.get(key)) for item in points]
    if not points or any(value is None for value in values):
        return Markup('<div class="chart-empty">原生收益序列不可用</div>')
    numeric = [value for value in values if value is not None]
    minimum = min(numeric)
    maximum = max(numeric)
    if minimum == maximum:
        minimum -= Decimal("0.01")
        maximum += Decimal("0.01")
    width, height, pad_x, pad_y = Decimal(1000), Decimal(280), Decimal(18), Decimal(20)
    plot_width = width - pad_x * 2
    plot_height = height - pad_y * 2
    coordinates: list[tuple[Decimal, Decimal]] = []
    for index, value in enumerate(numeric):
        x = pad_x + plot_width * Decimal(index) / Decimal(max(len(numeric) - 1, 1))
        y = pad_y + plot_height * (maximum - value) / (maximum - minimum)
        coordinates.append((x, y))
    path = " ".join(
        ("M" if index == 0 else "L") + f"{x:.2f},{y:.2f}"
        for index, (x, y) in enumerate(coordinates)
    )
    area = ""
    if fill:
        first_x, _ = coordinates[0]
        last_x, _ = coordinates[-1]
        area = (
            f'<path class="chart-area" d="{path} L{last_x:.2f},{height - pad_y:.2f} '
            f'L{first_x:.2f},{height - pad_y:.2f} Z"/>'
        )
    grid = "".join(
        f'<line class="chart-grid" x1="{pad_x}" x2="{width - pad_x}" y1="{y}" y2="{y}"/>'
        for y in (pad_y, height / 2, height - pad_y)
    )
    return Markup(
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{label}">{grid}{area}<path class="chart-line" d="{path}"/></svg>'
    )


def _first_timestamp(portfolio_path: Mapping[str, Any]) -> str:
    points = _object_list(portfolio_path.get("chart_points"))
    return str(points[0].get("timestamp")) if points else "—"


def _last_timestamp(portfolio_path: Mapping[str, Any]) -> str:
    points = _object_list(portfolio_path.get("chart_points"))
    return str(points[-1].get("timestamp")) if points else "—"


def _account_value(account: Mapping[str, Any], prefix: str) -> str | None:
    return next((str(value) for key, value in account.items() if str(key).startswith(prefix)), None)


def _format_account_value(value: str | None) -> str:
    if not value:
        return "—"
    parts = value.split(maxsplit=1)
    number = _decimal(parts[0])
    if number is None:
        return value
    suffix = f" {parts[1]}" if len(parts) == 2 else ""
    return f"{number:,.2f}{suffix}"


def _data_version(snapshot: Mapping[str, Any]) -> str:
    source = _mapping(snapshot.get("source"))
    return str(source.get("data_revision") or "未声明")


def _currency_values(values: Mapping[str, Any]) -> str:
    return " · ".join(f"{_decimal_display(value)} {currency}" for currency, value in values.items())


def _contract_cost_rows(contracts: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = []
    for instrument, raw in sorted(contracts.items()):
        contract = _mapping(raw)
        commission = _mapping(contract.get("commission"))
        rows.append(
            {
                "instrument": str(instrument),
                "exchange": str(contract.get("exchange") or "—"),
                "multiplier": str(contract.get("multiplier") or "—"),
                "margin": _percent(contract.get("margin_init")),
                "open": _commission(_mapping(commission.get("open"))),
                "close": _commission(_mapping(commission.get("close"))),
                "close_today": _commission(_mapping(commission.get("close_today"))),
            }
        )
    return rows


def _commission(value: Mapping[str, Any]) -> str:
    per_contract = _decimal(value.get("per_contract")) or Decimal(0)
    rate = _decimal(value.get("rate")) or Decimal(0)
    parts = []
    if per_contract:
        parts.append(f"{per_contract.normalize()} 元/手")
    if rate:
        parts.append(f"{rate.normalize()} 乘成交额")
    return " + ".join(parts) or "0"


def _money(value: Any, currency: str) -> str:
    number = _decimal(value)
    return f"{number:,.2f} {currency}" if number is not None else "—"


def _unit(value: Any, suffix: str) -> str:
    return f"{value}{suffix}" if value is not None else "—"


def _human_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _integer(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value) if value is not None else "—"


def _table_columns(preview: TablePreview) -> list[str]:
    return [str(key) for key in preview.rows[0]] if preview.rows else []


def _table_rows(preview: TablePreview) -> list[list[str]]:
    columns = _table_columns(preview)
    return [
        [_cell_value(column, row.get(column)) for column in columns] for row in preview.rows[:16]
    ]


def _cell_value(key: str, value: Any) -> str:
    if key in {"ts_event", "submit_ts_event"}:
        try:
            return datetime.fromtimestamp(int(value) / 1_000_000_000, tz=UTC).strftime(
                "%Y-%m-%d %H:%M"
            )
        except (TypeError, ValueError, OSError):
            return str(value)
    if isinstance(value, Mapping):
        reason = value.get("reason")
        target = value.get("target_contracts")
        if reason is not None:
            return f"{reason} · 目标 {target}" if target is not None else str(reason)
        return f"{len(value)} 个字段"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if len(value) <= 4 else f"{len(value)} 项"
    return str(value) if value is not None else "—"


def _object_rows(value: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [(str(key), _human_value(item)) for key, item in value.items()]


def _mapping(value: Any) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _object_list(value: Any) -> list[dict[str, Any]]:
    return [_mapping(item) for item in _list(value) if isinstance(item, Mapping)]
