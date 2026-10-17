"""Grid search siêu tham số của một variant, chấm trên val (không đọc test); kết quả nằm trong runs/<study>/_sweep/."""

import hashlib
import itertools
import json
from typing import Any

import numpy as np
import yaml
from pydantic import ValidationError

from surge_ml.config import OVERRIDABLE, Config, config_sha256
from surge_ml.data.dataset import DerivedData
from surge_ml.errors import SurgeError
from surge_ml.features import VARIANTS
from surge_ml.orchestration.runner import run_prepare, run_trial, study_dir, write_json


def _value(text: str) -> Any:
    value = yaml.safe_load(text)
    if isinstance(value, str):  # YAML 1.1 reads "1e-3" as a string
        try:
            return float(value)
        except ValueError:
            pass
    return value


def parse_grid(items: list[str]) -> dict[str, list]:
    """Đổi ["model.gru_hidden=32,64", ...] thành dict lưới tham số."""
    grid = {}
    for item in items:
        key, sep, values = item.partition("=")
        section, dot, field = key.partition(".")
        if not sep or not dot or not values or section not in OVERRIDABLE:
            raise SurgeError("CONFIG", f"bad --grid {item!r}; expected <section>.<field>=v1,v2 with section in "
                                       f"{OVERRIDABLE}")
        grid[key] = [_value(v) for v in values.split(",")]
    return grid


def with_point(cfg: Config, variant: str, point: dict[str, Any]) -> Config:
    """Trả cfg với điểm `point` gộp vào overrides[variant]; trường sai báo lỗi như yaml sai."""
    d = cfg.model_dump()
    patch = {s: dict(v) for s, v in d["overrides"].get(variant, {}).items()}
    for key, value in point.items():
        section, field = key.split(".", 1)
        patch.setdefault(section, {})[field] = value
    d["overrides"][variant] = patch
    try:
        return Config.model_validate(d)
    except ValidationError as exc:
        raise SurgeError("CONFIG", f"sweep point {point}: {exc}") from exc


def tag(point: dict[str, Any]) -> str:
    return ",".join(f"{k}={v}" for k, v in point.items()) or "base"


def point_id(point: dict[str, Any]) -> str:
    return "p_" + hashlib.sha1(json.dumps(point, sort_keys=True).encode()).hexdigest()[:8]


def to_markdown(out: dict) -> str:
    lines = [f"# Sweep — {out['variant']} ({out['study_id']}, validation only)", "",
             "| Rank | Point | MAE_q ↓ | Train s | Seeds |", "|---:|---|---:|---:|---:|"]
    for i, r in enumerate(out["points"], 1):
        std = f" ± {r['mae_q_std']:.4f}" if len(r["seeds"]) > 1 else ""
        lines.append(f"| {i} | {r['tag']} | {r['mae_q_mean']:.4f}{std} | {r['train_seconds_mean']:.0f} | "
                     f"{len(r['seeds'])} |")
    best = out["points"][0]
    snippet = yaml.safe_dump({"overrides": {out["variant"]: best["override"]}}, default_flow_style=None,
                             sort_keys=False)
    lines += ["", "Best point as a `train.yaml` block:", "", "```yaml", snippet.rstrip(), "```", "",
              "The ranking is picked on val, so the best score is optimistic. Paste the block, then confirm with "
              "`surge-ml benchmark` (all seeds) and `surge-ml report`.", ""]
    return "\n".join(lines)


def sweep(cfg: Config, variant: str, grid: dict[str, list], seeds: list[int]) -> dict:
    if variant not in VARIANTS:
        raise SurgeError("CONFIG", f"unknown variant {variant!r}; known: {list(VARIANTS)}")
    points = [dict(zip(grid, combo)) for combo in itertools.product(*grid.values())]
    configs = [with_point(cfg, variant, p) for p in points]  # validate every point before training any
    root = study_dir(cfg) / "_sweep" / variant
    head = VARIANTS[variant].primary_head
    data = DerivedData.load(run_prepare(cfg), cfg.data.window_steps, cfg.data.horizon_steps)
    rows = []
    for point, pcfg in zip(points, configs):
        results = []
        write_json(root / point_id(point) / "point.json", point)
        for seed in seeds:
            out = root / point_id(point) / f"seed_{seed}"
            done = out / "trial_result.json"
            if done.exists() and json.loads(done.read_text(encoding="utf-8"))["config_sha256"] == \
                    config_sha256(pcfg, variant):
                print(f"skip {tag(point)} seed {seed}: done")
                results.append(json.loads(done.read_text(encoding="utf-8")))
            else:  # missing, interrupted or from another config: retrain (the old dir is archived)
                results.append(run_trial(pcfg, data, VARIANTS[variant], seed, out=out))
        mae = [r["val"][head]["mae_q"] for r in results]
        rows.append({"tag": tag(point), "id": point_id(point), "point": point, "override": pcfg.overrides[variant], "seeds": seeds,
                     "mae_q": mae, "mae_q_mean": float(np.mean(mae)), "mae_q_std": float(np.std(mae)),
                     "train_seconds_mean": float(np.mean([r.get("train_seconds", 0.0) for r in results]))})
    rows.sort(key=lambda r: r["mae_q_mean"])
    out = {"study_id": cfg.study_id, "variant": variant, "metric": f"val/{head}/mae_q", "grid": grid, "points": rows}
    write_json(root / "sweep.json", out)
    (root / "sweep.md").write_text(to_markdown(out), encoding="utf-8")
    for r in rows:  # ASCII only: Windows consoles may not be UTF-8
        print(f"{r['mae_q_mean']:.4f}  {r['tag']}")
    print(f"best: {rows[0]['tag']}")
    print(f"written: {root / 'sweep.md'}")
    return out
