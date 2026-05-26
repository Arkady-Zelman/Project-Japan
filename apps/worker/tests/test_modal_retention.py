from __future__ import annotations

import ast
from pathlib import Path


def _prune_old_data_node() -> ast.FunctionDef:
    source = Path(__file__).resolve().parents[1] / "modal_app.py"
    module = ast.parse(source.read_text())
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "prune_old_data":
            return node
    raise AssertionError("prune_old_data not found")


def _time_pruned_tables(node: ast.FunctionDef) -> list[tuple[str, int, str]]:
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "time_pruned" for target in child.targets)
        ):
            continue
        return ast.literal_eval(child.value)
    raise AssertionError("time_pruned assignment not found")


def test_retention_keeps_recent_stack_outputs() -> None:
    node = _prune_old_data_node()
    tables = _time_pruned_tables(node)

    assert ("stack_clearing_prices", 90, "slot_start") in tables
    assert ("stack_curves", 90, "slot_start") in tables
    assert tables.index(("stack_clearing_prices", 90, "slot_start")) < tables.index(
        ("stack_curves", 90, "slot_start")
    )


def test_retention_does_not_truncate_stack_outputs() -> None:
    constants = [
        child.value.lower()
        for child in ast.walk(_prune_old_data_node())
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]

    assert not any("truncate" in value and "stack_curves" in value for value in constants)
