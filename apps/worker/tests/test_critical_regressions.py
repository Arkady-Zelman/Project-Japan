from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _function_block(source: str, name: str) -> str:
    match = re.search(
        rf"^def {re.escape(name)}\(.*?(?=^@app\.function|\Z)",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Could not find {name}"
    return match.group(0)


def test_nightly_retention_cannot_prune_canonical_history() -> None:
    modal_app = (ROOT / "apps/worker/modal_app.py").read_text()
    prune_nightly = _function_block(modal_app, "prune_nightly")

    assert "prune_forecast_paths.local" in prune_nightly
    assert "prune_old_data.local" not in prune_nightly
    assert "truncate table" not in prune_nightly.lower()


def test_emergency_history_prune_requires_explicit_confirmation() -> None:
    modal_app = (ROOT / "apps/worker/modal_app.py").read_text()
    prune_old_data = _function_block(modal_app, "prune_old_data")

    assert 'required_confirmation = "DELETE_CANONICAL_HISTORY"' in prune_old_data
    assert "if confirm != required_confirmation" in prune_old_data
    assert '"skipped": True' in prune_old_data


def test_bos_forecast_pagination_has_stable_order_before_range() -> None:
    route = (ROOT / "apps/web/src/app/api/bos-strategy/route.ts").read_text()
    forecast_query = route[route.index('.from("forecast_paths")') :]

    slot_order = forecast_query.index('.order("slot_start", { ascending: true })')
    path_order = forecast_query.index('.order("path_id", { ascending: true })')
    range_call = forecast_query.index(".range(from, from + pageSize - 1)")

    assert slot_order < range_call
    assert path_order < range_call
