from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from strategy_reporting.adapters.workspace import WorkspaceAdapter
from strategy_reporting.errors import ContractError, SourceError
from strategy_reporting.models import FormalRunReport, ReportDescriptor, ResearchStudyReport
from strategy_reporting.publishing.workspace import DESCRIPTOR_TYPE, WorkspaceReportPublisher

PORTAL_LIMIT = 10_000


class PortalBuilder:
    def __init__(self, workspace: WorkspaceAdapter) -> None:
        self.workspace = workspace
        self.publisher = WorkspaceReportPublisher(workspace)

    def build(self, output: Path, *, strategy_id: str | None = None) -> dict[str, Any]:
        try:
            records = self.workspace.client.list_records(
                record_type=DESCRIPTOR_TYPE, limit=PORTAL_LIMIT
            )
        except Exception as exc:
            raise SourceError("portal_source_failed", str(exc)) from exc
        if len(records) == PORTAL_LIMIT:
            raise ContractError(
                "portal_truncated", "report list reached the 10,000 record hard cap"
            )
        root = output.resolve()
        root.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        for record in records:
            report_id = str(record.get("record_id"))
            publication = self.publisher.inspect(report_id)
            descriptor = ReportDescriptor.model_validate(record.get("payload"), strict=True)
            model_ref = next(
                (
                    item
                    for item in publication.envelope.artifacts
                    if item.logical_role == "report-model"
                ),
                None,
            )
            if model_ref is None:
                raise ContractError("portal_model_missing", f"report model missing: {report_id}")
            model_bytes = self.workspace.read_verified_bytes(model_ref.model_dump(mode="json"))
            if descriptor.report_kind == "formal-run":
                formal_model = FormalRunReport.model_validate_json(model_bytes, strict=True)
                self.publisher.verify_semantic_descriptor(
                    publication.publication, formal_model, model_bytes
                )
                entry_strategy_id = str(formal_model.strategy.get("strategy_id") or "unknown")
                subject = formal_model.subject.workspace_run_id
                package = _package_identity(
                    formal_model.strategy.get("strategy_package", formal_model.strategy)
                )
                internal = {
                    "_workspace_run_id": formal_model.subject.workspace_run_id,
                    "_parameters": formal_model.strategy.get("parameters", {}),
                    "_snapshot": formal_model.market.get("snapshot", {}),
                    "summary": _formal_summary(formal_model),
                }
            else:
                research_model = ResearchStudyReport.model_validate_json(model_bytes, strict=True)
                self.publisher.verify_semantic_descriptor(
                    publication.publication, research_model, model_bytes
                )
                entry_strategy_id = str(
                    research_model.strategy_package.get("strategy_id") or "unknown"
                )
                subject = research_model.subject.study_id
                package = _package_identity(research_model.strategy_package)
                internal = {
                    "_decision_id": research_model.subject.decision_id,
                    "_trials": research_model.trials,
                    "_discovery": research_model.discovery.model_dump(mode="json"),
                    "summary": {
                        "decision_status": research_model.final_decision.get("status"),
                        "trial_count": len(research_model.trials),
                    },
                }
            if strategy_id and entry_strategy_id != strategy_id:
                continue
            html_refs = [
                item
                for item in publication.envelope.artifacts
                if item.logical_role == "report-html"
            ]
            if len(html_refs) != 1:
                raise ContractError("portal_html_ambiguous", f"report HTML ambiguous: {report_id}")
            destination = self._destination(root, Path("reports") / report_id / "index.html")
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.workspace.materialize_verified(html_refs[0].model_dump(mode="json"), destination)
            entries.append(
                {
                    "report_id": report_id,
                    "report_kind": descriptor.report_kind,
                    "strategy_id": entry_strategy_id,
                    "subject": subject,
                    "title": descriptor.title,
                    "created_at": record.get("created_at"),
                    "href": f"reports/{report_id}/index.html",
                    "lineage": record.get("lineage", []),
                    "_package": package,
                    **internal,
                }
            )
        entries.sort(
            key=lambda item: (
                str(item["strategy_id"]),
                str(item["created_at"]),
                str(item["report_id"]),
            ),
            reverse=True,
        )
        packages = _package_groups(entries)
        public_entries = [_public_entry(item) for item in entries]
        portal_model = {
            "schema": "strategy-reporting.portal-index.v1",
            "strategy_filter": strategy_id,
            "report_count": len(entries),
            "reports": public_entries,
            "packages": packages,
        }
        model_path = self._destination(root, Path("strategy-report-index.json"))
        model_path.write_text(
            json.dumps(
                portal_model,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        index_path = self._destination(root, Path("index.html"))
        index_path.write_text(_portal_html(packages), encoding="utf-8")
        return {
            "ok": True,
            "output": str(root),
            "report_count": len(entries),
            "index": str(index_path),
        }

    @staticmethod
    def _destination(root: Path, relative: Path) -> Path:
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise ContractError("portal_path_escape", "portal destination escapes output root")
        return candidate


def _portal_html(packages: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for package in packages:
        latest = package["latest_research"]
        latest_html = _entry_row(latest) if latest else '<p class="empty">尚无研究报告。</p>'
        history = (
            "".join(_entry_row(item) for item in package["research_history"])
            or '<p class="empty">暂无历史版本。</p>'
        )
        formal = package["formal_runs"]
        formal_sections = "".join(
            f'<div class="report-group"><h4>{label}</h4>'
            f"{''.join(_entry_row(item) for item in formal[key]) or '<p class="empty">暂无。</p>'}</div>"
            for key, label in (
                ("baseline_reference", "基准 / 参考 · Baseline / Reference"),
                ("challenge_window", "挑战窗口 · Challenge window"),
                ("parameter_config_variants", "参数 / 配置变体 · Parameter / config variants"),
            )
        )
        availability = package["discovery_availability"]
        discovery = html.escape(str(availability.get("status", "not_evaluated")))
        reason = html.escape(str(availability.get("reason") or ""))
        package_name = html.escape(str(package["package"]["strategy_id"]))
        revision = html.escape(str(package["package"].get("revision") or "—"))
        sections.append(
            f'<section><header class="package-header"><div><span>Strategy package · r{revision}</span>'
            f'<h2>{package_name}</h2></div><div class="availability">Discovery availability · '
            f"<strong>{discovery}</strong><small>{reason}</small></div></header>"
            f'<div class="portal-column"><h3>正式运行报告 <small>Formal Run Reports</small></h3>'
            f'{formal_sections}</div><div class="portal-column research-column">'
            f"<h3>最新 Research Study Report</h3>{latest_html}"
            f"<h3>历史 Research Study Reports</h3>{history}</div></section>"
        )
    empty = '<p class="portal-empty">当前没有已发布报告。</p>' if not sections else ""
    report_count = sum(
        len(group) for package in packages for group in package["formal_runs"].values()
    ) + sum(
        (1 if package["latest_research"] else 0) + len(package["research_history"])
        for package in packages
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Strategy Reporting Portal</title><style>{_portal_css()}</style></head><body><main><header class="portal-header"><div class="eyebrow">Strategy Reporting · Offline portal</div><h1>策略研究报告库</h1><p>从 Workspace 已验证 publication 构建的离线入口。正式运行、研究结论与历史版本按策略包归档; 不在门户中二次计算任何指标。</p><div class="portal-count"><strong>{report_count}</strong><span>份报告</span><strong>{len(packages)}</strong><span>个策略包</span></div></header>{empty}{"".join(sections)}<footer>确定性构建 · 自包含资源 · Workspace public contract only</footer></main></body></html>"""


def _portal_css() -> str:
    return """
:root{--ink:#15231d;--muted:#68756f;--paper:#f3f1eb;--surface:#fbfaf6;--line:#cfd5cf;--accent:#1d684e;--soft:#e5ebe6}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}main{width:min(1180px,92vw);margin:auto;padding:70px 0}.portal-header{padding:28px 0 64px;border-bottom:2px solid var(--ink)}.eyebrow,.package-header span{color:var(--accent);font-size:12px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}h1{margin:14px 0 18px;font:650 clamp(42px,7vw,82px)/1 Georgia,"Times New Roman","Microsoft YaHei",serif;letter-spacing:-.04em}.portal-header>p{max-width:720px;color:var(--muted)}.portal-count{display:flex;align-items:baseline;gap:8px 18px;margin-top:30px}.portal-count strong{font-size:25px}.portal-count span{color:var(--muted)}section{display:grid;grid-template-columns:minmax(260px,.7fr) 1.3fr 1fr;gap:44px;padding:54px 0;border-bottom:1px solid var(--line)}.package-header h2{margin:8px 0;font-size:24px;overflow-wrap:anywhere}.availability{margin-top:32px;color:var(--muted);font-size:12px}.availability strong,.availability small{display:block;color:var(--ink);overflow-wrap:anywhere}h3{margin:0 0 18px;font-size:16px}h3 small{display:block;color:var(--muted);font-weight:400}.report-group{margin-bottom:30px}.report-group h4{margin:0 0 8px;color:var(--muted);font-size:11px;letter-spacing:.04em}.report-row{display:block;padding:12px 0;border-top:1px solid var(--line);text-decoration:none}.report-row:hover .report-title{color:var(--accent)}.report-title{display:block;font-weight:700;transition:color .15s ease}.report-meta,.report-scope{display:block;color:var(--muted);font-size:11px}.report-scope{margin-top:4px}.empty,.portal-empty{color:var(--muted)}footer{padding-top:30px;color:var(--muted);font-size:12px}@media(max-width:850px){section{grid-template-columns:1fr 1fr}.package-header{grid-column:1/-1}.research-column{border-left:1px solid var(--line);padding-left:24px}}@media(max-width:560px){main{width:calc(100% - 36px);padding-top:38px}section{grid-template-columns:1fr;gap:30px}.package-header{grid-column:auto}.research-column{border-left:0;padding-left:0}.portal-count{flex-wrap:wrap}}
"""


def _formal_summary(model: FormalRunReport) -> dict[str, Any]:
    raw_snapshot = model.market.get("snapshot")
    snapshot: dict[str, Any] = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    raw_query = snapshot.get("query")
    query: dict[str, Any] = raw_query if isinstance(raw_query, dict) else {}
    raw_instruments = query.get("instruments")
    instruments: list[Any] = raw_instruments if isinstance(raw_instruments, list) else []
    return {
        "outcome": model.subject.outcome,
        "instrument_count": len(instruments),
        "start": query.get("start"),
        "end": query.get("end"),
    }


def _package_identity(raw: Any) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    return {
        "strategy_id": str(value.get("strategy_id") or "unknown"),
        "revision": value.get("revision"),
        "package_hash": value.get("package_hash"),
    }


def _package_groups(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        package = entry["_package"]
        key = (
            str(package["strategy_id"]),
            str(package["revision"]),
            str(package["package_hash"]),
        )
        grouped.setdefault(key, []).append(entry)
    result: list[dict[str, Any]] = []
    for key in sorted(grouped):
        items = grouped[key]
        research_candidates = sorted(
            (item for item in items if item["report_kind"] == "research-study"),
            key=_publication_order,
            reverse=True,
        )
        research: list[dict[str, Any]] = []
        seen_decisions: set[tuple[str, str]] = set()
        for item in research_candidates:
            fallback = str(item["report_id"])
            decision_key = (
                str(item.get("subject", fallback)),
                str(item.get("_decision_id", fallback)),
            )
            if decision_key in seen_decisions:
                continue
            seen_decisions.add(decision_key)
            research.append(item)
        formal = sorted(
            (item for item in items if item["report_kind"] == "formal-run"),
            key=_publication_order,
            reverse=True,
        )
        roles: dict[str, str] = {}
        for research_entry in reversed(research):
            roles.update(_formal_roles(research_entry["_trials"]))
        formal_groups: dict[str, list[dict[str, Any]]] = {
            "baseline_reference": [],
            "challenge_window": [],
            "parameter_config_variants": [],
        }
        seen_workspace_runs: set[str] = set()
        for item in formal:
            workspace_run_id = str(item["_workspace_run_id"])
            if workspace_run_id in seen_workspace_runs:
                continue
            seen_workspace_runs.add(workspace_run_id)
            role = roles.get(workspace_run_id, "baseline_reference")
            formal_groups[role].append(_public_entry(item))
        availability = (
            research[0]["_discovery"]
            if research
            else {
                "status": "not_evaluated",
                "items": [],
                "reason": "no research report",
            }
        )
        result.append(
            {
                "package": items[0]["_package"],
                "latest_research": _public_entry(research[0]) if research else None,
                "research_history": [_public_entry(item) for item in research[1:]],
                "formal_runs": formal_groups,
                "discovery_availability": availability,
            }
        )
    return result


def _formal_roles(trials: list[dict[str, Any]]) -> dict[str, str]:
    if not trials:
        return {}
    baseline = trials[0]
    result = {str(baseline.get("workspace_run_id")): "baseline_reference"}
    for trial in trials[1:]:
        if trial.get("snapshot_window") != baseline.get("snapshot_window"):
            role = "challenge_window"
        elif trial.get("parameters") != baseline.get("parameters") or _formal_configs(
            trial
        ) != _formal_configs(baseline):
            role = "parameter_config_variants"
        else:
            role = "baseline_reference"
        result[str(trial.get("workspace_run_id"))] = role
    return result


def _formal_configs(trial: dict[str, Any]) -> list[dict[str, Any]]:
    legs = trial.get("formal_legs")
    if not isinstance(legs, list):
        return []
    return [
        {
            "formal_id": leg.get("formal_id"),
            "adapter": leg.get("adapter"),
            "config": leg.get("config"),
        }
        for leg in legs
        if isinstance(leg, dict)
    ]


def _publication_order(item: dict[str, Any]) -> tuple[str, str]:
    return str(item["created_at"]), str(item["report_id"])


def _public_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _entry_row(item: dict[str, Any]) -> str:
    href = html.escape(str(item["href"]), quote=True)
    title = html.escape(str(item["title"]))
    created = html.escape(str(item["created_at"]))
    raw_summary = item.get("summary")
    summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
    if item.get("report_kind") == "formal-run":
        scope = (
            f"{summary.get('instrument_count', '—')} 品种 · "
            f"{summary.get('start', '—')} — {summary.get('end', '—')} · "
            f"{summary.get('outcome', '—')}"
        )
    else:
        scope = (
            f"{summary.get('trial_count', '—')} trials · "
            f"decision {summary.get('decision_status', '—')}"
        )
    return (
        f'<a class="report-row" href="{href}"><span class="report-title">{title}</span>'
        f'<span class="report-meta">{created}</span>'
        f'<span class="report-scope">{html.escape(scope)}</span></a>'
    )
