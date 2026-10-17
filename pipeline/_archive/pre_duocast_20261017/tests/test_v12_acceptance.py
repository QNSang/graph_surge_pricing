"""Checklist §11 của handoff Dual GRU + GATv2 (V1.2, `gru_gatv2_40`); bổ sung cho test_batch_model_loss.py."""

from pathlib import Path

import numpy as np
import pytest
import torch
import yaml

from surge_ml.config import ModelConfig, apply_overrides, config_sha256
from surge_ml.data.batch import make_batch
from surge_ml.data.scaler import fit_scalers
from surge_ml.features import EDGE_DIM, LOCAL37, NEIGHBOR3, VARIANTS, WINDOW
from surge_ml.models.dual_gru_gatv2 import SurgeNet, build_model, forward_batch
from surge_ml.orchestration.runner import set_seed
from surge_ml.training import checkpoint
from surge_ml.training.losses import dual_loss, target_mask
from surge_ml.training.trainer import Trainer

V12 = VARIANTS["gru_gatv2_40"]
SMALL = ModelConfig(gru_hidden=8, neighbor_hidden=4, gat_layers=2, gat_heads=2, head_hidden=8, dropout=0.0)
CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def _grad_modules(model: SurgeNet) -> dict[str, bool]:
    """Module con -> có ít nhất một tham số nhận gradient khác None."""
    names = ("encoder", "head_local", "neighbor", "fuse", "blocks", "head_graph")
    return {n: any(p.grad is not None for p in getattr(model, n).parameters()) for n in names}


def test_variant_is_original_dual_head():
    assert V12.family == "gru" and V12.graph
    assert V12.relations == ("adj", "od") and V12.columns == "local37" and V12.bypass == "b"
    assert V12.primary_head == "graph"
    assert not set(NEIGHBOR3) & set(LOCAL37) and len(LOCAL37) == 37


def test_reference_config_matches_handoff():
    raw = yaml.safe_load((CONFIGS / "train.yaml").read_text(encoding="utf-8"))
    assert "gru_gatv2_40" in raw["variants"]
    assert raw["model"] == {"gru_hidden": 64, "neighbor_hidden": 16, "gat_layers": 2, "gat_heads": 4,
                            "head_hidden": 64, "dropout": 0.1}
    assert raw["loss"] == {"smooth_l1_beta": 1.0, "lambda_local": 0.3}
    t = raw["train"]
    assert (t["batch_size"], t["eval_batch_size"], t["epochs"], t["lr"], t["weight_decay"]) == (32, 128, 30, 1e-3, 1e-4)
    assert (t["grad_clip_norm"], t["patience"], t["scheduler"]) == (1.0, 5, "cosine")
    assert raw["seeds"] == [42, 43, 44]
    assert raw["data"].get("window_steps", WINDOW) == 4 and raw["data"].get("horizon_steps", 1) == 1


def test_model_structure_and_outputs(data):
    model = build_model(V12, ModelConfig())
    assert type(model) is SurgeNet
    assert len(model.blocks) == 2
    for block in model.blocks:
        conv = block.conv
        assert conv.heads == 4 and conv.add_self_loops is False and conv.edge_dim == EDGE_DIM == 11
    batch = make_batch(data, np.array([100, 101, 102]), V12)
    assert batch["x_local"].shape[1:] == (4, data.n_nodes, 37) and batch["x_neighbor"].shape[-1] == 3
    assert "base_ds" not in batch and "y_ds" not in batch and "edge_history" not in batch
    out = forward_batch(model.eval(), batch)
    assert set(out) == {"local", "graph"}
    assert out["local"].shape == out["graph"].shape == (3, data.n_nodes)


def test_gradient_boundaries(data):
    torch.manual_seed(0)
    model = build_model(V12, SMALL)
    batch = make_batch(data, np.array([100, 101]), V12)
    mask = target_mask(batch["y"], batch["b"])
    total, parts = dual_loss(forward_batch(model, batch), batch["y"], mask, 1.0, 0.3)
    assert torch.isclose(total, parts["graph"] + 0.3 * parts["local"])

    parts["graph"].backward(retain_graph=True)
    g = _grad_modules(model)
    assert g["encoder"] and g["neighbor"] and g["fuse"] and g["blocks"] and g["head_graph"]
    assert not g["head_local"]  # L_G không chạm head local

    model.zero_grad(set_to_none=True)
    parts["local"].backward()
    g = _grad_modules(model)
    assert g["encoder"] and g["head_local"]
    assert not (g["neighbor"] or g["fuse"] or g["blocks"] or g["head_graph"])  # L_L chỉ tới nhánh local


def test_checkpoint_selected_by_val_graph_mae_q(cfg, data, tmp_path):
    cfg = apply_overrides(cfg, epochs=3)
    set_seed(3)
    summary = Trainer(build_model(V12, cfg.model), data, V12, cfg, tmp_path, config_sha256(cfg), 3).fit()
    scores = [row["val/graph/mae_q"] for row in summary["history"]]
    assert summary["best_epoch"] == int(np.argmin(scores))
    assert summary["best_score"] == pytest.approx(min(scores))
    assert checkpoint.load(tmp_path / "best.pt")["epoch"] == summary["best_epoch"]


def test_scaler_fits_train_split_only():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(100, 3, 4)).astype(np.float32)
    ptr = np.arange(101, dtype=np.int64) * 2
    attr = rng.normal(size=(200, 10)).astype(np.float32)
    clean = fit_scalers(x, attr, ptr, (40, 70), 1e-6)
    x[:40] += 1e3  # ngày trước train không được ảnh hưởng scaler
    attr[:80] += 1e3
    s = fit_scalers(x, attr, ptr, (40, 70), 1e-6)
    for key in clean:
        assert np.allclose(s[key], clean[key])
    assert np.allclose(s["node_mean"], x[40:70].reshape(-1, 4).mean(0), atol=1e-5)
    assert np.allclose(s["edge_mean"], attr[80:140].mean(0), atol=1e-5)
