"""Twice-daily VLSTM inference: 1000 paths × 48 slots × 9 areas.

Per BUILD_SPEC §7.6:
1. Load latest production VLSTM model (`type='vlstm'`, `status='ready'`).
2. For each area, build the 168-slot inference window at the current
   forecast origin.
3. Vectorized inference: stack 9 areas × 1000 paths into one tensor,
   single forward pass with MC dropout active → 9000 × 48 log-prices.
4. Reconstruct raw prices: `path_kwh = exp(y_hat) * stack_horizon_kwh`
   element-wise. (Stack horizon stored on the FeatureWindow.)
5. Insert one `forecast_runs` row per area + bulk-insert
   `forecast_paths` rows (~432K total via `cur.executemany`).

Modal cron is twice daily — 22:00 UTC (07:00 JST) and 13:00 UTC (22:00 JST).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import torch

from common.audit import compute_run
from common.db import connect

from .data import AREA_INDEX, SLOT_MIN, build_inference_window
from .model import JEPXForecaster
from .models import HORIZON_SLOTS, AreaCode

logger = logging.getLogger("vlstm.forecast")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

LOCAL_WEIGHTS_PATH = Path("/tmp/jepx-vlstm/weights.pt")
N_PATHS = 1000


def _load_active_model() -> tuple[str, JEPXForecaster] | None:
    """Returns (model_id, model_in_eval_mode) or None if no production VLSTM."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select id::text, artifact_url
            from models
            where type='vlstm' and status='ready'
            order by created_at desc limit 1
            """
        )
        row = cur.fetchone()
    if not row:
        logger.warning("no active VLSTM model found")
        return None
    model_id, artifact_url = row[0], row[1]

    # Resolve artifact_url. We support file:// for local + the
    # Storage upload path will be wired in M6.5.
    if artifact_url and artifact_url.startswith("file://"):
        weights_path = Path(artifact_url[len("file://"):])
    else:
        weights_path = LOCAL_WEIGHTS_PATH
    if not weights_path.exists():
        logger.warning("weights file %s missing", weights_path)
        return None

    model = JEPXForecaster()
    state = torch.load(weights_path, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model_id, model


def _persist_run(
    cur, model_id: str, area_id: str, origin: datetime, n_paths: int,
) -> str:
    cur.execute(
        """
        insert into forecast_runs
          (model_id, area_id, forecast_origin, horizon_slots, n_paths)
        values (%s, %s, %s, %s, %s)
        returning id::text
        """,
        (model_id, area_id, origin, HORIZON_SLOTS, n_paths),
    )
    row = cur.fetchone()
    assert row is not None
    return cast(str, row[0])


def _bulk_insert_paths(
    cur, run_id: str, paths_kwh: np.ndarray, slot_starts: list[datetime],
) -> int:
    """Insert n_paths × HORIZON rows. Vectorized via executemany.

    `paths_kwh.shape == (n_paths, HORIZON)`; `slot_starts` length HORIZON.
    """
    n_paths = paths_kwh.shape[0]
    rows: list[tuple] = []
    for path_id in range(n_paths):
        for h in range(HORIZON_SLOTS):
            rows.append((
                run_id, path_id, slot_starts[h], float(paths_kwh[path_id, h]),
            ))
    inserted = 0
    chunk_size = 1000
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        cur.executemany(
            """
            insert into forecast_paths
              (forecast_run_id, path_id, slot_start, price_jpy_kwh)
            values (%s, %s, %s, %s)
            on conflict (forecast_run_id, path_id, slot_start) do update set
              price_jpy_kwh = excluded.price_jpy_kwh
            """,
            chunk,
        )
        inserted += len(chunk)
    return inserted


def run_inference(
    *,
    origin: datetime | None = None,
    area_codes: tuple[AreaCode, ...] | None = None,
    n_paths: int = N_PATHS,
) -> dict:
    """Generate 1000 paths × 48 slots for each area at the given origin.

    Vectorized: 9 areas × 1000 paths → batch of 9000 in a single forward
    pass. With MC dropout active in eval, each batch element gets a
    different mask (one per path).
    """
    if area_codes is None:
        area_codes = tuple(AREA_INDEX.keys())   # type: ignore[assignment]

    if origin is None:
        now = datetime.now(tz=UTC)
        floor_min = (now.minute // SLOT_MIN) * SLOT_MIN
        origin = now.replace(minute=floor_min, second=0, microsecond=0)

    with compute_run("forecast_inference") as run:
        run.set_input({
            "origin": origin.isoformat(),
            "areas": list(area_codes),
            "n_paths": n_paths,
        })

        active = _load_active_model()
        if active is None:
            run.set_output({"skipped": "no_active_model"})
            return {"status": "skipped", "reason": "no_active_model"}
        model_id, model = active

        # Build inference window per area. Skip areas with insufficient data.
        windows: dict[AreaCode, object] = {}
        for code in area_codes:
            try:
                windows[code] = build_inference_window(code, origin)
            except Exception as e:
                logger.warning("%s: skipping inference — %s", code, e)

        if not windows:
            run.set_output({"skipped": "no_inference_windows"})
            return {"status": "skipped", "reason": "no_inference_windows"}

        # ---------- Vectorized batch inference --------------------------
        # Build a (n_areas * n_paths, 168, 27) tensor by replicating each
        # area's window n_paths times. Same area_ix per batch slice. With
        # MC dropout active in eval, each row of the batch gets a
        # different dropout mask = one mask per path.
        used_codes = list(windows.keys())
        X_per_area = []
        ix_per_area = []
        stack_horizon_per_area: dict[AreaCode, np.ndarray] = {}
        for code in used_codes:
            w = windows[code]
            X_one = torch.tensor(np.array(w.X, dtype=np.float32))     # (168, 27)
            X_per_area.append(X_one.unsqueeze(0).expand(n_paths, -1, -1))
            ix_per_area.append(
                torch.full((n_paths,), w.area_index, dtype=torch.long)
            )
            stack_horizon_per_area[code] = np.array(
                w.stack_horizon_kwh, dtype=np.float32
            )

        X_batch = torch.cat(X_per_area, dim=0)      # (areas*paths, 168, 27)
        ix_batch = torch.cat(ix_per_area, dim=0)    # (areas*paths,)
        with torch.no_grad():
            y_hat = model(X_batch, ix_batch)        # (areas*paths, 48) log-prices
        # Reshape to (n_areas, n_paths, 48).
        y_log = y_hat.reshape(len(used_codes), n_paths, HORIZON_SLOTS).cpu().numpy()
        paths_kwh_per_area: dict[AreaCode, np.ndarray] = {}
        for i, code in enumerate(used_codes):
            # Reconstruct raw prices. exp(log-price) directly — no stack
            # division needed since training target was log(price), not
            # log(price/stack). Stack appeared as input feature only.
            paths_kwh_per_area[code] = np.exp(y_log[i])

        # ---------- Persist forecast_runs + forecast_paths --------------
        run_ids: dict[AreaCode, str] = {}
        slot_starts = [
            origin + timedelta(minutes=SLOT_MIN * h) for h in range(HORIZON_SLOTS)
        ]
        with connect() as conn, conn.cursor() as cur:
            cur.execute("select code, id::text from areas where code != 'SYS'")
            area_id_by_code = {r[0]: r[1] for r in cur.fetchall()}

            total_paths_written = 0
            for code in used_codes:
                area_id = area_id_by_code[code]
                run_id = _persist_run(cur, model_id, area_id, origin, n_paths)
                run_ids[code] = run_id
                inserted = _bulk_insert_paths(
                    cur, run_id, paths_kwh_per_area[code], slot_starts,
                )
                total_paths_written += inserted
                logger.info(
                    "%s: forecast_run=%s wrote %d path-slot rows",
                    code, run_id, inserted,
                )
            conn.commit()

        result = {
            "model_id": model_id,
            "origin": origin.isoformat(),
            "n_areas": len(used_codes),
            "n_paths_per_area": n_paths,
            "total_path_slot_rows": total_paths_written,
            "run_ids": run_ids,
        }
        run.set_output(result)
        # TODO(M7): trigger asset_revaluation for assets with
        # metadata->>'auto_revalue' = 'true'.
        return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m vlstm.forecast")
    p.add_argument("--origin", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC))
    p.add_argument("--n-paths", type=int, default=N_PATHS)
    p.add_argument("--areas")
    args = p.parse_args(argv)

    area_codes: tuple[AreaCode, ...] | None = None
    if args.areas:
        codes = [c.strip().upper() for c in args.areas.split(",") if c.strip()]
        area_codes = tuple(c for c in codes if c in AREA_INDEX)   # type: ignore[assignment]

    out = run_inference(
        origin=args.origin, area_codes=area_codes, n_paths=args.n_paths,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
