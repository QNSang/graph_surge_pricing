from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from surge_ml._constant import CONTRACT_VERSION
from surge_ml._utils.io import atomic_json, digest_file, trial_lock
from surge_ml.train.duocast._types import config_hash
from surge_ml.train.duocast._constant import NEURAL_VARIANTS, MODEL_LABELS
from surge_ml.train.duocast.train import prepare, trial_folder, validate_result
from surge_ml.train.duocast.variants.lightgbm import predict_lightgbm
from surge_ml.inferences.duocast import predict_checkpoint, prediction_frame
from .metrics import FORECAST_METRICS, evaluate
from surge_ml.train.duocast._constant import MAIN_VARIANTS


def export_forecast_table(folder: Path, rows: list[dict], split: str) -> None:
    """Export the user's six metrics, mean/std across seeds, in fixed model order."""
    labels = ('D-MAE', 'S-MAE', 'Log D-MAE', 'Log S-MAE', 'Log D/S MAE', 'Log D/S RMSE')
    order = {variant: i for i, variant in enumerate((*MAIN_VARIANTS, 'persistence'))}
    records, markdown = [], ['| Model | ' + ' | '.join(label + ' (mean +/- std)' for label in labels) + ' |',
                            '|---|' + '---|' * len(labels)]
    for row in sorted(rows, key=lambda r: order.get(r['variant'], 999)):
        name = MODEL_LABELS[row['variant']]
        record = {'Model': name, 'variant': row['variant'], 'seeds': row['seeds']}
        values = []
        for key, label in zip(FORECAST_METRICS, labels):
            record[label], record[label + ' std'] = row[key], row[key + '_std']
            values.append(f"{row[key]:.6f} +/- {row[key + '_std']:.6f}")
        records.append(record)
        markdown.append('| ' + name + ' | ' + ' | '.join(values) + ' |')
    pd.DataFrame(records).to_csv(folder / f'forecast_{split}_comparison.csv', index=False)
    header = (f'# Forecast comparison: {split}\n\n'
              'Metrics use raw D/S counts and log1p counts. Log D/S = log((D+1)/(S+1)).\n'
              'Standard deviation is population SD across the configured seeds (ddof=0).\n'
              'The data kind is recorded in manifest.json; synthetic results are software tests, not accuracy claims.\n\n')
    (folder / f'forecast_{split}_comparison.md').write_text(header + '\n'.join(markdown) + '\n', encoding='utf-8')

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
        for metric in ("loss_log_huber", *FORECAST_METRICS, "ds_proxy_mae"):
            values = [m[metric] for m in metrics]
            row[metric] = float(np.mean(values))
            row[f"{metric}_std"] = float(np.std(values))
        rows.append(row)
    return sorted(rows, key=lambda row: (row["loss_log_huber"], row["variant"]))


def report(cfg):
    rows = validation_table(collect_results(cfg))
    pd.DataFrame(rows).to_csv(cfg.output_dir / "validation_comparison.csv", index=False)
    export_forecast_table(cfg.output_dir, rows, 'validation')
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    return rows


def select(cfg):
    """Freeze validation rankings while holding the same study lock as training."""
    path = cfg.output_dir / "selection.json"
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    with trial_lock(cfg.output_dir):
        if path.exists() or (cfg.output_dir / "test_report.json").exists():
            raise ValueError("Selection is already frozen; do not overwrite it")
        results = collect_results(cfg)
        if not {"lgbm_local", "persistence"}.intersection(cfg.variants):
            raise ValueError("Frozen comparison must include a baseline")
        for result in results:
            folder = trial_folder(cfg, result["variant"], result["seed"])
            if (folder / ".training.lock").exists():
                raise ValueError(f"Cannot select while trial is locked: {folder}")
        table = validation_table(results)
        selected = {"contract_version": CONTRACT_VERSION, "config_hash": config_hash(cfg),
                    "data_fingerprint": results[0]["data_fingerprint"], "selected_variant": table[0]["variant"],
                    "selection_metric": "mean validation loss_log_huber across configured seeds",
                    "rankings": table, "trials": [{"variant": r["variant"], "seed": r["seed"],
                        "result_sha256": digest_file(trial_folder(cfg, r["variant"], r["seed"]) / "trial_result.json")}
                        for r in results], "test_access": "finalize_only", "deployment_eligible": False}
        atomic_json(path, selected)
        return selected


