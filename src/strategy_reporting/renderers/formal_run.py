from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, StrictUndefined, select_autoescape
from markupsafe import Markup

from strategy_reporting.canonical import canonical_json
from strategy_reporting.errors import RenderError
from strategy_reporting.html.assets import stylesheet
from strategy_reporting.html.presentation import formal_view
from strategy_reporting.html.security import stylesheet_csp, validate_html
from strategy_reporting.models import FormalRunReport, ReportModel, ReportOptions
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle
from strategy_reporting.renderers.nautilus_tearsheet import NativeTearsheetRenderer


class FormalRunRenderer:
    renderer_version = "formal-html.v1+template.5+csp.2+nautilus.1.231.0"

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
            view=formal_view(model),
            labels={
                "orders": "订单",
                "fills": "成交",
                "rejects": "拒单",
                "positions": "持仓",
                "account_curve": "账户曲线",
                "fees": "费用",
                "decisions": "策略决策",
            },
            execution_sections=[
                (name, label, model.execution[name])
                for name, label in (
                    ("orders", "订单"),
                    ("fills", "成交"),
                    ("rejects", "拒单"),
                    ("positions", "持仓"),
                    ("account_curve", "账户曲线"),
                    ("fees", "费用"),
                    ("decisions", "策略决策"),
                )
            ],
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
