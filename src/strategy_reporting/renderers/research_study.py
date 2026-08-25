from __future__ import annotations

from markupsafe import Markup

from strategy_reporting.canonical import canonical_json
from strategy_reporting.errors import RenderError
from strategy_reporting.html.assets import stylesheet
from strategy_reporting.html.presentation import research_view
from strategy_reporting.html.security import stylesheet_csp, validate_html
from strategy_reporting.models import ReportModel, ReportOptions, ResearchStudyReport
from strategy_reporting.renderers.formal_run import _environment
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle


class ResearchStudyRenderer:
    renderer_version = "research-html.v1+template.6+csp.1"

    def render(self, model: ReportModel, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, ResearchStudyReport):
            raise RenderError(
                "renderer_model_mismatch", "research renderer requires ResearchStudyReport"
            )
        model_bytes = canonical_json(model.model_dump(mode="json"))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        css = stylesheet()
        html = (
            _environment()
            .get_template("research.html.j2")
            .render(
                model=model,
                theme=options.theme,
                stylesheet=Markup(css),
                csp=stylesheet_csp(css),
                view=research_view(model),
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
