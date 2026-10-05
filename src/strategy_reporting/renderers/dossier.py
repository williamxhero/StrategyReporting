"""Deterministic, bounded HTML projection of the evidence-backed dossier model."""

from __future__ import annotations

from html import escape

from strategy_reporting.canonical import canonical_json
from strategy_reporting.contracts.dossier_report import DossierReport
from strategy_reporting.errors import RenderError
from strategy_reporting.models import ReportOptions
from strategy_reporting.renderers.interface import RenderedArtifact, RenderedBundle

_SECTION_LABELS = {
    "source": "研究来源",
    "experiment_matrix": "实验矩阵",
    "lineage": "证据谱系",
    "metrics": "交易与风险指标",
    "audits": "执行审计",
    "comparisons": "对照比较",
    "attributions": "归因矩阵",
    "quarantine": "隔离的历史证据",
    "holdout_lock": "前向 Holdout",
    "limitations": "限制与下一步",
}


class DossierRenderer:
    """Render only persisted owner facts; never query Workspace or calculate metrics."""

    renderer_version = "dossier.html.v1"

    def render(self, model: DossierReport, options: ReportOptions) -> RenderedBundle:
        if not isinstance(model, DossierReport):
            raise RenderError("renderer_model_mismatch", "DossierRenderer requires DossierReport")
        model_bytes = canonical_json(model.model_dump(mode="json"))
        if len(model_bytes) > options.max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_bytes)} bytes")
        html = self._html(model)
        if len(html) > options.max_html_bytes:
            raise RenderError("html_too_large", f"html is {len(html)} bytes")
        return RenderedBundle(
            model=model,  # type: ignore[arg-type]
            model_bytes=model_bytes,
            renderer_version=self.renderer_version,
            options=options,
            artifacts=(
                RenderedArtifact(
                    name="dossier-report.json",
                    media_type="application/json",
                    logical_role="report-model",
                    record_schema=model.schema_id,
                    content=model_bytes,
                ),
                RenderedArtifact(
                    name="dossier-report.html",
                    media_type="text/html; charset=utf-8",
                    logical_role="report-html",
                    record_schema=None,
                    content=html,
                ),
            ),
        )

    @staticmethod
    def _html(model: DossierReport) -> bytes:
        navigation: list[str] = []
        sections: list[str] = []
        for section in model.sections:
            name = escape(section.name)
            title = escape(_SECTION_LABELS[section.name])
            navigation.append(f'<a href="#{name}">{title}</a>')
            records: list[str] = []
            for evidence in section.evidence:
                rows: list[str] = []
                for fact in evidence.facts:
                    value = "未评估" if fact.status == "not_evaluated" else str(fact.value)
                    citations = "<br>".join(
                        f"{escape(source.record.record_id)}{escape(source.selector)}"
                        for source in fact.sources
                    )
                    rows.append(
                        "<tr>"
                        f"<td>{escape(fact.path)}</td>"
                        f"<td>{escape(value)}</td>"
                        f"<td>{escape(fact.status)}</td>"
                        f"<td>{escape(fact.derivation)}</td>"
                        f"<td class=mono>{citations}</td>"
                        "</tr>"
                    )
                record_id = escape(evidence.source.record_id)
                records.append(
                    f"<details><summary>{escape(evidence.source.record_type)} "
                    f"<span class=mono>{record_id}</span></summary>"
                    '<div class=table-scroll><table><thead><tr><th>字段</th><th>值</th>'
                    "<th>状态</th><th>派生口径</th><th>来源</th></tr></thead>"
                    f"<tbody>{''.join(rows)}</tbody></table></div></details>"
                )
            reason = f"<p>{escape(section.reason)}</p>" if section.reason else ""
            sections.append(
                f'<section id="{name}"><h2>{title}</h2>'
                f'<p class=status>{escape(section.status)}</p>{reason}'
                f"{''.join(records)}</section>"
            )
        document = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(model.title)}</title>"
            "<style>"
            "body{margin:0;background:#f9f9f7;color:#17202a;font:15px/1.5 system-ui;}"
            "main{max-width:1280px;margin:auto;padding:24px;}"
            "header{border-bottom:1px solid #d8dee4;padding-bottom:20px;}"
            ".banner{background:#fff0d3;border-left:4px solid #b77400;padding:12px;}"
            "nav{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0;}"
            "a{color:#195a9c;text-decoration:none;}"
            "section{border-top:1px solid #d8dee4;padding:20px 0;}"
            "details{margin:8px 0;background:#fff;border:1px solid #d8dee4;padding:12px;}"
            "summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere;}"
            ".table-scroll{overflow:auto;}table{border-collapse:collapse;width:100%;}"
            "th,td{text-align:left;vertical-align:top;border-bottom:1px solid #d8dee4;"
            "padding:8px;overflow-wrap:anywhere;}th{white-space:nowrap;}"
            ".mono{font-family:ui-monospace,monospace;font-size:12px;}"
            ".status{color:#5f6b76;font-weight:600;}"
            "@media(prefers-color-scheme:dark){body{background:#111;color:#eee;}"
            "details{background:#1c1c1c;border-color:#444;}a{color:#8ec1fa;}"
            ".banner{background:#31240f;}section,header,td,th{border-color:#444;}}"
            "@media(max-width:600px){main{padding:16px;}nav{gap:8px;}}"
            "</style></head><body><main>"
            f"<header><h1>{escape(model.title)}</h1>"
            f'<p class="banner">{escape(model.banner)}</p>'
            "<p>这是已发布证据的只读投影。展开各条记录可核查字段、状态和来源,"
            "重渲染不等于通过新检验。</p></header>"
            f"<nav>{''.join(navigation)}</nav>{''.join(sections)}"
            "<footer>candidate_evidence · 不作盈利、因果或生产批准推断。</footer>"
            "</main></body></html>"
        )
        return document.encode("utf-8")
