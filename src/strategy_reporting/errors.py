from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReportingError(Exception):
    code: str
    message: str
    category: str = "contract"
    details: dict[str, object] | None = None

    def __str__(self) -> str:
        return self.message


class SourceError(ReportingError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "source", details)


class ContractError(ReportingError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "contract", details)


class RenderError(ReportingError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "render", details)


class PublicationError(ReportingError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(code, message, "publication", details)
