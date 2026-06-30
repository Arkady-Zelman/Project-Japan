"""Static safety guards for Modal retention jobs.

These tests intentionally parse modal_app.py without importing it. Importing the
module requires Modal and worker dependencies that are not always installed in
the lightweight cloud test image.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"

CANONICAL_TABLES = (
    "jepx_spot_prices",
    "demand_actuals",
    "generation_mix_actuals",
    "weather_obs",
    "stack_curves",
    "stack_clearing_prices",
    "regime_states",
)

RETENTION_FUNCTIONS = (
    "_prune_forecast_paths_impl",
    "prune_forecast_paths",
    "prune_old_data",
    "prune_nightly",
)


def _function_source(name: str) -> str:
    source = MODAL_APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"{name} not found in {MODAL_APP}")


def test_retention_jobs_do_not_delete_canonical_history() -> None:
    for function_name in RETENTION_FUNCTIONS:
        body = _function_source(function_name).lower()
        for table in CANONICAL_TABLES:
            assert not re.search(rf"\bdelete\s+from\s+{table}\b", body), function_name
            assert not re.search(rf"\btruncate\s+table\b[^;]*\b{table}\b", body), function_name


def test_retention_prunes_paths_not_forecast_run_metadata() -> None:
    body = _function_source("_prune_forecast_paths_impl").lower()
    assert re.search(r"\bdelete\s+from\s+forecast_paths\b", body)
    assert not re.search(r"\bdelete\s+from\s+forecast_runs\b", body)
    assert "valuations" in body
    assert "'queued'" in body
    assert "'running'" in body


def test_legacy_and_nightly_entry_points_use_safe_helper() -> None:
    helper_call = "_prune_forecast_paths_impl(retain_latest_per_area=2)"
    assert helper_call in _function_source("prune_old_data")
    assert helper_call in _function_source("prune_nightly")
