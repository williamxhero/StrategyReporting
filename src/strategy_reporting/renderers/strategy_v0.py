from __future__ import annotations

import json
from html import escape

from strategy_reporting.canonical import canonical_json
from strategy_reporting.contracts.campaign_report import CampaignReport
from strategy_reporting.errors import RenderError
from strategy_reporting.models import ReportModel, ReportOptions, StrategyReportV0
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle


class StrategyReportV0Renderer:
    renderer_version = "strategy-report-v0.html.v1"

    def render(self, model: ReportModel | CampaignReport, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, StrategyReportV0):
            raise RenderError(
                "renderer_model_mismatch", "StrategyReport-v0 requires StrategyReportV0"
            )
        model_bytes = canonical_json(model.model_dump(mode="json"))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        html = self._html(model)
        if len(html) > options.max_html_bytes:
            raise RenderError("html_too_large", f"html is {len(html)} bytes")
        return RenderedBundle(
            model=model,
            model_bytes=model_bytes,
            renderer_version=self.renderer_version,
            options=options,
            artifacts=(
                RenderedArtifact(
                    name="strategy-report-v0.json",
                    media_type="application/json",
                    logical_role="report-model",
                    record_schema=model.schema_id,
                    content=model_bytes,
                ),
                RenderedArtifact(
                    name="strategy-report-v0.html",
                    media_type="text/html; charset=utf-8",
                    logical_role="report-html",
                    record_schema=None,
                    content=html,
                ),
            ),
        )

    @staticmethod
    def _html(model: StrategyReportV0) -> bytes:
        sections = []
        for section in model.sections:
            section_id = escape(str(section.get("section_id", "unknown")))
            status = escape(str(section.get("status", "not_evaluated")))
            reason = section.get("reason")
            body = (
                f'<p class="status">{escape(str(reason))}</p>'
                if status == "not_evaluated" and reason
                else f"<pre>{escape(json.dumps(section.get('facts', {}), ensure_ascii=False, sort_keys=True))}</pre>"
            )
            sections.append(f"<section><h2>{section_id}</h2><p>{status}</p>{body}</section>")
        limitation_html = "".join(f"<li>{escape(item)}</li>" for item in model.limitations)
        html = f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{escape(model.title)}</title>'
        html += "<style>body{font-family:system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#17202a}header{border-bottom:1px solid #ccd6dd;margin-bottom:24px}.meta{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}section{border-top:1px solid #d8dee4;padding:16px 0}pre{white-space:pre-wrap;background:#f6f8fa;padding:12px}.status{color:#8a3b12}</style></head><body>"
        html += f'<header><h1>{escape(model.title)}</h1><div class="meta"><p>判定:{escape(model.decision)}</p><p>证据等级:{escape(model.evidence_level)}</p><p>适用范围:{escape(json.dumps(model.applicability, ensure_ascii=False, sort_keys=True))}</p></div></header>'
        html += (
            f"<h2>限制</h2><ul>{limitation_html or '<li>无已发布限制</li>'}</ul>{''.join(sections)}"
        )
        html += "<footer>重渲染不等于通过新检验。</footer></body></html>"
        return html.encode("utf-8")
