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
                    "_trials": research_model.trials,
                    "_discovery": research_model.discovery.model_dump(mode="json"),
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
            native_refs = [
                item
                for item in publication.envelope.artifacts
                if item.logical_role == "native-tearsheet-html"
            ]
            if len(native_refs) > 1:
                raise ContractError(
                    "portal_native_tearsheet_ambiguous",
                    f"native tearsheet HTML ambiguous: {report_id}",
                )
            native_tearsheet_href: str | None = None
            if native_refs:
                native_tearsheet_href = f"reports/{report_id}/nautilus-tearsheet.html"
            entries.append(
                {
                    "report_id": report_id,
                    "report_kind": descriptor.report_kind,
                    "strategy_id": entry_strategy_id,
                    "subject": subject,
                    "title": descriptor.title,
                    "created_at": record.get("created_at"),
                    "href": f"reports/{report_id}/index.html",
                    "native_tearsheet_href": native_tearsheet_href,
                    "lineage": record.get("lineage", []),
                    "_html_ref": html_refs[0].model_dump(mode="json"),
                    "_native_tearsheet_ref": (
                        native_refs[0].model_dump(mode="json") if native_refs else None
                    ),
                    "_publication_subject": descriptor.subject_id,
                    "_package": package,
                    **internal,
                }
            )
        entries = _latest_subject_entries(entries)
        entries.sort(
            key=lambda item: (
                str(item["strategy_id"]),
                str(item["created_at"]),
                str(item["report_id"]),
            ),
            reverse=True,
        )
        for entry in entries:
            destination = self._destination(
                root, Path("reports") / str(entry["report_id"]) / "index.html"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.workspace.materialize_verified(entry["_html_ref"], destination)
            native_ref = entry["_native_tearsheet_ref"]
            if native_ref is not None:
                native_destination = self._destination(
                    root, Path("reports") / str(entry["report_id"]) / "nautilus-tearsheet.html"
                )
                self.workspace.materialize_verified(native_ref, native_destination)
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
        latest_html = _entry_link(latest) if latest else "<span>无</span>"
        history = (
            "".join(_entry_item(item) for item in package["research_history"]) or "<li>无</li>"
        )
        formal = package["formal_runs"]
        formal_sections = "".join(
            f"<h4>{label}</h4><ul>{''.join(_entry_item(item) for item in formal[key]) or '<li>无</li>'}</ul>"
            for key, label in (
                ("baseline_reference", "基准/参考运行"),
                ("challenge_window", "挑战区间"),
                ("parameter_config_variants", "参数/配置变体"),
            )
        )
        availability = package["discovery_availability"]
        discovery = html.escape(str(availability.get("status", "not_evaluated")))
        reason = html.escape(str(availability.get("reason") or ""))
        package_name = html.escape(str(package["package"]["strategy_id"]))
        sections.append(
            f"<section><h2>{package_name}</h2><h3>最新研究报告</h3>{latest_html}"
            f"<h3>历史研究报告</h3><ul>{history}</ul>"
            f"<h3>正式运行报告</h3>{formal_sections}"
            f"<h3>探索可用性</h3><p>{discovery} {reason}</p></section>"
        )
    empty = "<p>当前没有已发布报告。</p>" if not sections else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'"><title>Strategy Reporting Portal</title><style>body{{font:15px/1.6 system-ui;margin:40px auto;max-width:980px;padding:0 24px;color:#18211d;background:#f7f5ef}}section{{background:white;padding:18px;margin:14px 0;border:1px solid #d8ddd9}}a{{color:#176b4d}}small{{color:#647069}}</style></head><body><h1>Strategy Reporting Portal</h1>{empty}{"".join(sections)}</body></html>"""


def _package_identity(raw: Any) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    return {
        "strategy_id": str(value.get("strategy_id") or "unknown"),
        "revision": value.get("revision"),
        "package_hash": value.get("package_hash"),
    }


def _latest_subject_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hide superseded renderer revisions for one immutable report subject."""
    latest: dict[str, dict[str, Any]] = {}
    for item in entries:
        subject = str(item["_publication_subject"])
        previous = latest.get(subject)
        if previous is None or _publication_order(item) > _publication_order(previous):
            latest[subject] = item
    return list(latest.values())


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
        research = sorted(
            (item for item in items if item["report_kind"] == "research-study"),
            key=_publication_order,
            reverse=True,
        )
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
        for item in formal:
            role = roles.get(str(item["_workspace_run_id"]), "baseline_reference")
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


def _entry_item(item: dict[str, Any]) -> str:
    return f"<li>{_entry_link(item)}</li>"


def _entry_link(item: dict[str, Any]) -> str:
    href = html.escape(str(item["href"]), quote=True)
    title = html.escape(str(item["title"]))
    created = html.escape(str(item["created_at"]))
    native = item.get("native_tearsheet_href")
    native_link = ""
    if native:
        native_href = html.escape(str(native), quote=True)
        native_link = f' · <a href="{native_href}">净值/回撤图</a>'
    return f'<a href="{href}">{title}</a>{native_link} <small>{created}</small>'
