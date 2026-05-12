"""End-to-end VLSTM training + gate evaluation.

Pipeline (per BUILD_SPEC §7.5):

1. Pull training features over `[train_start, gate_start)` for all 9 areas.
   Stride=4 by default (~12 examples/area/day, ~40K/area/year).
2. Train/val split: last 7 days of the training window become the
   validation set for early stopping.
3. Train PyTorch Lightning module with EarlyStopping(monitor=val_loss,
   patience=5).
4. Evaluate per-area RMSE at horizons {1, 6, 12, 24, 48} on the gate
   window `[gate_start, gate_end)`.
5. Run AR(1) baseline (`vlstm.baseline.evaluate_baseline`) on the same
   gate window.
6. Gate decision: VLSTM RMSE@24h < AR(1) RMSE@24h on ≥6 of 9 areas →
   `models.status='ready'`, mark previous version 'deprecated', save
   weights. Else `status='deprecated'` with rationale logged.

Smoke-test invocation (small window, fast):
    python -m vlstm.train --train-start 2025-01-01 --gate-start 2026-04-24 \\
        --gate-end 2026-05-08 --epochs 5 --stride 8

Full M6 gate (Modal L4):
    modal run apps/worker/modal_app.py::train_vlstm_weekly
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import pytorch_lightning as L  # type: ignore[import-untyped]
import torch
from pytorch_lightning.callbacks import EarlyStopping  # type: ignore[import-untyped]
from torch.utils.data import DataLoader, TensorDataset

from common.audit import compute_run
from common.db import connect

from .baseline import evaluate_baseline
from .data import AREA_INDEX, SLOT_MIN, build_training_examples
from .model import JEPXForecaster
from .models import HORIZON_SLOTS, AreaCode

logger = logging.getLogger("vlstm.train")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Where to dump the trained weights locally before Storage upload (Storage
# upload is a M6.5 follow-up; for now we keep weights at this path so
# forecast.py can load them in-process).
LOCAL_WEIGHTS_DIR = Path("/tmp/jepx-vlstm")


def _examples_to_tensors(examples):
    """Stack a list of FeatureWindow into (X, area_ix, y) tensors."""
    X = torch.tensor(
        np.array([e.X for e in examples], dtype=np.float32),
        dtype=torch.float32,
    )
    area_ix = torch.tensor([e.area_index for e in examples], dtype=torch.long)
    y = torch.tensor(
        np.array([e.y for e in examples], dtype=np.float32),
        dtype=torch.float32,
    )
    return X, area_ix, y


def _evaluate_vlstm_gate(
    model: JEPXForecaster,
    *,
    gate_start: datetime,
    gate_end: datetime,
    area_codes: tuple[AreaCode, ...],
    stride_24h: int = HORIZON_SLOTS,
    n_mc_samples: int = 50,
) -> dict[str, dict]:
    """Per-area VLSTM RMSE on rolling 24h-stride forecasts within the gate window.

    The gate compares VLSTM's POINT forecast to AR(1)'s point forecast.
    With MC dropout always active, a single forward pass is noisy — to get
    a stable point estimate we average N=50 MC samples (Bayesian model
    averaging). This is the standard interpretation of MC dropout for
    point prediction (Gal & Ghahramani 2016).
    """
    out: dict[str, dict] = {}
    model.eval()
    with torch.no_grad():
        for code in area_codes:
            examples = list(
                build_training_examples(
                    start=gate_start,
                    end=gate_end - timedelta(minutes=SLOT_MIN * HORIZON_SLOTS),
                    area_codes=(code,),
                    stride=stride_24h,
                )
            )
            if not examples:
                out[code] = {"skipped": True, "n_origins": 0}
                continue
            X, ix, y = _examples_to_tensors(examples)
            # Average N MC samples for a Bayesian point estimate. Stack into
            # one big batch for vectorized inference: (n_mc * B, 168, 27).
            B = X.shape[0]
            X_rep = X.repeat(n_mc_samples, 1, 1)
            ix_rep = ix.repeat(n_mc_samples)
            y_hat_all = model(X_rep, ix_rep)                       # (n_mc*B, 48)
            y_hat_all = y_hat_all.view(n_mc_samples, B, HORIZON_SLOTS)
            y_hat = y_hat_all.mean(dim=0)                          # (B, 48) point estimate
            errs = (y_hat - y) ** 2
            rmse_per_h = torch.sqrt(errs.mean(dim=0)).cpu().numpy()

            # Reconstruct prices from log-prices for raw-yen RMSE @24h.
            # The gate text in BUILD_SPEC §12 says "RMSE" without specifying
            # units; we report both log-price and raw-yen RMSE to make the
            # comparison cheap regardless of which the operator wants.
            y_hat_kwh = torch.exp(y_hat).cpu().numpy()
            y_kwh = torch.exp(y).cpu().numpy()
            raw_errs = (y_hat_kwh - y_kwh) ** 2
            raw_rmse_per_h = np.sqrt(raw_errs.mean(axis=0))

            out[code] = {
                "rmse_logprice_per_horizon": [float(v) for v in rmse_per_h],
                "rmse_logprice_at_24h": float(rmse_per_h[HORIZON_SLOTS - 1]),
                "rmse_kwh_per_horizon": [float(v) for v in raw_rmse_per_h],
                "rmse_kwh_at_24h": float(raw_rmse_per_h[HORIZON_SLOTS - 1]),
                "n_origins": int(len(examples)),
            }
    return out


def _persist_model(
    *,
    train_start: datetime, gate_start: datetime, gate_end: datetime,
    metrics: dict, gate_pass: bool, n_beating: int,
    weights_path: Path,
) -> str:
    """Insert one models row carrying VLSTM hyperparams + metrics."""
    name = "vlstm_global"
    version = f"v1-{datetime.now(tz=UTC).strftime('%Y%m%d-%H%M%S')}"
    status = "ready" if gate_pass else "deprecated"
    artifact_url = f"file://{weights_path}"             # placeholder until Storage upload lands
    with connect() as conn, conn.cursor() as cur:
        # Demote any prior 'ready' row.
        cur.execute(
            "update models set status='deprecated' "
            "where type='vlstm' and name=%s and status='ready'",
            (name,),
        )
        cur.execute(
            """
            insert into models
              (name, type, version, hyperparams, training_window_start,
               training_window_end, metrics, artifact_url, status)
            values (%s, 'vlstm', %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s)
            returning id::text
            """,
            (
                name, version,
                json.dumps({
                    "lookback_slots": 168,
                    "horizon_slots": HORIZON_SLOTS,
                    "n_features_per_slot": 27,
                    "lstm_hidden": 128, "lstm_layers": 2,
                    "dropout": 0.3, "lr": 1e-3,
                    "area_emb_dim": 8,
                }),
                train_start, gate_start,
                json.dumps({
                    "gate_pass": gate_pass,
                    "n_areas_beating_baseline": n_beating,
                    **metrics,
                }),
                artifact_url, status,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        model_id = cast(str, row[0])
        conn.commit()
    return model_id


def train(
    *,
    train_start: datetime,
    gate_start: datetime,
    gate_end: datetime,
    n_epochs: int = 25,
    stride: int = 4,
    val_days: int = 7,
    batch_size: int = 256,
    area_codes: tuple[AreaCode, ...] | None = None,
    hidden_dim: int = 128,
    dropout_p: float = 0.3,
    lr: float = 1e-3,
    lr_schedule: str = "plateau",
    upload_storage: bool = False,
) -> dict:
    """Run the full M6 training + gate evaluation pipeline."""
    if area_codes is None:
        area_codes = tuple(AREA_INDEX.keys())   # type: ignore[assignment]

    LOCAL_WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)

    with compute_run("vlstm_train") as run:
        run.set_input({
            "train_start": train_start.isoformat(),
            "gate_start": gate_start.isoformat(),
            "gate_end": gate_end.isoformat(),
            "n_epochs": n_epochs, "stride": stride, "val_days": val_days,
            "areas": list(area_codes),
        })

        # ---------- 1. Build training examples ------------------------
        logger.info("generating training examples %s → %s", train_start, gate_start)
        examples = list(
            build_training_examples(
                start=train_start, end=gate_start, area_codes=area_codes, stride=stride,
            )
        )
        logger.info("got %d training examples across %d areas", len(examples), len(area_codes))
        if len(examples) < 100:
            run.set_output({"skipped": "too_few_examples", "n": len(examples)})
            return {"status": "skipped", "n_examples": len(examples)}

        # Train/val split by origin date.
        val_cutoff = gate_start - timedelta(days=val_days)
        train_ex = [e for e in examples if e.origin < val_cutoff]
        val_ex = [e for e in examples if e.origin >= val_cutoff]
        logger.info("train=%d val=%d", len(train_ex), len(val_ex))

        X_tr, ix_tr, y_tr = _examples_to_tensors(train_ex)
        X_va, ix_va, y_va = _examples_to_tensors(val_ex) if val_ex else (None, None, None)

        train_loader = DataLoader(
            TensorDataset(X_tr, ix_tr, y_tr),
            batch_size=batch_size, shuffle=True, num_workers=0,
        )
        val_loader = (
            DataLoader(
                TensorDataset(X_va, ix_va, y_va),
                batch_size=batch_size, shuffle=False, num_workers=0,
            )
            if X_va is not None else None
        )

        # ---------- 2. Train ------------------------------------------
        model = JEPXForecaster(
            lr=lr, hidden_dim=hidden_dim, dropout_p=dropout_p, lr_schedule=lr_schedule,
        )
        callbacks: list = []
        if val_loader is not None:
            callbacks.append(EarlyStopping(monitor="val_loss", patience=5, mode="min"))
        trainer = L.Trainer(
            max_epochs=n_epochs, accelerator="auto", devices="auto",
            callbacks=callbacks, log_every_n_steps=10,
            enable_checkpointing=False, enable_progress_bar=True,
        )
        trainer.fit(model, train_loader, val_loader)

        # ---------- 3. Save weights -----------------------------------
        weights_path = LOCAL_WEIGHTS_DIR / "weights.pt"
        torch.save(model.state_dict(), weights_path)
        logger.info("weights saved to %s", weights_path)

        # ---------- 4. Per-area VLSTM gate eval -----------------------
        vlstm_metrics = _evaluate_vlstm_gate(
            model, gate_start=gate_start, gate_end=gate_end, area_codes=area_codes,
        )

        # ---------- 5. AR(1) baseline ---------------------------------
        baseline_metrics = evaluate_baseline(
            area_codes=area_codes,
            train_start=train_start, gate_start=gate_start, gate_end=gate_end,
        )

        # ---------- 6. Gate decision ----------------------------------
        n_beating = 0
        gate_per_area: dict[str, dict] = {}
        for code in area_codes:
            v = vlstm_metrics.get(code, {})
            b = baseline_metrics.get(code, {})
            v_rmse = v.get("rmse_kwh_at_24h")
            b_rmse = b.get("rmse_at_24h")
            beats = (
                v_rmse is not None and b_rmse is not None
                and not math.isnan(v_rmse) and not math.isnan(b_rmse)
                and v_rmse < b_rmse
            )
            if beats:
                n_beating += 1
            gate_per_area[code] = {
                "vlstm_rmse_kwh_at_24h": v_rmse,
                "ar1_rmse_kwh_at_24h": b_rmse,
                "beats_baseline": bool(beats),
            }

        gate_pass = n_beating >= 6
        logger.info(
            "GATE: VLSTM beats AR(1) on %d of %d areas → %s",
            n_beating, len(area_codes), "PASS" if gate_pass else "FAIL",
        )

        # ---------- 7. Persist ----------------------------------------
        all_metrics = {
            "vlstm": vlstm_metrics,
            "ar1_baseline": baseline_metrics,
            "gate_per_area": gate_per_area,
        }
        model_id = _persist_model(
            train_start=train_start, gate_start=gate_start, gate_end=gate_end,
            metrics=all_metrics, gate_pass=gate_pass, n_beating=n_beating,
            weights_path=weights_path,
        )

        # Optional Supabase Storage upload (M10C L2).
        storage_path: str | None = None
        if upload_storage:
            from .storage import upload_weights_to_storage
            try:
                storage_path = upload_weights_to_storage(model_id, weights_path)
                logger.info("uploaded weights to Storage at %s", storage_path)
                # Rewrite artifact_url so forecast.py knows to pull from Storage.
                with connect() as conn, conn.cursor() as cur:
                    cur.execute(
                        "update models set artifact_url=%s where id=%s",
                        (f"supabase://models/{storage_path}", model_id),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning("Storage upload failed: %s", e)

        result = {
            "model_id": model_id,
            "status": "ready" if gate_pass else "deprecated",
            "n_areas_beating_baseline": n_beating,
            "gate_pass": gate_pass,
            "n_train": len(train_ex), "n_val": len(val_ex),
        }
        run.set_output(result)
        return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m vlstm.train")
    p.add_argument("--train-start", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC),
                   default=datetime(2024, 1, 1, tzinfo=UTC))
    p.add_argument("--gate-start", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC))
    p.add_argument("--gate-end", type=lambda s: datetime.fromisoformat(s).replace(tzinfo=UTC))
    p.add_argument("--epochs", type=int, default=15)
    p.add_argument("--stride", type=int, default=8)
    p.add_argument("--val-days", type=int, default=7)
    p.add_argument("--batch", type=int, default=256)
    p.add_argument("--areas", help="comma-separated AreaCodes; default all 9")
    p.add_argument("--hidden-dim", type=int, default=128, help="LSTM hidden size")
    p.add_argument("--dropout", type=float, default=0.3, help="Dropout probability")
    p.add_argument("--lr", type=float, default=1e-3, help="Initial learning rate")
    p.add_argument("--lr-schedule", choices=["plateau", "cosine"], default="plateau")
    p.add_argument("--upload-storage", action="store_true",
                   help="Upload weights.pt to Supabase Storage after training")
    args = p.parse_args(argv)

    if args.gate_end is None:
        # Default: today (rounded to start-of-day) as gate_end, today − 14d as gate_start.
        today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        args.gate_end = today
    if args.gate_start is None:
        args.gate_start = args.gate_end - timedelta(days=14)

    area_codes: tuple[AreaCode, ...] | None = None
    if args.areas:
        codes = [c.strip().upper() for c in args.areas.split(",") if c.strip()]
        area_codes = tuple(c for c in codes if c in AREA_INDEX)   # type: ignore[assignment]

    out = train(
        train_start=args.train_start,
        gate_start=args.gate_start, gate_end=args.gate_end,
        n_epochs=args.epochs, stride=args.stride, val_days=args.val_days,
        batch_size=args.batch, area_codes=area_codes,
        hidden_dim=args.hidden_dim, dropout_p=args.dropout, lr=args.lr,
        lr_schedule=args.lr_schedule, upload_storage=args.upload_storage,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
