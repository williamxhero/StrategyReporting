from __future__ import annotations

import re
from base64 import b64encode
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlparse

from strategy_reporting.errors import RenderError

FORBIDDEN_TEXT = ("innerHTML", "eval(", "new Function", "javascript:")
REMOTE_ATTRIBUTES = {"src", "href", "action", "formaction", "poster"}
FORBIDDEN_TAGS = {"base", "object", "embed", "form", "iframe"}


class _SafetyParser(HTMLParser):
    def __init__(self, *, native_plotly: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.native_plotly = native_plotly
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in FORBIDDEN_TAGS:
            self.errors.append(f"forbidden tag <{lowered}>")
        for name, value in attrs:
            key = name.lower()
            raw = value or ""
            if key.startswith("on"):
                self.errors.append(f"event handler attribute {key}")
            if key in REMOTE_ATTRIBUTES and raw:
                parsed = urlparse(raw.strip())
                if parsed.scheme.lower() in {
                    "http",
                    "https",
                    "ftp",
                    "file",
                    "javascript",
                } or raw.startswith("//"):
                    self.errors.append(f"remote or unsafe resource {key}={raw[:80]}")
            if key == "srcdoc":
                self.errors.append("srcdoc is forbidden")


def validate_html(value: bytes, *, maximum_bytes: int, native_plotly: bool = False) -> None:
    if len(value) > maximum_bytes:
        raise RenderError("html_too_large", f"HTML is {len(value)} bytes; limit is {maximum_bytes}")
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RenderError("html_not_utf8", str(exc)) from exc
    if not re.match(r"\s*<!doctype html>", text, flags=re.IGNORECASE):
        raise RenderError("html_structure_invalid", "document lacks HTML5 doctype")
    parser = _SafetyParser(native_plotly=native_plotly)
    parser.feed(text)
    if not native_plotly:
        parser.errors.extend(item for item in FORBIDDEN_TEXT if item in text)
    if parser.errors:
        raise RenderError("unsafe_html", "; ".join(sorted(set(parser.errors))))
    if "Content-Security-Policy" not in text:
        raise RenderError("csp_missing", "document lacks a CSP meta policy")


def stylesheet_csp(value: str) -> str:
    return (
        "default-src 'none'; style-src 'sha256-"
        + b64encode(sha256(value.encode("utf-8")).digest()).decode("ascii")
        + "'; img-src data:; base-uri 'none'; form-action 'none'"
    )


def add_native_csp(value: str) -> str:
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", value, flags=re.IGNORECASE | re.DOTALL)
    script_tokens = " ".join(_hash_token(item) for item in scripts)
    policy_value = (
        "default-src 'none'; "
        + (f"script-src {script_tokens}; " if script_tokens else "script-src 'none'; ")
        + "style-src-elem 'unsafe-inline'; "
        + "style-src-attr 'unsafe-inline'; img-src data: blob:; base-uri 'none'; form-action 'none'"
    )
    policy = f'<meta http-equiv="Content-Security-Policy" content="{policy_value}">'
    match = re.search(r"<head[^>]*>", value, flags=re.IGNORECASE)
    if not match:
        raise RenderError("native_tearsheet_invalid", "Nautilus HTML lacks a head element")
    return value[: match.end()] + policy + value[match.end() :]


def _hash_token(value: str) -> str:
    return "'sha256-" + b64encode(sha256(value.encode("utf-8")).digest()).decode("ascii") + "'"
