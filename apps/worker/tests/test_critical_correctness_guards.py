from __future__ import annotations

import ast
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment.lower()
    raise AssertionError(f"{name} not found in modal_app.py")


def test_retention_entrypoints_do_not_destroy_canonical_tables() -> None:
    retention_source = "\n".join(
        [
            _function_source("_prune_forecast_paths_impl"),
            _function_source("prune_forecast_paths"),
            _function_source("prune_old_data"),
            _function_source("prune_nightly"),
        ]
    )

    forbidden_fragments = [
        "truncate table stack_curves",
        "truncate stack_curves",
        "delete from stack_curves",
        "delete from stack_clearing_prices",
        "delete from jepx_spot_prices",
        "delete from demand_actuals",
        "delete from generation_mix_actuals",
        "delete from weather_obs",
        "delete from regime_states",
    ]

    for fragment in forbidden_fragments:
        assert fragment not in retention_source


def test_forecast_retention_preserves_parent_runs_and_in_flight_paths() -> None:
    source = _function_source("_prune_forecast_paths_impl")

    assert "delete from forecast_paths" in source
    assert "delete from forecast_runs" not in source
    assert "from valuations v" in source
    assert "queued" in source
    assert "running" in source
