"""Mỗi họ model (`Variant.family`) có một adapter: cách huấn luyện một trial và cách dự đoán một split."""

from pathlib import Path
from typing import NamedTuple, Protocol

import numpy as np

from surge_ml.config import Config
from surge_ml.data.dataset import DerivedData
from surge_ml.evaluation.metrics import evaluate_predictions
from surge_ml.features import Variant
from surge_ml.models import lgbm
from surge_ml.models.baselines import BASELINES
from surge_ml.models.dual_gru_gatv2 import build_model
from surge_ml.training import checkpoint
from surge_ml.training.trainer import Trainer, predict, resolve_device


class Fitted(NamedTuple):
    preds: dict[str, np.ndarray]  # val predictions per head, [K, N]
    ks: np.ndarray  # val cutoffs actually predicted
    history: list[dict]  # per-epoch rows; empty for untrained / non-epoch models
    info: dict  # merged into trial_result.json: n_params, best_epoch, n_trees, val (if already scored), ...


class Adapter(Protocol):
    def fit(self, cfg: Config, data: DerivedData, variant: Variant, seed: int, out: Path, tracker,
            resume: bool, sha: str) -> Fitted: ...

    def predict(self, cfg: Config, data: DerivedData, variant: Variant, out: Path,
                split: str) -> tuple[dict[str, np.ndarray], np.ndarray]: ...


def score(cfg: Config, data: DerivedData, variant: Variant, preds: dict[str, np.ndarray], ks: np.ndarray) -> dict:
    bypass = data.b32 if variant.bypass == "b32" else data.b
    return evaluate_predictions(preds, data.y[ks], bypass[ks], cfg.loss.smooth_l1_beta)


class BaselineAdapter:
    """Luật không huấn luyện (models/baselines.py); không lưu gì."""

    def fit(self, cfg, data, variant, seed, out, tracker, resume, sha) -> Fitted:
        preds, ks = self.predict(cfg, data, variant, out, "val")
        return Fitted(preds, ks, [], {"n_params": 0, "best_epoch": None})

    def predict(self, cfg, data, variant, out, split):
        ks = data.candidates(split)
        return BASELINES[variant.family](data, ks), ks


class LgbmAdapter:
    """models/lgbm.py; dừng sớm theo val, lưu model.txt."""

    def fit(self, cfg, data, variant, seed, out, tracker, resume, sha) -> Fitted:
        out.mkdir(parents=True, exist_ok=True)
        booster = lgbm.fit(data, variant, data.candidates("train"), data.candidates("val"), seed, out, cfg.lgbm,
                           smoke=cfg.train.limit_batches is not None)
        tracker.log_artifact(out / lgbm.MODEL_FILE)
        ks = data.candidates("val")
        return Fitted(lgbm.predict(booster, data, variant, ks), ks, [],
                      {"n_params": None, "n_trees": booster.num_trees(), "best_epoch": booster.best_iteration or None})

    def predict(self, cfg, data, variant, out, split):
        ks = data.candidates(split)
        return lgbm.predict(lgbm.load(out), data, variant, ks), ks


class GruAdapter:
    """SurgeNet (GRU, tuỳ chọn head GATv2) huấn luyện bằng Trainer; best.pt giữ epoch val tốt nhất."""

    def fit(self, cfg, data, variant, seed, out, tracker, resume, sha) -> Fitted:
        model = build_model(variant, cfg.model)
        n_params = sum(p.numel() for p in model.parameters())
        tracker.log_params({"n_params": n_params})
        summary = Trainer(model, data, variant, cfg, out, sha, seed, tracker).fit(resume=resume)
        history = summary.pop("history")
        tracker.log_artifact(out / "best.pt")
        preds, ks = self.predict(cfg, data, variant, out, "val")
        return Fitted(preds, ks, history, {"n_params": n_params, **summary})

    def predict(self, cfg, data, variant, out, split):
        model = build_model(variant, cfg.model)
        model.load_state_dict(checkpoint.load(out / "best.pt")["model"])
        device = resolve_device(cfg.train.device)
        return predict(model.to(device), data, variant, data.candidates(split), cfg.train.eval_batch_size, device,
                       cfg.train.limit_batches)


ADAPTERS: dict[str, Adapter] = {
    "persistence": BaselineAdapter(),
    "seasonal": BaselineAdapter(),
    "lgbm": LgbmAdapter(),
    "gru": GruAdapter(),
    "flow_gru": GruAdapter(),
}
