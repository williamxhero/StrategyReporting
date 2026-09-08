"""Deterministic escaped rendering for SPEC-032 read models."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from strategy_reporting.canonical import canonical_json
from strategy_reporting.contracts.revalidation import RevalidationReadModel
from strategy_reporting.errors import RenderError
from strategy_reporting.html.security import stylesheet_csp, validate_html


@dataclass(frozen=True, slots=True)
class RevalidationRenderedBundle:
    model_json: bytes
    html: bytes


class RevalidationRenderer:
    renderer_version = "revalidation-html.v1+csp.1"

    def render(
        self,
        model: RevalidationReadModel,
        *,
        max_model_bytes: int = 2_000_000,
        max_html_bytes: int = 12_000_000,
    ) -> RevalidationRenderedBundle:
        if not isinstance(model, RevalidationReadModel):
            raise RenderError(
                "renderer_model_mismatch", "revalidation renderer requires its public read model"
            )
        model_json = canonical_json(model.model_dump(mode="json", by_alias=True))
        if len(model_json) > max_model_bytes:
            raise RenderError("model_too_large", f"model is {len(model_json)} bytes")
        css = (
            "body{font-family:system-ui,sans-serif;margin:2rem;max-width:90rem}"
            "h1{border-bottom:3px solid #222;padding-bottom:.5rem}"
            "section{margin:1.2rem 0}pre{white-space:pre-wrap;background:#f4f1e8;padding:1rem}"
            ".blocked{color:#8b1e1e;font-weight:700}"
        )
        sections = (
            ("maturity-and-currency", {"maturity": model.maturity, "currency": model.currency}),
            ("triggers", model.trigger_observations),
            ("campaign-and-budget", {"campaign": model.campaign, "budget": model.budget}),
            ("stages", model.stages),
            ("decay-and-comparison", {"decays": model.decays, "comparison": model.comparison}),
            ("supersession", model.supersession),
            ("active-and-historical-archive", model.archive),
            ("missing-owner-facts", model.missing_facts),
        )
        body = "".join(
            f"<section><h2>{escape(title)}</h2><pre>"
            f"{escape(canonical_json(value).decode('utf-8'))}</pre></section>"
            for title, value in sections
        )
        status_class = "blocked" if model.read_status == "blocked" else "complete"
        html = (
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{stylesheet_csp(css)}">'
            f"<style>{css}</style><title>Revalidation {escape(model.root.record_id)}</title>"
            f'</head><body><h1>Revalidation evidence</h1><p class="{status_class}">'
            f"{escape(model.read_status)}: {escape(model.reason)}</p>{body}</body></html>"
        ).encode()
        validate_html(html, maximum_bytes=max_html_bytes)
        return RevalidationRenderedBundle(model_json=model_json, html=html)


__all__ = ["RevalidationRenderedBundle", "RevalidationRenderer"]
