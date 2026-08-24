from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from strategy_reporting.errors import ContractError


def normalize_json(value: Any, *, location: str = "$") -> Any:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("nonfinite_number", f"non-finite number at {location}")
        return 0 if value == 0 else value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ContractError("nonfinite_number", f"non-finite decimal at {location}")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ContractError("naive_datetime", f"datetime at {location} lacks timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        raise ContractError("local_path_in_contract", f"local path is forbidden at {location}")
    if isinstance(value, Mapping):
        return {
            str(key): normalize_json(item, location=f"{location}.{key}")
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | memoryview):
        return [
            normalize_json(item, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ContractError(
        "unsupported_json_value",
        f"unsupported JSON value {type(value).__name__} at {location}",
    )


def canonical_json(value: Any) -> bytes:
    normalized = normalize_json(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid_json", str(exc)) from exc


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return sha256(value).hexdigest()


def parse_json_bytes(value: bytes, *, maximum_bytes: int) -> Any:
    if len(value) > maximum_bytes:
        raise ContractError(
            "model_too_large", f"JSON artifact is {len(value)} bytes; limit is {maximum_bytes}"
        )
    try:
        decoded = json.loads(value.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ContractError("invalid_json", f"invalid UTF-8 JSON: {exc}") from exc
    return normalize_json(decoded)


def _reject_constant(value: str) -> None:
    raise ValueError(f"forbidden JSON constant: {value}")
