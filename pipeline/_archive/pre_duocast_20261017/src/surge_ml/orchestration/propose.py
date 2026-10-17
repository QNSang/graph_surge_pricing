"""Sinh đề xuất surge demo/shadow có thể kiểm toán từ một checkpoint graph đã huấn luyện."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch

from surge_ml.config import Config, config_sha256
from surge_ml.controller import apply_surge_controller
from surge_ml.data.dataset import DerivedData
from surge_ml.data.derive import prepare
from surge_ml.errors import SurgeError
from surge_ml.features import IDX_CURRENT_SURGE, VARIANTS, Variant
from surge_ml.models.dual_gru_gatv2 import build_model
from surge_ml.orchestration.runner import trial_dir
from surge_ml.training import checkpoint
from surge_ml.training.trainer import predict, resolve_device

SCHEMA_VERSION = "surge_proposal_v1"
INDEX_SCHEMA_VERSION = "surge_proposal_index_v1"


@dataclass
class ProposalContext:
    """Mọi thứ cần để dự báo và chạy controller, nạp một lần cho nhiều cutoff."""

    cfg: Config
    variant_name: str
    variant: Variant
    seed: int
    checkpoint_path: Path
    config_sha: str
    data: DerivedData
    model: torch.nn.Module
    device: torch.device
    raw_x: np.ndarray  # [T, N, 40] chưa chuẩn hoá; bidding lấy từ đây
    derived_dir: Path
    source_manifest: dict


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


def load_context(cfg: Config, variant_name: str, seed: int) -> ProposalContext:
    """Kiểm checkpoint khớp contract hiện tại rồi nạp dữ liệu derived và model."""
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
    vcfg = cfg.for_variant(variant_name)
    model = build_model(variant, vcfg.model)
    model.load_state_dict(saved["model"])
    device = resolve_device(vcfg.train.device)
    source_manifest_path = cfg.data.source_root / "meta" / "manifest.json"
    return ProposalContext(
        cfg=cfg,
        variant_name=variant_name,
        variant=variant,
        seed=seed,
        checkpoint_path=checkpoint_path,
        config_sha=expected_sha,
        data=data,
        model=model.to(device),
        device=device,
        raw_x=np.load(derived / "x.npy", mmap_mode="r"),
        derived_dir=derived,
        source_manifest=json.loads(source_manifest_path.read_text(encoding="utf-8")),
    )


def _cutoff_ts(ctx: ProposalContext, cutoff: int) -> datetime:
    return datetime.fromisoformat(ctx.data.manifest["first_ts"]) + timedelta(minutes=5 * cutoff)


def build_report(ctx: ProposalContext, cutoff: int, local: np.ndarray, graph: np.ndarray) -> dict:
    """Chạy controller trên dự báo [N] của một cutoff và đóng gói theo `surge_proposal_v1`."""
    cfg = ctx.cfg
    bidding = np.asarray(ctx.raw_x[cutoff, :, IDX_CURRENT_SURGE], dtype=np.float64)
    controlled = apply_surge_controller(local, graph, bidding, cfg.controller)
    manifest = ctx.data.manifest
    rows = []
    for i, hex_id in enumerate(manifest["hex_ids"]):
        rows.append({"hex_id": hex_id, **{
            key: _json_scalar(values[i]) for key, values in controlled.items()
        }})
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": cfg.study_id,
        "variant": ctx.variant_name,
        "seed": ctx.seed,
        "checkpoint": str(ctx.checkpoint_path),
        "config_sha256": ctx.config_sha,
        "dataset_id": manifest["dataset_id"],
        "data_fingerprint": ctx.source_manifest.get("data_fingerprint"),
        "derived_dir": str(ctx.derived_dir),
        "split": _split_for_cutoff(ctx.data, cutoff),
        "cutoff_index": cutoff,
        "cutoff_ts_local": _cutoff_ts(ctx, cutoff).isoformat(),
        "source_timezone": ctx.source_manifest.get("timezone", "Asia/Ho_Chi_Minh"),
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


def _forecast(ctx: ProposalContext, ks: np.ndarray) -> dict[str, np.ndarray]:
    preds, used = predict(ctx.model, ctx.data, ctx.variant, ks, ctx.cfg.train.eval_batch_size, ctx.device)
    if used.tolist() != ks.tolist() or "local" not in preds or "graph" not in preds:
        raise SurgeError("FORECAST", "paired local/graph forecasts were not produced for the requested cutoffs")
    return preds


def generate_proposals(
    cfg: Config,
    variant_name: str,
    seed: int,
    cutoff: int,
    output: Path | None = None,
) -> tuple[dict, Path]:
    """Chạy một cutoff hợp lệ qua dự báo và bộ điều khiển surge demo/shadow."""
    ctx = load_context(cfg, variant_name, seed)
    _split_for_cutoff(ctx.data, cutoff)
    preds = _forecast(ctx, np.array([cutoff], dtype=np.int64))
    report = build_report(ctx, cutoff, preds["local"][0], preds["graph"][0])
    path = output or ctx.checkpoint_path.parent / "surge" / f"proposals_k{cutoff}.json"
    _write_json(path, report)
    return report, path


def resolve_cutoffs(
    data: DerivedData,
    split: str | None = None,
    from_cutoff: int | None = None,
    to_cutoff: int | None = None,
    stride: int = 1,
) -> np.ndarray:
    """Danh sách cutoff hợp lệ: cả split, hoặc dải [from, to] (mỗi cutoff phải nằm trong một split)."""
    if stride < 1:
        raise SurgeError("CONFIG", f"stride must be >= 1, got {stride}")
    if split is not None:
        if split not in data.splits:
            raise SurgeError("CONFIG", f"unknown split {split!r}; known: {list(data.splits)}")
        ks = data.candidates(split)
    else:
        if from_cutoff is None or to_cutoff is None or to_cutoff < from_cutoff:
            raise SurgeError("CONFIG", "a cutoff range needs --from-cutoff <= --to-cutoff")
        ks = np.arange(from_cutoff, to_cutoff + 1, dtype=np.int64)
        for k in (int(ks[0]), int(ks[-1])):
            _split_for_cutoff(data, k)
        eligible = np.concatenate([data.candidates(s) for s in data.splits])
        ks = ks[np.isin(ks, eligible)]
    ks = ks[::stride]
    if not len(ks):
        raise SurgeError("CUTOFF", "no eligible cutoffs in the requested range")
    return ks


def write_proposal_range(ctx: ProposalContext, ks: np.ndarray, out_dir: Path) -> Path:
    """Dự báo theo lô cho mọi cutoff, ghi một `proposals_k{k}.json` mỗi cutoff và một `index.json`."""
    preds = _forecast(ctx, ks)
    entries = []
    for i, k in enumerate(ks.tolist()):
        report = build_report(ctx, k, preds["local"][i], preds["graph"][i])
        name = f"proposals_k{k}.json"
        _write_json(out_dir / name, report)
        entries.append({"cutoff_index": k, "cutoff_ts_local": report["cutoff_ts_local"],
                        "split": report["split"], "file": name})
    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "study_id": ctx.cfg.study_id,
        "variant": ctx.variant_name,
        "seed": ctx.seed,
        "config_sha256": ctx.config_sha,
        "data_fingerprint": ctx.source_manifest.get("data_fingerprint"),
        "count": len(entries),
        "first_cutoff_ts_local": entries[0]["cutoff_ts_local"],
        "last_cutoff_ts_local": entries[-1]["cutoff_ts_local"],
        "cutoffs": entries,
    }
    path = out_dir / "index.json"
    _write_json(path, index)
    return path


def generate_proposal_range(
    cfg: Config,
    variant_name: str,
    seed: int,
    *,
    split: str | None = None,
    from_cutoff: int | None = None,
    to_cutoff: int | None = None,
    stride: int = 1,
    out_dir: Path | None = None,
) -> Path:
    """Nạp checkpoint một lần rồi sinh đề xuất cho cả split hoặc một dải cutoff; trả đường dẫn `index.json`."""
    ctx = load_context(cfg, variant_name, seed)
    ks = resolve_cutoffs(ctx.data, split, from_cutoff, to_cutoff, stride)
    return write_proposal_range(ctx, ks, out_dir or ctx.checkpoint_path.parent / "surge")
