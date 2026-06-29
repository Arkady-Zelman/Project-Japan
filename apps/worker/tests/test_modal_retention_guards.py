"""Static guards for Modal retention jobs.

These tests intentionally avoid importing ``modal_app`` so they can run in a
minimal environment without Modal installed. The retention bug they guard
against was textual SQL in the scheduled entry point, so source inspection is
enough to catch regressions before deploy.
"""

from __future__ import annotations

import re
from pathlib import Path


MODAL_APP = Path(__file__).resolve().parents[1] / "modal_app.py"


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"^def {name}\(.*?^def ", source, flags=re.MULTILINE | re.DOTALL)
    if match:
        return match.group(0).rsplit("\ndef ", 1)[0]
    match = re.search(rf"^def {name}\(.*", source, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, f"{name} not found"
    return match.group(0)


def test_nightly_retention_routes_to_forecast_path_pruning_only() -> None:
    source = MODAL_APP.read_text(encoding="utf-8")
    body = _function_body(source, "prune_nightly")

    assert "return prune_old_data.local()" in body
    assert re.search(r"\btruncate\s+table\b", body, re.IGNORECASE) is None
    assert re.search(r"\bdelete\s+from\b", body, re.IGNORECASE) is None


def test_prune_old_data_preserves_canonical_history() -> None:
    source = MODAL_APP.read_text(encoding="utf-8")
    body = _function_body(source, "prune_old_data")

    assert "_prune_forecast_paths_impl" in body
    assert "canonical_history_preserved" in body
    assert re.search(r"\btruncate\s+table\b", body, re.IGNORECASE) is None
    assert re.search(r"\bdelete\s+from\b", body, re.IGNORECASE) is None


def test_forecast_retention_does_not_delete_parent_runs() -> None:
    source = MODAL_APP.read_text(encoding="utf-8").lower()

    assert re.search(r"delete\s+from\s+forecast_runs\b", source) is None
    assert "delete from forecast_paths" in source
    assert "v.status in ('queued', 'running')" in source
