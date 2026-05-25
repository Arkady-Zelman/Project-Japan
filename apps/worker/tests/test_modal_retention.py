from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"function not found: {name}")


def test_prune_old_data_preserves_recent_stack_outputs() -> None:
    source = _function_source("prune_old_data")
    lowered = source.lower()

    assert "truncate table" not in lowered
    assert '("stack_clearing_prices", 90, "slot_start")' in source
    assert '("stack_curves", 90, "slot_start")' in source
    assert source.index('"stack_clearing_prices"') < source.index('"stack_curves"')

