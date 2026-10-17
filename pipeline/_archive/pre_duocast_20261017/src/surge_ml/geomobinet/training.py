"""Validation-selected checkpoints, reproducible resume, and label-free inference."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from uuid import uuid4

import numpy as np
import pandas as pd
import torch

from . import CONTRACT_VERSION
from .batch import Batcher
from .config import Config, ModelConfig, config_hash
from .data import split_manifest
from .metrics import point_metrics
from .model import GeoMobiNet, count_predictions, loss_parts


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_checkpoint(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        torch.save(value, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_checkpoint(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"Checkpoint does not exist: {path}")
    result = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(result, dict) or result.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Incompatible checkpoint: GeoMobiNet demand/idle-supply contract required; legacy log-ratio is rejected")
    return result


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    return device


def input_schema(cfg: Config, panel) -> dict:
    fields = ("dynamic_features", "geo_features", "spatial_features", "mobility_features",
              "nullable_dynamic", "log_dynamic", "log_geo", "log_spatial", "log_mobility",
              "signed_features", "history", "horizon", "timezone")
    return {**{key: getattr(cfg.data, key) for key in fields}, "node_order": panel.hex_ids,
            "target": ["new eligible requests in (t,t+5min]", "idle online eligible drivers at t+5min"],
            "feature_definition_version": panel.metadata.get("feature_definition_version"),
            "geo_version": panel.metadata.get("geo_version"),
            "mobility_semantics": panel.metadata.get("mobility_semantics")}


def make_model(cfg: Config, panel, batcher: Batcher, variant: str):
    dimensions = {"n_dynamic": batcher.n_dynamic, "n_geo": panel.geo.shape[1],
                  "n_spatial": panel.spatial_attr.shape[1], "n_mobility": panel.mobility_attr.shape[1]}
    return GeoMobiNet(**dimensions, cfg=cfg.model, variant=variant), dimensions


@torch.no_grad()
def predict(model, batcher: Batcher, cutoffs, batch_size: int):
    model.eval()
    outputs = []
    for start in range(0, len(cutoffs), batch_size):
        ks = cutoffs[start:start + batch_size]
        output = model(batcher.build(ks, targets=False))
        outputs.append(count_predictions(output).reshape(len(ks), batcher.panel.n_nodes, 2).cpu().numpy())
    if not outputs:
        raise ValueError("No inference cutoffs")
    return np.concatenate(outputs).astype(np.float64)


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
    model.load_state_dict(checkpoint["model_state"])
    return predict(model, batcher, splits["val"], cfg.train.eval_batch_size), {
        "best_epoch": int(checkpoint["epoch"]), "n_params": sum(p.numel() for p in model.parameters()),
        "epochs_completed": len(history), "checkpoint": "best.pt", "device": str(device)}


def predict_checkpoint(cfg: Config, panel, checkpoint_path: Path, cutoffs):
    checkpoint = load_checkpoint(checkpoint_path)
    if checkpoint.get("input_schema") != input_schema(cfg, panel):
        raise ValueError("Inference feature order, node order, target, history, or geo version differs from checkpoint")
    device = resolve_device(cfg.train.device)
    torch.set_num_threads(cfg.train.num_threads)
    batcher = Batcher(panel, cfg.data, checkpoint["scalers"], device)
    model = GeoMobiNet(**checkpoint["dimensions"], cfg=ModelConfig.model_validate(checkpoint["model_config"]),
                       variant=checkpoint["variant"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    return predict(model, batcher, cutoffs, cfg.train.eval_batch_size)
