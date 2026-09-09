from __future__ import annotations

import html
import json

from markupsafe import Markup

from strategy_reporting.canonical import canonical_json
from strategy_reporting.contracts.campaign_report import CampaignReport
from strategy_reporting.errors import RenderError
from strategy_reporting.html.assets import campaign_stylesheet
from strategy_reporting.html.security import stylesheet_csp, validate_html
from strategy_reporting.models import ReportModel, ReportOptions
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle


class CampaignRenderer:
    renderer_version = "campaign-html.v1+cards.2+csp.1"

    def render(self, model: ReportModel | CampaignReport, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, CampaignReport):
            raise RenderError(
                "renderer_model_mismatch", "campaign renderer requires CampaignReport"
            )
        model_bytes = canonical_json(model.model_dump(mode="json"))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        css = campaign_stylesheet()
        rendered = _document(model, options.detail_row_limit, css).encode("utf-8")
        validate_html(rendered, maximum_bytes=options.max_html_bytes)
        return RenderedBundle(
            model=model,
            model_bytes=model_bytes,
            renderer_version=self.renderer_version,
            options=options,
            artifacts=(
                RenderedArtifact(
                    name="campaign-report.json",
                    media_type="application/json",
                    logical_role="report-model",
                    record_schema=model.schema_id,
                    content=model_bytes,
                ),
                RenderedArtifact(
                    name="campaign-report.html",
                    media_type="text/html; charset=utf-8",
                    logical_role="report-html",
                    record_schema=None,
                    content=rendered,
                ),
            ),
        )


def _document(model: CampaignReport, limit: int, css: str) -> str:
    objective = model.objective
    lanes = "".join(_lane(item.model_dump(mode="json"), limit) for item in model.evidence_lanes)
    fact_source = {
        "record_id": model.source_publication["record_id"],
        "record_type": model.source_publication["record_type"],
    }
    sections = "".join(
        _section(item.model_dump(mode="json"), limit, fact_source) for item in model.sections
    )
    constraints = "".join(f"<li>{html.escape(item)}</li>" for item in objective.constraints)
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in objective.assumptions)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{stylesheet_csp(css)}">'
        f"<title>{html.escape(model.title)}</title><style>{Markup(css)}</style></head><body><main>"
        f'<header class="hero"><div class="eyebrow">AI Research Campaign · Offline report</div>'
        f'<h1>{html.escape(model.title)}</h1><span class="state">{model.report_state}</span>'
        f'<div class="source">campaign {html.escape(model.subject.campaign_id)} · source '
        f"{html.escape(model.subject.source_id)}</div></header>"
        f'<section class="objective"><h2>Frozen question and scope</h2><p>{html.escape(objective.question)}</p>'
        f"<h3>Constraints</h3><ul>{constraints}</ul><h3>Assumptions</h3><ul>{assumptions}</ul></section>"
        f'<h2>Evidence lanes</h2><div class="lanes">{lanes}</div>'
        f'<h2>Campaign record</h2><div class="sections">{sections}</div>'
        "</main></body></html>"
    )


def _lane(raw: dict[str, object], limit: int) -> str:
    evidence_class = str(raw["evidence_class"])
    entries = _list_of_objects(raw["entries"])
    visible = entries[:limit]
    omitted = len(entries) - len(visible)
    rows = "".join(_entry(item) for item in visible)
    return (
        f'<section class="lane" data-evidence-class="{html.escape(evidence_class)}">'
        f"<h3>{html.escape(evidence_class.title())}</h3>{rows or '<p class="reason">No published facts.</p>'}"
        f'<p class="omitted" data-omitted="{omitted}">{omitted} omitted</p></section>'
    )


def _entry(raw: object) -> str:
    value = _object(raw)
    source = _object(value["source"])
    return (
        '<article class="entry">'
        f'<div class="source">{html.escape(str(value["section"]))} · '
        f"{html.escape(str(source['record_type']))} · {html.escape(str(source['record_id']))}</div>"
        f"<pre>{_json(value['data'])}</pre>"
        f"<pre>{_json(value['quantitative_values'])}</pre></article>"
    )


def _section(raw: dict[str, object], limit: int, fact_source: dict[str, str]) -> str:
    availability = _object(raw["availability"])
    items = _list_of_objects(raw["items"])
    facts = _object(raw["facts"])
    visible = items[:limit]
    omitted = len(items) - len(visible)
    rows = "".join(
        _entry(
            {
                "section": raw["name"],
                "source": item["source"],
                "data": item["summary"],
                "quantitative_values": [],
            }
        )
        for item in visible
    )
    facts_source = (
        '<div class="source">section facts · '
        f"{html.escape(fact_source['record_type'])} · "
        f"{html.escape(fact_source['record_id'])}</div>"
        if facts
        else ""
    )
    return (
        f'<section class="section" data-section="{html.escape(str(raw["name"]))}">'
        f"<h3>{html.escape(str(raw['name']))}</h3>"
        f'<div class="availability">{html.escape(str(availability["status"]))}</div>'
        f'<p class="reason">{html.escape(str(availability.get("reason") or ""))}</p>'
        f"{rows}{facts_source}<pre>{_json(facts)}</pre>"
        f'<p class="omitted" data-omitted="{omitted}">{omitted} omitted</p></section>'
    )


def _json(value: object) -> str:
    return html.escape(
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RenderError("campaign_render_model_invalid", "campaign view value must be an object")
    return value


def _list_of_objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise RenderError("campaign_render_model_invalid", "campaign view value must be an array")
    return [_object(item) for item in value]
