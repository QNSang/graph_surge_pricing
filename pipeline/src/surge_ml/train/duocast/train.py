from __future__ import annotations
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import numpy as np
import pandas as pd
import torch
from surge_ml._constant import CONTRACT_VERSION
from surge_ml._utils.io import atomic_json, digest_file, trial_lock
from surge_ml.datasets.duocast import load_panel, make_splits, split_manifest, input_schema
from surge_ml.datasets.batching import Batcher, fit_scalers
from surge_ml.reports.metrics import point_metrics, evaluate
from surge_ml.inferences.duocast import load_checkpoint, resolve_device, predict
from ._types import Config, config_hash
from ._constant import BASELINES, NEURAL_VARIANTS, VARIANTS
from .variants.neural import DuoCast, loss_parts
from .variants.lightgbm import fit_lightgbm

def atomic_checkpoint(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        torch.save(value, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def make_model(cfg: Config, panel, batcher: Batcher, variant: str):
    dimensions = {"n_dynamic": batcher.n_dynamic, "n_mobility": panel.mobility_attr.shape[1]}
    return DuoCast(**dimensions, cfg=cfg.model, variant=variant), dimensions


def train_neural(cfg, panel, splits, scalers, variant, seed, folder: Path, *, resume=False):
    device = resolve_device(cfg.train.device)
    torch.set_num_threads(cfg.train.num_threads)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    generator = np.random.default_rng(seed)
    batcher = Batcher(panel, cfg.data, scalers, device)
    model, dimensions = make_model(cfg, panel, batcher, variant)
    model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.train.lr, weight_decay=cfg.train.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, factor=0.5, patience=3)
    history, first_epoch, stale = [], 1, 0
    best, best_epoch = float("inf"), 0
    common = {"contract_version": CONTRACT_VERSION, "variant": variant, "seed": seed,
              "config_hash": config_hash(cfg), "data_fingerprint": panel.fingerprint,
              "input_schema": input_schema(cfg, panel), "dimensions": dimensions,
              "model_config": cfg.model.model_dump(mode="json"), "config": cfg.model_dump(mode="json"),
              "scalers": scalers, "splits": split_manifest(panel, splits, cfg.data),
              "selection_metric": "validation.loss_log_huber", "deployment_eligible": False}
    if resume:
        checkpoint = load_checkpoint(folder / "last.pt")
        for field in ("config_hash", "data_fingerprint", "variant", "seed", "input_schema"):
            if checkpoint.get(field) != common[field]:
                raise ValueError(f"Cannot resume: checkpoint {field} differs from this trial")
        if not (folder / "best.pt").is_file():
            raise ValueError("Cannot resume without the validation-selected best.pt")
        model.load_state_dict(checkpoint["model_state"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler.load_state_dict(checkpoint["scheduler"])
        history, first_epoch = checkpoint["history"], checkpoint["epoch"] + 1
        best, best_epoch, stale = checkpoint["best_score"], checkpoint["best_epoch"], checkpoint["stale"]
        generator.bit_generator.state = checkpoint["rng_numpy"]
        torch.set_rng_state(checkpoint["rng_torch"])
        if device.type == "cuda" and checkpoint.get("rng_cuda"):
            torch.cuda.set_rng_state_all(checkpoint["rng_cuda"])
    val_truth = panel.target[splits["val"] + 1]
    for epoch in range(first_epoch, cfg.train.epochs + 1):
        if stale >= cfg.train.patience:
            break
        began = time.perf_counter()
        model.train()
        order = generator.permutation(splits["train"])
        if cfg.train.limit_batches is not None:
            order = order[:cfg.train.limit_batches * cfg.train.batch_size]
        total_d, total_s, count = 0.0, 0.0, 0
        for start in range(0, len(order), cfg.train.batch_size):
            ks = order[start:start + cfg.train.batch_size]
            batch = batcher.build(ks)
            optimizer.zero_grad(set_to_none=True)
            output = model(batch)
            loss, demand, supply = loss_parts(output, batch["y"], cfg.train)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.train.grad_clip, error_if_nonfinite=True)
            optimizer.step()
            total_d += demand.item() * len(ks)
            total_s += supply.item() * len(ks)
            count += len(ks)
        val_pred = predict(model, batcher, splits["val"], cfg.train.eval_batch_size)
        metrics = point_metrics(val_pred, val_truth, cfg.evaluation, cfg.train)
        score = metrics["loss_log_huber"]
        scheduler.step(score)
        improved = score < best - cfg.train.min_delta
        if improved:
            best, best_epoch, stale = score, epoch, 0
        else:
            stale += 1
        row = {"epoch": epoch, "train_loss_demand": total_d / count, "train_loss_supply": total_s / count,
               "train_cutoffs_seen": count, "val_loss": score, "val_demand_mae": metrics["demand_mae"],
               "val_supply_mae": metrics["supply_mae"], "lr": optimizer.param_groups[0]["lr"],
               "is_best": improved, "seconds": time.perf_counter() - began}
        history.append(row)
        checkpoint = {**common, "epoch": epoch, "model_state": model.state_dict(),
                      "val_metrics": metrics, "best_score": best, "best_epoch": best_epoch,
                      "stale": stale, "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                      "history": history, "rng_numpy": generator.bit_generator.state,
                      "rng_torch": torch.get_rng_state(),
                      "rng_cuda": torch.cuda.get_rng_state_all() if device.type == "cuda" else []}
        if improved:
            atomic_checkpoint(folder / "best.pt", checkpoint)
        atomic_checkpoint(folder / "last.pt", checkpoint)
        pd.DataFrame(history).to_csv(folder / "history.csv", index=False)
        print(f"{variant} seed={seed} epoch={epoch} val_loss={score:.5f} "
              f"D_MAE={metrics['demand_mae']:.3f} S_MAE={metrics['supply_mae']:.3f}", flush=True)
    if not (folder / "best.pt").exists():
        raise ValueError("No valid checkpoint produced")
    checkpoint = load_checkpoint(folder / "best.pt")
    for field in ("config_hash", "data_fingerprint", "variant", "seed", "input_schema"):
        if checkpoint.get(field) != common[field]:
            raise ValueError(f"Validation-selected checkpoint {field} differs from this trial")
    model.load_state_dict(checkpoint["model_state"])
    return predict(model, batcher, splits["val"], cfg.train.eval_batch_size), {
        "best_epoch": int(checkpoint["epoch"]), "n_params": sum(p.numel() for p in model.parameters()),
        "epochs_completed": len(history), "checkpoint": "best.pt", "device": str(device)}


def prepare(cfg: Config):
    panel = load_panel(cfg.data)
    splits = make_splits(len(panel.timestamps), cfg.data)
    scalers = fit_scalers(panel, splits["train"], cfg.data)
    high = float(np.quantile(panel.target[splits["train"] + 1, :, 0], cfg.evaluation.high_demand_quantile))
    manifest = {"contract_version": CONTRACT_VERSION, "config_hash": config_hash(cfg),
                "data_fingerprint": panel.fingerprint, "dataset_id": panel.metadata["dataset_id"],
                "input_schema": input_schema(cfg, panel), "splits": split_manifest(panel, splits, cfg.data),
                "split_mode": cfg.data.split_mode, "embargo_steps": cfg.data.embargo_steps,
                "scalers": scalers, "high_demand_cut": high,
                "synthetic": panel.metadata.get("synthetic", False), "deployment_eligible": False,
                "availability_validation": cfg.data.availability,
                "scaler_input_bounds": [int(splits["train"][0]) - cfg.data.history + 1, int(splits["train"][-1])],
                "scaler_note": "Adjacency validated as-of first snapshot; dynamic and OD scalers fitted on train inputs only; no geo"}
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.output_dir / "manifest.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if any(old.get(k) != manifest[k] for k in ("contract_version", "config_hash", "data_fingerprint")):
            raise ValueError("Study already exists with different data/config; choose a NEW output_dir")
    else:
        atomic_json(path, manifest)
        atomic_json(cfg.output_dir / "config.json", cfg.model_dump(mode="json"))
    return panel, splits, scalers, high


def trial_folder(cfg, variant, seed):
    if variant not in VARIANTS or not isinstance(seed, int):
        raise ValueError("Invalid variant or seed")
    return cfg.output_dir / variant / f"seed_{seed}"


def trial_incomplete(folder: Path) -> bool:
    """A marker records attempt completion, not whether a process is still alive."""
    path = folder / "training_state.json"
    if not path.is_file():
        return False  # Backward-compatible with earlier completed trial artifacts.
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("status") not in ("RUNNING", "COMPLETED"):
        raise ValueError(f"Invalid training state marker: {folder}")
    return state["status"] != "COMPLETED"


def validate_result(cfg, panel, folder, result):
    """Validate identity and the complete required artifact manifest before reuse."""
    from surge_ml.reports.metrics import FORECAST_METRICS
    if trial_incomplete(folder):
        raise ValueError(f"Trial attempt is incomplete; resume it before selecting: {folder}")
    if not isinstance(result, dict) or (
            result.get("contract_version") != CONTRACT_VERSION
            or result.get("config_hash") != config_hash(cfg)
            or result.get("data_fingerprint") != panel.fingerprint):
        raise ValueError(f"Stale/incompatible trial result: {folder}")
    variant, seed = result.get("variant"), result.get("seed")
    if variant not in VARIANTS or type(seed) is not int or trial_folder(cfg, variant, seed) != folder:
        raise ValueError(f"Trial identity mismatch: {folder}")
    required = ({"best.pt"} if variant in NEURAL_VARIANTS else
                {"demand_5m.txt", "idle_supply_t.txt"} if variant == "lgbm_local" else set())
    hashes = result.get("artifact_sha256")
    if not isinstance(hashes, dict) or set(hashes) != required:
        raise ValueError(f"Incomplete trial artifact manifest: {folder}")
    for name, expected in hashes.items():
        path = folder / name
        if not isinstance(expected, str) or not path.is_file() or digest_file(path) != expected:
            raise ValueError(f"Changed/missing trial artifact: {path}")
    overall = result.get("validation", {}).get("overall", {})
    for metric in ("loss_log_huber", *FORECAST_METRICS):
        value = overall.get(metric)
        if type(value) not in (int, float) or not np.isfinite(value) or value < 0:
            raise ValueError(f"Missing/invalid validation metric {metric}: {folder}")


def ensure_study_unfrozen(cfg: Config) -> None:
    if (cfg.output_dir / "test_report.json").exists() or (cfg.output_dir / "selection.json").exists():
        raise ValueError("Study is frozen for final evaluation; use a new output_dir for additional training")


def run_trial(cfg: Config, variant: str, seed: int, *, resume=False, prepared=None, reuse_completed=False):
    """Fit one trial. A study lock prevents training racing with selection/finalize.

    Benchmark continuation reuses valid completed trials, resumes neural checkpoints,
    and never deletes or restarts partial LightGBM fits implicitly.
    """
    ensure_study_unfrozen(cfg)
    folder = trial_folder(cfg, variant, seed)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    with trial_lock(cfg.output_dir):
        ensure_study_unfrozen(cfg)
        panel, splits, scalers, high = prepared or prepare(cfg)
        result_path = folder / "trial_result.json"
        if (folder / ".training.lock").exists():
            raise ValueError(f"Trial is locked: {folder}; check the existing process before resuming")
        incomplete = trial_incomplete(folder)
        if reuse_completed and result_path.is_file() and not incomplete:
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            validate_result(cfg, panel, folder, saved)
            completed = saved.get("training", {}).get("epochs_completed", 0)
            if variant in NEURAL_VARIANTS and completed < cfg.train.epochs:
                last = load_checkpoint(folder / "last.pt")
                if last["stale"] < cfg.train.patience:
                    resume = True
                else:
                    print(f"Reused early-stopped trial: {folder}", flush=True)
                    return saved
            else:
                print(f"Reused verified trial: {folder}", flush=True)
                return saved
        elif reuse_completed and folder.exists():
            if variant in NEURAL_VARIANTS and (folder / "last.pt").is_file():
                resume = True
            else:
                raise ValueError(f"Cannot resume partial trial without a neural checkpoint: {folder}; use a new study directory")
        if folder.exists() and not resume:
            raise ValueError(f"Trial already exists: {folder}; use --resume or a new study directory")
        if resume and not folder.exists():
            raise ValueError(f"Cannot resume a missing trial: {folder}")
        if resume and variant == "lgbm_local":
            raise ValueError("LightGBM resume is not supported; use a new trial directory")
        if resume and result_path.is_file() and not incomplete:
            validate_result(cfg, panel, folder, json.loads(result_path.read_text(encoding="utf-8")))
        folder.mkdir(parents=True, exist_ok=True)
        with trial_lock(folder):
            state = {"schema_version": "duocast.trial-state.v1", "status": "RUNNING",
                     "variant": variant, "seed": seed, "config_hash": config_hash(cfg),
                     "data_fingerprint": panel.fingerprint}
            atomic_json(folder / "training_state.json", state)
            began = time.perf_counter()
            if variant in NEURAL_VARIANTS:
                pred, info = train_neural(cfg, panel, splits, scalers, variant, seed, folder, resume=resume)
                artifacts = ["best.pt"]
            elif variant == "persistence":
                pred, info = panel.target[splits["val"]].astype(np.float64), {"baseline": "current_observed_counts"}
                artifacts = []
            elif variant in BASELINES:
                if resume:
                    raise ValueError("LightGBM resume is not supported; use a new trial directory")
                pred, info = fit_lightgbm(panel, splits, cfg, variant, seed, folder)
                artifacts = ["demand_5m.txt", "idle_supply_t.txt"]
            else:
                raise ValueError(f"Unknown variant: {variant}")
            report = evaluate(pred, panel.target[splits["val"] + 1], panel, splits["val"],
                              cfg.evaluation, cfg.train, high)
            result = {"contract_version": CONTRACT_VERSION, "config_hash": config_hash(cfg),
                      "data_fingerprint": panel.fingerprint, "variant": variant, "seed": seed,
                      "validation": report, "training": info, "seconds": time.perf_counter() - began,
                      "smoke": cfg.train.limit_batches is not None, "test_evaluated": False,
                      "artifact_sha256": {name: digest_file(folder / name) for name in artifacts}}
            atomic_json(result_path, result)
            atomic_json(folder / "training_state.json", {**state, "status": "COMPLETED"})
            print(f"Saved validation result: {folder}", flush=True)
            return result


def benchmark(cfg, *, resume: bool = False):
    """Train configured models/seeds; --resume safely continues an unfinished study."""
    ensure_study_unfrozen(cfg)
    prepared = prepare(cfg)
    return [run_trial(cfg, variant, seed, prepared=prepared, reuse_completed=resume)
            for variant in cfg.variants for seed in cfg.seeds]
