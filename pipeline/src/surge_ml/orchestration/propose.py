"""Sinh đề xuất surge demo/shadow có thể kiểm toán từ một checkpoint graph đã huấn luyện."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from surge_ml.config import Config, config_sha256
from surge_ml.controller import apply_surge_controller
from surge_ml.data.dataset import DerivedData
from surge_ml.data.derive import prepare
from surge_ml.errors import SurgeError
from surge_ml.features import IDX_CURRENT_SURGE, VARIANTS
from surge_ml.models.dual_gru_gatv2 import build_model
from surge_ml.orchestration.runner import trial_dir
from surge_ml.training import checkpoint
from surge_ml.training.trainer import predict, resolve_device


def _split_for_cutoff(data: DerivedData, cutoff: int) -> str:
    for split in data.splits:
        ks = data.candidates(split)
        if len(ks) and int(ks[0]) <= cutoff <= int(ks[-1]):
            return split
    raise SurgeError("CUTOFF", f"cutoff {cutoff} is outside the eligible W{data.window} sample index")


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def generate_proposals(
    cfg: Config,
    variant_name: str,
    seed: int,
    cutoff: int,
    output: Path | None = None,
) -> tuple[dict, Path]:
    """Chạy một cutoff hợp lệ qua dự báo và bộ điều khiển surge demo/shadow."""
    variant = VARIANTS.get(variant_name)
    if variant is None or not variant.graph:
        raise SurgeError("CONFIG", "surge proposals require a graph variant with local and graph heads")
    trial = trial_dir(cfg, variant_name, seed)
    checkpoint_path = trial / "best.pt"
    if not checkpoint_path.is_file():
        raise SurgeError("CHECKPOINT", f"checkpoint not found: {checkpoint_path}")
    saved = checkpoint.load(checkpoint_path)
    expected_sha = config_sha256(cfg, variant_name)
    if saved.get("config_sha256") != expected_sha:
        raise SurgeError("STALE_CHECKPOINT", "checkpoint config does not match the current dataset/model contract")

    derived = prepare(cfg)
    data = DerivedData.load(derived, cfg.data.window_steps, cfg.data.horizon_steps)
    split = _split_for_cutoff(data, cutoff)
    vcfg = cfg.for_variant(variant_name)
    model = build_model(variant, vcfg.model)
    model.load_state_dict(saved["model"])
    device = resolve_device(vcfg.train.device)
    preds, used = predict(model.to(device), data, variant, np.array([cutoff]), 1, device)
    if used.tolist() != [cutoff] or "local" not in preds or "graph" not in preds:
        raise SurgeError("FORECAST", "paired local/graph forecasts were not produced for the requested cutoff")

    raw_x = np.load(derived / "x.npy", mmap_mode="r")
    bidding = np.asarray(raw_x[cutoff, :, IDX_CURRENT_SURGE], dtype=np.float64)
    controlled = apply_surge_controller(preds["local"][0], preds["graph"][0], bidding, cfg.controller)

    manifest = data.manifest
    source_manifest_path = cfg.data.source_root / "meta" / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    first_ts = datetime.fromisoformat(manifest["first_ts"])
    cutoff_ts = first_ts + timedelta(minutes=5 * cutoff)
    rows = []
    for i, hex_id in enumerate(manifest["hex_ids"]):
        rows.append({"hex_id": hex_id, **{
            key: _json_scalar(values[i]) for key, values in controlled.items()
        }})

    report = {
        "schema_version": "surge_proposal_v1",
        "study_id": cfg.study_id,
        "variant": variant_name,
        "seed": seed,
        "checkpoint": str(checkpoint_path),
        "config_sha256": expected_sha,
        "dataset_id": manifest["dataset_id"],
        "data_fingerprint": source_manifest.get("data_fingerprint"),
        "derived_dir": str(derived),
        "split": split,
        "cutoff_index": cutoff,
        "cutoff_ts_local": cutoff_ts.isoformat(),
        "source_timezone": source_manifest.get("timezone", "Asia/Ho_Chi_Minh"),
        "forecast_horizon_minutes": cfg.data.horizon_minutes,
        "window_steps": cfg.data.window_steps,
        "target_contract": "log((D+1)/(S_eff+1)); inverse=exp",
        "execution_mode": cfg.controller.execution_mode,
        "policy_version": cfg.controller.policy_version,
        "reference_version": cfg.controller.reference_version,
        "controller_calibrated": cfg.controller.calibrated,
        "deployment_eligible": False,
        "policy": cfg.controller.model_dump(mode="json"),
        "proposals": rows,
    }
    path = output or trial / "surge" / f"proposals_k{cutoff}.json"
    _write_json(path, report)
    return report, path