def _validated_frozen_trials(cfg, panel, selection):
    """Check every frozen trial BEFORE any test prediction or metric is produced."""
    expected = {(variant, seed) for variant in cfg.variants for seed in cfg.seeds}
    trials = selection.get("trials")
    if not isinstance(trials, list) or any(not isinstance(t, dict) for t in trials):
        raise ValueError("Invalid frozen trial list")
    pairs = [(t.get("variant"), t.get("seed")) for t in trials]
    if len(pairs) != len(expected) or set(pairs) != expected:
        raise ValueError("Configured model/seed set differs from frozen selection")
    validated = []
    for trial in trials:
        folder = trial_folder(cfg, trial["variant"], trial["seed"])
        if (folder / ".training.lock").exists():
            raise ValueError(f"Frozen trial is locked: {folder}")
        path = folder / "trial_result.json"
        if not path.is_file() or digest_file(path) != trial.get("result_sha256"):
            raise ValueError("A trial changed after selection was frozen")
        result = json.loads(path.read_text(encoding="utf-8"))
        validate_result(cfg, panel, folder, result)
        validated.append((folder, result))
    rankings = validation_table([result for _, result in validated])
    if selection.get("rankings") != rankings or selection.get("selected_variant") != rankings[0]["variant"]:
        raise ValueError("Frozen validation ranking or winner was modified")
    return validated


def finalize(cfg):
    path = cfg.output_dir / "selection.json"
    if not path.is_file():
        raise ValueError("Run select before touching test predictions")
    with trial_lock(cfg.output_dir):
        if (cfg.output_dir / "test_report.json").exists():
            raise ValueError("This study has already evaluated test; the saved report is immutable")
        selection = json.loads(path.read_text(encoding="utf-8"))
        panel, splits, _, high = prepare(cfg)
        if (selection.get("contract_version") != CONTRACT_VERSION
                or selection.get("config_hash") != config_hash(cfg)
                or selection.get("data_fingerprint") != panel.fingerprint):
            raise ValueError("Frozen selection no longer matches data/config")
        frozen = _validated_frozen_trials(cfg, panel, selection)
        results = []
        for folder, result in frozen:
            variant, seed = result["variant"], result["seed"]
            ks = splits["test"]
            if variant in NEURAL_VARIANTS:
                pred = predict_checkpoint(cfg, panel, folder / "best.pt", ks)
            elif variant.startswith("lgbm_"):
                pred = predict_lightgbm(panel, ks, cfg, variant, folder)
            else:
                pred = panel.target[ks].astype(np.float64)
            test = evaluate(pred, panel.target[ks + 1], panel, ks, cfg.evaluation, cfg.train, high)
            results.append({"variant": variant, "seed": seed, "test": test})
            prediction_frame(panel, ks, pred).to_csv(folder / "test_predictions.csv", index=False)
        final = {"contract_version": CONTRACT_VERSION, "selection": selection, "trials": results,
                 "synthetic": panel.metadata.get("synthetic", False), "deployment_eligible": False,
                 "note": "Forecast-only evaluation. No conclusion about surge profitability or causal effects."}
        comparison = validation_table([{'variant': r['variant'], 'seed': r['seed'], 'validation': r['test']} for r in results])
        export_forecast_table(cfg.output_dir, comparison, 'test')
        atomic_json(cfg.output_dir / "test_report.json", final)
        return final
