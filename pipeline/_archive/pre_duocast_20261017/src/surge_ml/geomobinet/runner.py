"""Prepare -> validation-only trials -> freeze selection -> one final test evaluation."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from . import CONTRACT_VERSION
from .baselines import fit_lightgbm, naive_predictions, predict_lightgbm
from .batch import fit_scalers
from .config import BASELINES, NEURAL_VARIANTS, VARIANTS, Config, config_hash
from .data import STEP, load_panel, make_splits, split_manifest
from .metrics import evaluate
from .training import atomic_json, input_schema, predict_checkpoint, train_neural


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


@contextmanager
def trial_lock(folder: Path):
    lock = folder / ".training.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(f"Trial is locked: {folder}. Check another training process before removing a stale lock") from exc
    try:
        handle.write("GeoMobiNet trial in progress\n")
        handle.close()
        yield
    finally:
        handle.close()
        lock.unlink(missing_ok=True)


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
                "scaler_note": "Static geo/road data validated as-of first snapshot; dynamic and OD fitted on train inputs only"}
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


def validate_result(cfg, panel, folder, result):
    if (result.get("contract_version") != CONTRACT_VERSION or result.get("config_hash") != config_hash(cfg)
            or result.get("data_fingerprint") != panel.fingerprint):
        raise ValueError(f"Stale/incompatible trial result: {folder}")
    for name, expected in result.get("artifact_sha256", {}).items():
        path = folder / name
        if not path.is_file() or digest_file(path) != expected:
            raise ValueError(f"Changed/missing trial artifact: {path}")


def run_trial(cfg: Config, variant: str, seed: int, *, resume=False, prepared=None):
    if (cfg.output_dir / "test_report.json").exists() or (cfg.output_dir / "selection.json").exists():
        raise ValueError("Study is frozen for final evaluation; use a new output_dir for additional training")
    panel, splits, scalers, high = prepared or prepare(cfg)
    folder = trial_folder(cfg, variant, seed)
    if folder.exists() and not resume:
        raise ValueError(f"Trial already exists: {folder}; use --resume or a new study directory")
    if resume and not folder.exists():
        raise ValueError(f"Cannot resume a missing trial: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    with trial_lock(folder):
        began = time.perf_counter()
        if variant in NEURAL_VARIANTS:
            pred, info = train_neural(cfg, panel, splits, scalers, variant, seed, folder, resume=resume)
            artifacts = ["best.pt"]
        elif variant in ("persistence", "seasonal_naive"):
            pred, info = naive_predictions(panel, splits["val"], variant, cfg.evaluation.seasonal_period)
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
        atomic_json(folder / "trial_result.json", result)
        print(f"Saved validation result: {folder}", flush=True)
        return result


def benchmark(cfg):
    prepared = prepare(cfg)
    return [run_trial(cfg, variant, seed, prepared=prepared) for variant in cfg.variants for seed in cfg.seeds]


def collect_results(cfg):
    panel, _, _, _ = prepare(cfg)
    results = []
    for variant in cfg.variants:
        for seed in cfg.seeds:
            folder = trial_folder(cfg, variant, seed)
            path = folder / "trial_result.json"
            if not path.is_file():
                raise ValueError(f"Missing trial: {path}; finish all configured variants/seeds before selection")
            result = json.loads(path.read_text(encoding="utf-8"))
            validate_result(cfg, panel, folder, result)
            if result["variant"] != variant or result["seed"] != seed:
                raise ValueError(f"Trial identity mismatch: {path}")
            results.append(result)
    return results


def validation_table(results):
    rows = []
    for variant in sorted({r["variant"] for r in results}):
        selected = [r for r in results if r["variant"] == variant]
        metrics = [r["validation"]["overall"] for r in selected]
        row = {"variant": variant, "seeds": len(selected)}
        for metric in ("loss_log_huber", "demand_mae", "supply_mae", "ds_proxy_mae"):
            values = [m[metric] for m in metrics]
            row[metric] = float(np.mean(values))
            row[f"{metric}_std"] = float(np.std(values))
        rows.append(row)
    return sorted(rows, key=lambda row: (row["loss_log_huber"], row["variant"]))


def report(cfg):
    rows = validation_table(collect_results(cfg))
    pd.DataFrame(rows).to_csv(cfg.output_dir / "validation_comparison.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    return rows


def select(cfg):
    path = cfg.output_dir / "selection.json"
    if path.exists():
        raise ValueError("Selection is already frozen; do not overwrite it")
    results = collect_results(cfg)
    if "persistence" not in cfg.variants:
        raise ValueError("Frozen comparison must include persistence")
    table = validation_table(results)
    selected = {"contract_version": CONTRACT_VERSION, "config_hash": config_hash(cfg),
                "data_fingerprint": results[0]["data_fingerprint"], "selected_variant": table[0]["variant"],
                "selection_metric": "mean validation loss_log_huber across configured seeds",
                "rankings": table, "trials": [{"variant": r["variant"], "seed": r["seed"],
                    "result_sha256": digest_file(trial_folder(cfg, r["variant"], r["seed"]) / "trial_result.json")}
                    for r in results], "test_access": "finalize_only", "deployment_eligible": False}
    atomic_json(path, selected)
    return selected


def prediction_frame(panel, cutoffs, pred):
    return pd.DataFrame({"cutoff_time": np.repeat(panel.timestamps[cutoffs].astype(str), panel.n_nodes),
                         "target_time": np.repeat((panel.timestamps[cutoffs] + STEP).astype(str), panel.n_nodes),
                         "hex_id": np.tile(panel.hex_ids, len(cutoffs)),
                         "pred_demand": pred[..., 0].reshape(-1),
                         "pred_idle_supply": pred[..., 1].reshape(-1),
                         "ds_proxy": (pred[..., 0] / (pred[..., 1] + 1.0)).reshape(-1)})


def finalize(cfg):
    path = cfg.output_dir / "selection.json"
    if not path.is_file():
        raise ValueError("Run select before touching test predictions")
    if (cfg.output_dir / "test_report.json").exists():
        raise ValueError("This study has already evaluated test; the saved report is immutable")
    selection = json.loads(path.read_text(encoding="utf-8"))
    panel, splits, _, high = prepare(cfg)
    if selection.get("config_hash") != config_hash(cfg) or selection.get("data_fingerprint") != panel.fingerprint:
        raise ValueError("Frozen selection no longer matches data/config")
    results = []
    with trial_lock(cfg.output_dir):
        for trial in selection["trials"]:
            variant, seed = trial["variant"], trial["seed"]
            folder = trial_folder(cfg, variant, seed)
            result_path = folder / "trial_result.json"
            if digest_file(result_path) != trial["result_sha256"]:
                raise ValueError("A trial changed after selection was frozen")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            validate_result(cfg, panel, folder, result)
            ks = splits["test"]
            if variant in NEURAL_VARIANTS:
                pred = predict_checkpoint(cfg, panel, folder / "best.pt", ks)
            elif variant.startswith("lgbm_"):
                pred = predict_lightgbm(panel, ks, cfg, variant, folder)
            else:
                pred, _ = naive_predictions(panel, ks, variant, cfg.evaluation.seasonal_period)
            test = evaluate(pred, panel.target[ks + 1], panel, ks, cfg.evaluation, cfg.train, high)
            results.append({"variant": variant, "seed": seed, "test": test})
            prediction_frame(panel, ks, pred).to_csv(folder / "test_predictions.csv", index=False)
        final = {"contract_version": CONTRACT_VERSION, "selection": selection, "trials": results,
                 "synthetic": panel.metadata.get("synthetic", False), "deployment_eligible": False,
                 "note": "Forecast-only evaluation. No conclusion about surge profitability or causal effects."}
        atomic_json(cfg.output_dir / "test_report.json", final)
    return final


def forecast(cfg, checkpoint_path: Path, *, cutoff: int | None = None, output: Path | None = None):
    panel = load_panel(cfg.data)
    cutoff = len(panel.timestamps) - 1 if cutoff is None else cutoff
    if not cfg.data.history - 1 <= cutoff < len(panel.timestamps):
        raise ValueError("Forecast cutoff is outside the available history")
    ks = np.array([cutoff], dtype=np.int64)
    pred = predict_checkpoint(cfg, panel, checkpoint_path, ks)
    frame = prediction_frame(panel, ks, pred)
    if output is not None:
        output = output.resolve()
        if output.exists():
            raise ValueError(f"Forecast output already exists; choose a new path: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False)
    return frame
