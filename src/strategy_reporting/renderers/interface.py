from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from strategy_reporting.models import ReportModel, ReportOptions


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    name: str
    media_type: str
    logical_role: str
    record_schema: str | None
    content: bytes


@dataclass(frozen=True, slots=True)
class RenderedBundle:
    model: ReportModel
    model_bytes: bytes
    artifacts: tuple[RenderedArtifact, ...]
    renderer_version: str
    options: ReportOptions


class ReportRenderer(Protocol):
    renderer_version: str

    def render(self, model: ReportModel, options: ReportOptions) -> RenderedBundle: ...
