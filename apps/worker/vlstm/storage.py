"""Supabase Storage helpers for VLSTM weights (M10C L2).

Uploads `weights.pt` to bucket `models` at `<model_id>/weights.pt` after
training so Modal cold starts can fetch from Storage rather than rely on the
ephemeral `/tmp/jepx-vlstm/` cache.

Bucket needs to exist with private RLS (only service-role reads/writes).
Operator creates via Supabase dashboard or:
    INSERT INTO storage.buckets (id, name, public) VALUES ('models', 'models', false);
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

from common.db import _ensure_env_loaded

logger = logging.getLogger("vlstm.storage")

_BUCKET = "models"


def _supabase_url() -> str:
    _ensure_env_loaded()
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    if not url:
        raise RuntimeError("NEXT_PUBLIC_SUPABASE_URL not set")
    return url.rstrip("/")


def _service_key() -> str:
    _ensure_env_loaded()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not set")
    return key


def upload_weights_to_storage(model_id: str, weights_path: Path) -> str:
    """Upload a weights.pt file to `models/<model_id>/weights.pt`.

    Returns the Storage path (without the bucket prefix). Idempotent —
    overwrites on conflict.
    """
    if not weights_path.exists():
        raise FileNotFoundError(f"weights file not found: {weights_path}")
    url = f"{_supabase_url()}/storage/v1/object/{_BUCKET}/{model_id}/weights.pt"
    data = weights_path.read_bytes()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "authorization": f"Bearer {_service_key()}",
            "content-type": "application/octet-stream",
            "x-upsert": "true",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"storage upload status={resp.status}")
    return f"{model_id}/weights.pt"


def download_weights_from_storage(model_id: str, dest: Path) -> None:
    """Download `models/<model_id>/weights.pt` into `dest`."""
    url = f"{_supabase_url()}/storage/v1/object/{_BUCKET}/{model_id}/weights.pt"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"authorization": f"Bearer {_service_key()}"},
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status != 200:
            raise RuntimeError(f"storage download status={resp.status}")
        dest.write_bytes(resp.read())
