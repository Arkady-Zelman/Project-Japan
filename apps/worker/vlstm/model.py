"""PyTorch Lightning module for the JEPX VLSTM forecaster.

One shared cross-area model with an 8-dim area embedding. Direct multi-step
forecast head: 168-slot lookback × 27 features → 48 forecast log-prices in
one shot. The MC-Dropout layer stays active during inference (`eval()`) so
each forward pass uses a different random mask — that's how we sample
1000 paths from the same model with `forecast.py`.

Architecture:
    InputProjection  (27 → 64)            -- per-timestep linear, no activation
    AreaEmbedding    (9 → 8)              -- broadcast to every timestep
    LSTM             (72 → 128, 2 layers, dropout 0.3 between layers)
    MCDropout        (128 → 128, p=0.3)   -- always active (one mask per fwd)
    Head             (128 → 48)           -- direct multi-step

Loss: MSE on log-price 48-step prediction. Optimizer: Adam(lr=1e-3) with
ReduceLROnPlateau on val_loss.

Critical: `MCDropout` overrides `train(mode)` to keep `self.training=True`
even when the parent module is in eval mode. This is the **one mask per
forward pass** behavior that BUILD_SPEC §7.5 step 3 requires.
"""

from __future__ import annotations

import logging

import pytorch_lightning as L  # type: ignore[import-untyped]
import torch
import torch.nn as nn
import torch.nn.functional as F  # noqa: N812

from .data import N_FEATURES_PER_SLOT
from .models import HORIZON_SLOTS, LOOKBACK_SLOTS, N_AREAS

logger = logging.getLogger("vlstm.model")

INPUT_PROJ_DIM = 64
AREA_EMB_DIM = 8
LSTM_HIDDEN = 128
LSTM_LAYERS = 2
DROPOUT_P = 0.3


class MCDropout(nn.Module):
    """Dropout that stays active during eval mode.

    `nn.Dropout` only drops during `model.train()`. For Monte-Carlo
    dropout sampling at inference, we want the mask randomized on every
    forward pass even when the parent is in eval mode. Override
    `train(mode)` to ignore the mode flag and always pass `training=True`
    to the functional call.
    """

    def __init__(self, p: float = DROPOUT_P) -> None:
        super().__init__()
        self.p = p

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Always-on dropout. One mask per forward pass (broadcast across
        # the timestep dim doesn't matter here — we apply after the LSTM
        # has reduced to a single hidden vector per example).
        return F.dropout(x, p=self.p, training=True)


class JEPXForecaster(L.LightningModule):
    """One shared model across 9 areas with an area embedding.

    Inputs to `forward`:
      x:       (B, 168, 27) feature tensor
      area_ix: (B,) long tensor of area indices in [0, 9)

    Output:
      y_hat:   (B, 48) predicted log-prices

    The area embedding is broadcast across all 168 timesteps and
    concatenated to the projected feature dim, so every timestep "knows"
    which area it belongs to.
    """

    def __init__(
        self,
        lr: float = 1e-3,
        hidden_dim: int = LSTM_HIDDEN,
        dropout_p: float = DROPOUT_P,
        lr_schedule: str = "plateau",
    ) -> None:
        super().__init__()
        self.save_hyperparameters()
        self.input_proj = nn.Linear(N_FEATURES_PER_SLOT, INPUT_PROJ_DIM)
        self.area_embedding = nn.Embedding(N_AREAS, AREA_EMB_DIM)
        self.lstm = nn.LSTM(
            input_size=INPUT_PROJ_DIM + AREA_EMB_DIM,
            hidden_size=hidden_dim,
            num_layers=LSTM_LAYERS,
            dropout=dropout_p,
            batch_first=True,
        )
        self.mc_dropout = MCDropout(p=dropout_p)
        self.head = nn.Linear(hidden_dim, HORIZON_SLOTS)

    def forward(self, x: torch.Tensor, area_ix: torch.Tensor) -> torch.Tensor:
        B, T, _ = x.shape
        assert T == LOOKBACK_SLOTS
        # Per-timestep input projection.
        h = self.input_proj(x)                          # (B, T, 64)
        # Area embedding broadcast across timesteps.
        emb = self.area_embedding(area_ix)              # (B, 8)
        emb = emb.unsqueeze(1).expand(B, T, -1)         # (B, T, 8)
        h = torch.cat([h, emb], dim=-1)                 # (B, T, 72)
        # LSTM.
        out, _ = self.lstm(h)                           # (B, T, 128)
        last = out[:, -1, :]                            # (B, 128)
        # MC-Dropout (always-on).
        last = self.mc_dropout(last)
        # Direct multi-step head.
        return self.head(last)                          # (B, 48)

    # ---------- Lightning hooks ----------------------------------------

    def training_step(self, batch, _batch_idx):
        x, area_ix, y = batch
        y_hat = self(x, area_ix)
        loss = F.mse_loss(y_hat, y)
        self.log("train_loss", loss, prog_bar=True)
        return loss

    def validation_step(self, batch, _batch_idx):
        x, area_ix, y = batch
        y_hat = self(x, area_ix)
        loss = F.mse_loss(y_hat, y)
        # RMSE in log-price space — log to make the gate downstream cheap.
        rmse = torch.sqrt(loss)
        self.log("val_loss", loss, prog_bar=True)
        self.log("val_rmse", rmse, prog_bar=True)
        return loss

    def configure_optimizers(self):
        opt = torch.optim.Adam(self.parameters(), lr=self.hparams.lr)
        schedule = getattr(self.hparams, "lr_schedule", "plateau")
        if schedule == "cosine":
            # Cosine schedule needs trainer.max_epochs at construction time;
            # default to 30 if Lightning doesn't expose it yet.
            t_max = getattr(self.trainer, "max_epochs", None) or 30
            sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=t_max)
            return {"optimizer": opt, "lr_scheduler": {"scheduler": sched, "interval": "epoch"}}
        # default: plateau
        sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
            opt, mode="min", factor=0.5, patience=3,
        )
        return {
            "optimizer": opt,
            "lr_scheduler": {
                "scheduler": sched,
                "monitor": "val_loss",
                "interval": "epoch",
            },
        }
