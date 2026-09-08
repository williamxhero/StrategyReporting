from __future__ import annotations

from html import escape

from strategy_reporting.canonical import canonical_json
from strategy_reporting.errors import RenderError
from strategy_reporting.html.security import stylesheet_csp, validate_html
from strategy_reporting.models import ReplicationStudyReport, ReportModel, ReportOptions
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle


class ReplicationStudyRenderer:
    renderer_version = "replication-html.v1+csp.1"

    def render(self, model: ReportModel, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, ReplicationStudyReport):
            raise RenderError(
                "renderer_model_mismatch",
                "replication renderer requires ReplicationStudyReport",
            )
        model_bytes = canonical_json(model.model_dump(mode="json", by_alias=True))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        css = (
            "body{font-family:system-ui,sans-serif;margin:2rem;max-width:90rem}"
            "h1{border-bottom:3px solid #222;padding-bottom:.5rem}"
            "section{margin:1.5rem 0}pre{white-space:pre-wrap;background:#f4f1e8;padding:1rem}"
            ".outcome{font-weight:700;font-size:1.4rem}"
        )
        sections = (
            ("source_metrics", model.source_metrics),
            ("legacy_metrics", model.legacy_metrics),
            ("research_assumptions", model.research_assumptions),
            ("comparison_criteria", model.comparison_criteria),
            ("formal_facts", model.formal_facts),
            ("differences", model.differences),
            ("blocking_prerequisites", model.blocking_prerequisites),
        )
        body = "".join(
            f"<section><h2>{name}</h2><pre>{escape(canonical_json(value).decode('utf-8'))}</pre></section>"
            for name, value in sections
        )
        html = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{stylesheet_csp(css)}">'
            f"<style>{css}</style><title>{escape(model.title)}</title></head><body>"
            f'<h1>{escape(model.title)}</h1><p class="outcome">{model.subject.outcome}</p>'
            f"{body}</body></html>"
        ).encode()
        validate_html(html, maximum_bytes=options.max_html_bytes)
        return RenderedBundle(
            model=model,
            model_bytes=model_bytes,
            renderer_version=self.renderer_version,
            options=options,
            artifacts=(
                RenderedArtifact(
                    name="replication-study-report.json",
                    media_type="application/json",
                    logical_role="report-model",
                    record_schema=model.schema_id,
                    content=model_bytes,
                ),
                RenderedArtifact(
                    name="replication-study-report.html",
                    media_type="text/html; charset=utf-8",
                    logical_role="report-html",
                    record_schema=None,
                    content=html,
                ),
            ),
        )
