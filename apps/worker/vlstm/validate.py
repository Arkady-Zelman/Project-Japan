"""Replay the M6 STOP gate from the persisted `models.metrics` row.

Doesn't re-train, doesn't re-evaluate — just reads the latest VLSTM model
row, prints per-area RMSE@24h vs AR(1), and flags PASS/FAIL.

CLI: `python -m vlstm.validate`. Logs to `compute_runs(kind='vlstm_validate')`.
"""

from __future__ import annotations

import argparse
import json
import logging

from common.audit import compute_run
from common.db import connect

from .data import AREA_INDEX

logger = logging.getLogger("vlstm.validate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def evaluate(name: str = "vlstm_global") -> dict:
    with compute_run("vlstm_validate") as run:
        run.set_input({"name": name})
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select id::text, version, status, metrics::text, created_at
                from models
                where type='vlstm' and name=%s
                order by created_at desc limit 1
                """,
                (name,),
            )
            row = cur.fetchone()
        if not row:
            run.set_output({"missing_model": True})
            return {"missing_model": True, "name": name}

        model_id, version, status, metrics_json, created_at = row
        metrics = json.loads(metrics_json)
        gate_per_area = metrics.get("gate_per_area", {})
        n_beating = metrics.get("n_areas_beating_baseline")
        gate_pass = metrics.get("gate_pass")

        run.set_output({
            "model_id": model_id, "version": version, "status": status,
            "gate_pass": gate_pass, "n_areas_beating_baseline": n_beating,
        })
        return {
            "model_id": model_id, "version": version, "status": status,
            "created_at": created_at, "gate_per_area": gate_per_area,
            "gate_pass": gate_pass, "n_beating": n_beating,
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m vlstm.validate")
    p.add_argument("--name", default="vlstm_global")
    args = p.parse_args(argv)

    out = evaluate(args.name)
    if out.get("missing_model"):
        print("no VLSTM model found")
        return 1

    print()
    print(f"model_id={out['model_id']} version={out['version']} status={out['status']}")
    print(f"created={out['created_at']}")
    print()
    print(
        f"{'area':<5} {'vlstm_rmse@24h':>15} {'ar1_rmse@24h':>14} "
        f"{'beats?':>8}"
    )
    for code in AREA_INDEX:
        row = out["gate_per_area"].get(code, {})
        v = row.get("vlstm_rmse_kwh_at_24h")
        b = row.get("ar1_rmse_kwh_at_24h")
        beats = row.get("beats_baseline")
        v_s = f"{v:.3f}" if isinstance(v, (int, float)) else "—"
        b_s = f"{b:.3f}" if isinstance(b, (int, float)) else "—"
        print(f"{code:<5} {v_s:>15} {b_s:>14} {('PASS' if beats else 'FAIL'):>8}")
    print()
    print(
        f"VLSTM beats AR(1) on {out['n_beating']} of 9 areas at 24h horizon. "
        f"Gate: {'PASS' if out['gate_pass'] else 'FAIL'} (need ≥6)"
    )
    return 0 if out["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
