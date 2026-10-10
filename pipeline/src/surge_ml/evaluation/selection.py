"""Chọn variant chỉ trên val: xếp hạng theo mae_q head chính trung bình qua các seed."""

import json

import numpy as np

from surge_ml.config import Config, config_sha256
from surge_ml.errors import SurgeError
from surge_ml.orchestration.runner import study_dir, write_json


def load_results(cfg: Config) -> list[dict]:
    paths = sorted(study_dir(cfg).glob("*/seed_*/trial_result.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def select(cfg: Config) -> dict:
    results = load_results(cfg)
    if not results:
        raise SurgeError("NO_TRIALS", f"no trial_result.json under {study_dir(cfg)}")
    stale = [(r["variant"], r["seed"]) for r in results if r.get("config_sha256") != config_sha256(cfg, r["variant"])]
    if stale:
        raise SurgeError("STALE_TRIAL", f"trials from a different config: {stale}; use a new study_id")
    missing = sorted({(v, s) for v in cfg.variants for s in cfg.seeds} - {(r["variant"], r["seed"]) for r in results})
    if missing:
        raise SurgeError("INCOMPLETE", f"missing trials (variant, seed): {missing}")
    table = {}
    for r in results:
        row = table.setdefault(r["variant"], {"primary_head": r["primary_head"], "seeds": [], "scores": []})
        row["seeds"].append(r["seed"])
        row["scores"].append(r["val"][r["primary_head"]]["mae_q"])
    for row in table.values():
        row["mean_mae_q"] = float(np.mean(row["scores"]))
        row["std_mae_q"] = float(np.std(row["scores"]))
    ranking = sorted(table, key=lambda v: table[v]["mean_mae_q"])
    selection = {"study_id": cfg.study_id, "metric": "val/<primary>/mae_q", "selected": ranking[0],
                 "ranking": ranking, "variants": table}
    write_json(study_dir(cfg) / "selection.json", selection)
    for v in ranking:
        print(f"{v:16s} {table[v]['primary_head']:6s} mae_q={table[v]['mean_mae_q']:.4f} "
              f"± {table[v]['std_mae_q']:.4f} (n={len(table[v]['scores'])})")
    print(f"selected: {ranking[0]}")
    return selection
