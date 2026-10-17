"""Vòng lặp epoch, chọn checkpoint theo mae_q head chính trên val, resume chính xác."""

import math
from pathlib import Path

import numpy as np
import torch

from surge_ml.config import Config
from surge_ml.data.batch import make_batch
from surge_ml.data.dataset import DerivedData
from surge_ml.errors import SurgeError
from surge_ml.evaluation.metrics import evaluate_predictions, flatten
from surge_ml.features import Variant, candidates
from surge_ml.models.dual_gru_gatv2 import forward_batch
from surge_ml.training import checkpoint
from surge_ml.training.losses import dual_loss, target_mask


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def _chunks(ks: np.ndarray, size: int, limit: int | None) -> list[np.ndarray]:
    out = [ks[i:i + size] for i in range(0, len(ks), size)]
    return out[:limit] if limit else out


@torch.no_grad()
def predict(model: torch.nn.Module, data: DerivedData, variant: Variant, ks: np.ndarray, batch_size: int,
            device: torch.device, limit: int | None = None) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Trả dự đoán mỗi head [K, N] và các cutoff thực sự được đánh giá."""
    model.eval()
    parts: dict[str, list] = {}
    chunks = _chunks(ks, batch_size, limit)
    for chunk in chunks:
        out = forward_batch(model, make_batch(data, chunk, variant, device))
        for head, value in out.items():
            parts.setdefault(head, []).append(value.cpu().numpy())
    return {h: np.concatenate(v) for h, v in parts.items()}, np.concatenate(chunks)


def evaluate(model, data, variant, split, cfg: Config, device) -> dict:
    preds, ks = predict(model, data, variant, data.candidates(split), cfg.train.eval_batch_size, device,
                        cfg.train.limit_batches)
    bypass = data.b32 if variant.bypass == "b32" else data.b
    return evaluate_predictions(preds, data.y[ks], bypass[ks], cfg.loss.smooth_l1_beta)


class Trainer:
    def __init__(self, model: torch.nn.Module, data: DerivedData, variant: Variant, cfg: Config, trial_dir: Path,
                 config_sha: str, seed: int, tracker=None):
        self.model, self.data, self.variant, self.cfg = model, data, variant, cfg
        self.dir, self.sha, self.tracker = trial_dir, config_sha, tracker
        self.device = resolve_device(cfg.train.device)
        self.model.to(self.device)
        t = cfg.train
        self.opt = torch.optim.AdamW(model.parameters(), lr=t.lr, weight_decay=t.weight_decay)
        if t.scheduler == "cosine":
            self.sched = torch.optim.lr_scheduler.CosineAnnealingLR(self.opt, T_max=max(t.epochs, 1))
        elif t.scheduler == "plateau":
            self.sched = torch.optim.lr_scheduler.ReduceLROnPlateau(self.opt, patience=max(1, t.patience // 2))
        else:
            self.sched = None
        self.shuffle = np.random.default_rng(seed)
        self.state = {"epoch": 0, "best_score": math.inf, "best_epoch": None, "bad_epochs": 0,
                      "stopped": False, "skipped_batches": 0, "history": []}

    # -- checkpoint -------------------------------------------------------
    def _payload(self) -> dict:
        return {"model": self.model.state_dict(), "optimizer": self.opt.state_dict(),
                "scheduler": self.sched.state_dict() if self.sched else None, "rng": checkpoint.capture_rng(),
                "shuffle": self.shuffle.bit_generator.state, "state": self.state,
                "config_sha256": self.sha, "variant": self.variant.name}

    def _resume(self) -> None:
        path = self.dir / "last.pt"
        if not path.is_file():
            raise SurgeError("RESUME", f"no checkpoint at {path}")
        ck = checkpoint.load(path)
        if ck["config_sha256"] != self.sha:
            raise SurgeError("RESUME", "config_sha256 differs from the checkpoint; start a new study_id")
        self.model.load_state_dict(ck["model"])
        self.opt.load_state_dict(ck["optimizer"])
        if self.sched and ck["scheduler"]:
            self.sched.load_state_dict(ck["scheduler"])
        checkpoint.restore_rng(ck["rng"])
        self.shuffle.bit_generator.state = ck["shuffle"]
        self.state = ck["state"]

    # -- loop ---------------------------------------------------------------
    def _train_epoch(self) -> dict[str, float]:
        self.model.train()
        t, totals, n = self.cfg.train, {}, 0
        ks = self.shuffle.permutation(self.data.candidates("train"))
        for chunk in _chunks(ks, t.batch_size, t.limit_batches):
            batch = make_batch(self.data, chunk, self.variant, self.device)
            y, loss_cfg = batch["y"], self.cfg.loss
            res = dual_loss(forward_batch(self.model, batch), y, target_mask(y, batch["b"]),
                            loss_cfg.smooth_l1_beta, loss_cfg.lambda_local)
            if res is None:
                self.state["skipped_batches"] += 1
                continue
            loss, parts = res
            if not torch.isfinite(loss):
                raise SurgeError("NONFINITE", f"loss is {loss.item()} at epoch {self.state['epoch']}")
            self.opt.zero_grad(set_to_none=True)
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), t.grad_clip_norm)
            if not torch.isfinite(norm):
                raise SurgeError("NONFINITE", f"grad norm is {norm.item()} at epoch {self.state['epoch']}")
            self.opt.step()
            n += 1
            for key, value in {"loss": loss, **{f"loss_{k}": v for k, v in parts.items()}}.items():
                totals[key] = totals.get(key, 0.0) + value.item()
        return {f"train/{k}": v / max(n, 1) for k, v in totals.items()}

    def fit(self, resume: bool = False) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        if resume:
            self._resume()
        t, s = self.cfg.train, self.state
        primary = self.variant.primary_head
        while s["epoch"] < t.epochs and not s["stopped"]:
            epoch = s["epoch"]
            train_metrics = self._train_epoch()
            val = evaluate(self.model, self.data, self.variant, "val", self.cfg, self.device)
            score = val[primary]["mae_q"]
            if isinstance(self.sched, torch.optim.lr_scheduler.ReduceLROnPlateau):
                self.sched.step(score)
            elif self.sched:
                self.sched.step()
            improved = score < s["best_score"] - t.tie_tolerance
            if improved:
                s.update(best_score=score, best_epoch=epoch, bad_epochs=0, best_val=val)
            else:
                s["bad_epochs"] += 1
            s["stopped"] = s["bad_epochs"] >= t.patience
            row = {"epoch": epoch, **train_metrics, **flatten(val, "val"), "lr": self.opt.param_groups[0]["lr"]}
            s["history"].append(row)
            s["epoch"] = epoch + 1
            if improved:
                checkpoint.save(self.dir / "best.pt", {"model": self.model.state_dict(), "epoch": epoch,
                                                        "val": val, "config_sha256": self.sha,
                                                        "variant": self.variant.name})
            checkpoint.save(self.dir / "last.pt", self._payload())
            if self.tracker:
                self.tracker.log_metrics({k: v for k, v in row.items() if k != "epoch"}, step=epoch)
            print(f"[{self.variant.name}] epoch {epoch} loss={train_metrics.get('train/loss', float('nan')):.4f} "
                  f"val/{primary}/mae_q={score:.4f}{' *' if improved else ''}", flush=True)
        return {"best_epoch": s["best_epoch"], "best_score": s["best_score"], "val": s.get("best_val"),
                "epochs_run": s["epoch"], "stopped_early": s["stopped"], "skipped_batches": s["skipped_batches"],
                "history": s["history"]}
