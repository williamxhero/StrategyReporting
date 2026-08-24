from __future__ import annotations

import re

import pandas as pd
from nautilus_trader.analysis import create_tearsheet_from_stats

from strategy_reporting.errors import RenderError
from strategy_reporting.html.security import add_native_csp, validate_html
from strategy_reporting.models import FormalRunReport, ReportOptions
from strategy_reporting.renderers.interface import RenderedArtifact

UUID_ID = re.compile(r'(["\'])\w{8}-\w{4}-\w{4}-\w{4}-\w{12}\1')


class NativeTearsheetRenderer:
    def render(self, model: FormalRunReport, options: ReportOptions) -> RenderedArtifact:
        index = pd.DatetimeIndex([item.timestamp for item in model.performance.portfolio_returns])
        values = [float(item.value) for item in model.performance.portfolio_returns]
        returns = pd.Series(values, index=index, dtype="float64", name="returns")
        try:
            raw = create_tearsheet_from_stats(
                stats_pnls=model.performance.stats_pnls,
                stats_returns=model.performance.stats_returns,
                stats_general=model.performance.stats_general,
                returns=returns,
                output_path=None,
                title="NautilusTrader Backtest Results",
                run_info=model.run_info,
                account_info=model.account_info,
                engine=None,
            )
        except Exception as exc:
            raise RenderError("nautilus_tearsheet_failed", str(exc)) from exc
        if not isinstance(raw, str):
            raise RenderError("nautilus_tearsheet_failed", "offline API returned no HTML")
        normalized = add_native_csp(_normalize_plotly_identity(raw))
        content = normalized.encode("utf-8")
        validate_html(content, maximum_bytes=options.max_html_bytes, native_plotly=True)
        return RenderedArtifact(
            name="nautilus-tearsheet.html",
            media_type="text/html; charset=utf-8",
            logical_role="native-tearsheet-html",
            record_schema=None,
            content=content,
        )


def _normalize_plotly_identity(value: str) -> str:
    if not re.match(r"\s*<!doctype html>", value, flags=re.IGNORECASE):
        value = "<!doctype html>" + value
    matches = list(dict.fromkeys(match.group(0)[1:-1] for match in UUID_ID.finditer(value)))
    for index, identifier in enumerate(matches):
        value = value.replace(identifier, f"nautilus-tearsheet-{index}")
    return value
