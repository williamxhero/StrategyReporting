from __future__ import annotations

from strategy_reporting.errors import RenderError
from strategy_reporting.models import (
    FormalRunReport,
    ReplicationStudyReport,
    ReportModel,
    ResearchStudyReport,
)
from strategy_reporting.renderers.formal_run import FormalRunRenderer
from strategy_reporting.renderers.interface import ReportRenderer
from strategy_reporting.renderers.replication import ReplicationStudyRenderer
from strategy_reporting.renderers.research_study import ResearchStudyRenderer


class RendererRegistry:
    def __init__(self) -> None:
        self._formal = FormalRunRenderer()
        self._research = ResearchStudyRenderer()
        self._replication = ReplicationStudyRenderer()

    def resolve(self, model: ReportModel) -> ReportRenderer:
        if isinstance(model, FormalRunReport):
            return self._formal
        if isinstance(model, ResearchStudyReport):
            return self._research
        if isinstance(model, ReplicationStudyReport):
            return self._replication
        raise RenderError("renderer_not_registered", f"no renderer for {type(model).__name__}")
