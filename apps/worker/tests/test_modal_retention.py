from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text()
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found in modal_app.py")


def test_nightly_retention_preserves_canonical_tables() -> None:
    source = MODAL_APP.read_text().lower()
    prune_old_data = _function_source("prune_old_data").lower()

    assert "prune_forecast_paths.local(retain_latest_per_area=2)" in prune_old_data
    assert "truncate table stack_curves" not in source
    assert "delete from" not in prune_old_data
    assert "truncate" not in prune_old_data


def test_prune_nightly_uses_safe_retention_wrapper() -> None:
    prune_nightly = _function_source("prune_nightly")

    assert "return prune_old_data.local()" in prune_nightly
