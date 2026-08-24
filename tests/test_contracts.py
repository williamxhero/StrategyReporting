from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from strategy_reporting.canonical import canonical_json, canonical_sha256, parse_json_bytes
from strategy_reporting.errors import ContractError
from strategy_reporting.models import ReportOptions


def test_canonical_json_is_sorted_and_unicode_preserving() -> None:
    assert canonical_json({"z": 1, "a": "中文"}) == b'{"a":"\xe4\xb8\xad\xe6\x96\x87","z":1}'
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})


def test_canonical_json_normalizes_positive_and_negative_float_zero() -> None:
    assert canonical_json({"negative": -0.0, "positive": 0.0}) == (b'{"negative":0,"positive":0}')
    assert canonical_sha256({"value": -0.0}) == canonical_sha256({"value": 0})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite(value: float) -> None:
    with pytest.raises(ContractError, match="non-finite"):
        canonical_json({"value": value})


def test_canonical_json_rejects_local_path() -> None:
    with pytest.raises(ContractError, match="local path"):
        canonical_json({"path": Path("secret")})


def test_json_parser_rejects_nonfinite_constants() -> None:
    with pytest.raises(ContractError, match="forbidden JSON constant"):
        parse_json_bytes(b'{"value":NaN}', maximum_bytes=100)


def test_options_identity_excludes_workspace_and_subject_selectors(tmp_path: Path) -> None:
    left = ReportOptions(workspace_root=tmp_path, formal_id="a")
    right = ReportOptions(workspace_root=tmp_path / "other", formal_id="b")
    assert left.normalized() == right.normalized()
    assert left.options_hash == right.options_hash


def test_options_are_bounded_and_strict() -> None:
    with pytest.raises(ValidationError):
        ReportOptions(detail_row_limit=1001)
    with pytest.raises(ValidationError):
        ReportOptions.model_validate({"unknown": True})
