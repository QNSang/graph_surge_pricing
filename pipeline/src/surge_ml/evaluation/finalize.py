"""Đánh giá test một lần cho mọi trial của study; đây là nơi duy nhất đọc test."""

import json

import numpy as np

from surge_ml.config import Config
from surge_ml.data.dataset import DerivedData
from surge_ml.data.derive import prepare
from surge_ml.errors import SurgeError
from surge_ml.evaluation.selection import load_results
from surge_ml.features import VARIANTS
from surge_ml.models.registry import ADAPTERS, score
from surge_ml.orchestration.runner import study_dir, trial_dir, write_json


def finalize(cfg: Config) -> dict:
    root = study_dir(cfg)
    if not (root / "selection.json").is_file():
        raise SurgeError("NOT_SELECTED", "run `surge-ml select` first")
    if (root / "test_report.json").exists():
        raise SurgeError("ALREADY_FINALIZED", f"{root / 'test_report.json'} exists; test is evaluated once")
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    data = DerivedData.load(prepare(cfg), cfg.data.window_steps, cfg.data.horizon_steps)
    trials = []
    for r in load_results(cfg):
        variant = VARIANTS[r["variant"]]
        vcfg = cfg.for_variant(variant.name)
        preds, ks = ADAPTERS[variant.family].predict(vcfg, data, variant, trial_dir(cfg, variant.name, r["seed"]),
                                                     "test")
        test = score(vcfg, data, variant, preds, ks)
        trials.append({"variant": variant.name, "seed": r["seed"], "test": test})
    summary = {}
    for name in {t["variant"] for t in trials}:
        head = VARIANTS[name].primary_head
        rows = [t["test"][head] for t in trials if t["variant"] == name]
        summary[name] = {"primary_head": head, "n_seeds": len(rows), **{
            f"{m}_{stat}": float(fn([row[m] for row in rows]))
            for m in ("mae_q", "rmse_q", "bias_q", "mae_log", "pair_acc", "spearman")
            if all(row.get(m) is not None for row in rows)
            for stat, fn in (("mean", np.mean), ("std", np.std))}}
    report = {"study_id": cfg.study_id, "selected": selection["selected"], "summary": summary, "trials": trials}
    write_json(root / "test_report.json", report)
    for name in sorted(summary, key=lambda v: summary[v]["mae_q_mean"]):
        flag = " <- selected" if name == selection["selected"] else ""
        print(f"{name:16s} test mae_q={summary[name]['mae_q_mean']:.4f} ± {summary[name]['mae_q_std']:.4f}{flag}")
    return report
