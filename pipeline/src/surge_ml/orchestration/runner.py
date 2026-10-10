"""Các giai đoạn: prepare, một trial, benchmark."""

import json
import random
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

from surge_ml.config import Config, config_sha256, flat_params
from surge_ml.data.dataset import DerivedData
from surge_ml.data.derive import prepare
from surge_ml.data.target import to_ratio
from surge_ml.errors import SurgeError
from surge_ml.evaluation.metrics import flatten
from surge_ml.features import VARIANTS, Variant, candidates
from surge_ml.models.registry import ADAPTERS, score
from surge_ml.tracking.mlflow_adapter import Tracker
from surge_ml.visualize import data_figures, trial_figures


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=float), encoding="utf-8")


def study_dir(cfg: Config) -> Path:
    return cfg.runs_root / cfg.study_id


def trial_dir(cfg: Config, variant: str, seed: int) -> Path:
    return study_dir(cfg) / variant / f"seed_{seed}"


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def run_prepare(cfg: Config) -> Path:
    path = prepare(cfg)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    print(f"derived: {path}")
    print(f"  window {cfg.data.window_steps} snapshots, horizon {cfg.data.horizon_minutes} min")
    for split, s in manifest["splits"].items():
        n = len(candidates(split, {split: tuple(s["bounds"])}, cfg.data.window_steps))
        print(f"  {split}: days {s['days'][0]}-{s['days'][1]}, {n} candidates")
    return path


def save_val_preds(out: Path, ks: np.ndarray, pred: np.ndarray, y: np.ndarray, b: np.ndarray) -> None:
    """Lưu dự đoán val của head chính và |q_hat - q| mỗi ô (NaN nếu không chấm) cho so sánh cặp."""
    mask = np.isfinite(y) & np.isfinite(b)
    err = np.where(mask, np.abs(to_ratio(pred.astype(np.float64)) - to_ratio(np.where(mask, y, 0.0))), np.nan)
    np.savez_compressed(out / "val_preds.npz", ks=ks, pred=pred.astype(np.float32), abs_err_q=err.astype(np.float32))


def run_trial(cfg: Config, data: DerivedData, variant: Variant, seed: int, resume: bool = False,
              out: Path | None = None) -> dict:
    """Huấn luyện một variant x seed bằng adapter của họ model rồi chấm val; `out` mặc định là thư mục trial."""
    out = out or trial_dir(cfg, variant.name, seed)
    if not resume and out.exists():
        if (study_dir(cfg) / "test_report.json").exists():
            raise SurgeError("ALREADY_FINALIZED", f"study {cfg.study_id} is finalized; use a new study_id")
        archived = out.parents[1] / "_archive" / f"{out.parent.name}_{out.name}_{datetime.now():%Y%m%d-%H%M%S}"
        archived.parent.mkdir(parents=True, exist_ok=True)
        out.rename(archived)  # a fresh train keeps the previous trial instead of deleting it
        print(f"previous trial moved to {archived}")
    sha = config_sha256(cfg, variant.name)
    vcfg = cfg.for_variant(variant.name)
    result = {"study_id": cfg.study_id, "variant": variant.name, "seed": seed, "config_sha256": sha,
              "primary_head": variant.primary_head, "derived_dir": str(data.path), "window_steps": data.window,
              "horizon_steps": data.horizon}
    with Tracker(cfg.tracking.enabled, cfg.tracking.experiment, out, f"{variant.name}-s{seed}",
                 resume=resume) as tracker:
        tracker.log_params({**flat_params(vcfg), "variant": variant.name, "family": variant.family, "seed": seed,
                            "config_sha256": sha, "derived_dir": str(data.path), "window_steps": data.window,
                            "horizon_steps": data.horizon})
        if cfg.tracking.enabled and data.path is not None:
            tracker.log_figures(data_figures(data.path), "data_figures")
        started = time.perf_counter()
        set_seed(seed)
        fitted = ADAPTERS[variant.family].fit(vcfg, data, variant, seed, out, tracker, resume, sha)
        result["train_seconds"] = time.perf_counter() - started
        result.update(fitted.info)
        if result.get("val") is None:  # models without an epoch loop are scored here
            result["val"] = score(vcfg, data, variant, fitted.preds, fitted.ks)
            tracker.log_metrics(flatten(result["val"], "val"), step=0)
        out.mkdir(parents=True, exist_ok=True)
        if fitted.history:
            write_json(out / "history.json", fitted.history)
            tracker.log_artifact(out / "history.json")
        y = data.y[fitted.ks]
        save_val_preds(out, fitted.ks, fitted.preds[variant.primary_head], y, data.b[fitted.ks])
        tracker.log_figures(trial_figures(fitted.history, fitted.preds, y, variant.primary_head, out / "figures"),
                            "figures")
        write_json(out / "trial_result.json", result)
        tracker.log_artifact(out / "trial_result.json")
    return result


def is_done(cfg: Config, variant: str, out: Path) -> bool:
    """True nếu `out` có trial đã xong cùng config; trial xong nhưng khác config thì báo lỗi."""
    done = out / "trial_result.json"
    if not done.exists():
        return False
    if json.loads(done.read_text(encoding="utf-8")).get("config_sha256") != config_sha256(cfg, variant):
        raise SurgeError("STALE_TRIAL", f"{done} was produced by a different config; use a new study_id")
    return True


def train(cfg: Config, variant: str, seed: int, resume: bool = False) -> dict:
    data = DerivedData.load(run_prepare(cfg), cfg.data.window_steps, cfg.data.horizon_steps)
    return run_trial(cfg, data, VARIANTS[variant], seed, resume)


def benchmark(cfg: Config) -> None:
    """Chạy mọi variant x seed; trial đã xong thì bỏ qua, trial dang dở thì chạy tiếp."""
    data = DerivedData.load(run_prepare(cfg), cfg.data.window_steps, cfg.data.horizon_steps)
    for seed in cfg.seeds:
        for name in cfg.variants:
            out = trial_dir(cfg, name, seed)
            if is_done(cfg, name, out):
                print(f"skip {name} seed {seed}: done")
                continue
            run_trial(cfg, data, VARIANTS[name], seed, resume=(out / "last.pt").exists())
