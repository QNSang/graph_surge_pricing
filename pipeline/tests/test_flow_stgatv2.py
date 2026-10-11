"""Flow-STGATv2: topology, temporal as-of, dual-head isolation and gradients."""
from dataclasses import replace

import numpy as np
import torch

from surge_ml.config import ModelConfig
from surge_ml.data.batch import make_batch
from surge_ml.features import VARIANTS
from surge_ml.models.dual_gru_gatv2 import build_model, forward_batch
from surge_ml.training.losses import dual_loss, target_mask

SMALL = ModelConfig(
    gru_hidden=8, neighbor_hidden=4, gat_layers=1, gat_heads=2,
    head_hidden=8, dropout=0.0
)


def test_temporal_edge_batch_shapes_and_cutoff(data):
    ks = np.array([100, 200], dtype=np.int64)
    batch = make_batch(data, ks, VARIANTS["flow_stgatv2_full"])
    ei = batch["edge_index"].numpy()
    r = batch["edge_relation"].numpy()
    h, mask = batch["edge_history"].numpy(), batch["edge_history_mask"].numpy()
    n = data.n_nodes
    assert batch["x_local"].shape == (2, 4, n, 37)
    assert h.shape == (ei.shape[1], 4, 10)
    assert mask.shape == (ei.shape[1], 4)
    assert list(np.bincount(r, minlength=3)) == [2 * n, 2, 2 * n]
    assert np.array_equal(ei[0] // n, ei[1] // n)
    real = r != 2
    assert mask[real, -1].all() and not mask[~real].any()
    assert np.allclose(h[real, -1], batch["edge_attr"].numpy()[real, :10])


def test_temporal_edges_are_asof_only(data):
    d = replace(data, edge_attr=data.edge_attr.copy(), _keep={})
    original = make_batch(d, np.array([100]), VARIANTS["flow_stgatv2_full"])
    # Future edge changes must not affect a forecast made at cutoff 100.
    start = int(d.edge_ptr[101])
    d.edge_attr[start:] += 1000
    changed = make_batch(d, np.array([100]), VARIANTS["flow_stgatv2_full"])
    for key in ("edge_index", "edge_attr", "edge_history", "edge_history_mask", "edge_relation"):
        assert torch.equal(original[key], changed[key]), key


def test_edge_history_presence_marks_missing_relation(data):
    d = replace(data, edge_src=data.edge_src.copy(), edge_dst=data.edge_dst.copy(),
                edge_is_adj=data.edge_is_adj.copy(), _keep={})
    # Change only the earlier OD key, preserving the 5 edges per snapshot.
    step = 99
    od = int(d.edge_ptr[step + 1]) - 1
    assert not d.edge_is_adj[od]
    d.edge_dst[od] = (int(d.edge_dst[od]) + 1) % d.n_nodes
    batch = make_batch(d, np.array([100]), VARIANTS["flow_stgatv2_full"])
    od_now = batch["edge_relation"] == 1
    assert od_now.sum().item() == 1
    assert batch["edge_history_mask"][od_now, -2].item() is False
    assert batch["edge_history_mask"][od_now, -1].item() is True


def test_dual_outputs_and_graph_sensitive_to_od_content(data):
    torch.manual_seed(9)
    model = build_model(VARIANTS["flow_stgatv2_full"], SMALL).eval()
    batch = make_batch(data, np.array([100, 101]), VARIANTS["flow_stgatv2_full"])
    with torch.no_grad():
        before = forward_batch(model, batch)
        perturbed = {k: v.clone() for k, v in batch.items()}
        od = perturbed["edge_relation"] == 1
        perturbed["edge_history"][od, :, 8] += 5.0
        after = forward_batch(model, perturbed)
    assert before["local"].shape == before["graph"].shape == (2, data.n_nodes)
    assert torch.equal(before["local"], after["local"])
    assert (before["graph"] - after["graph"]).abs().max().item() > 1e-7


def test_direction_and_relation_ablations(data):
    torch.manual_seed(12)
    model = build_model(VARIANTS["flow_stgatv2_full"], SMALL).eval()
    full = make_batch(data, np.array([100]), VARIANTS["flow_stgatv2_full"])
    self_batch = make_batch(data, np.array([100]), VARIANTS["flow_stgatv2_self"])
    with torch.no_grad():
        full_out = forward_batch(model, full)
        self_out = forward_batch(model, self_batch)
        flipped = {k: v.clone() for k, v in full.items()}
        od = flipped["edge_relation"] == 1
        flipped["edge_index"][:, od] = torch.flip(flipped["edge_index"][:, od], dims=[0])
        flipped_out = forward_batch(model, flipped)
    assert torch.equal(full_out["local"], self_out["local"])
    assert torch.equal(full_out["local"], flipped_out["local"])
    assert (full_out["graph"] - self_out["graph"]).abs().max().item() > 1e-7
    assert (full_out["graph"] - flipped_out["graph"]).abs().max().item() > 1e-7
    assert sum(p.numel() for p in model.parameters()) == sum(
        p.numel() for p in build_model(VARIANTS["flow_stgatv2_self"], SMALL).parameters())


def test_backward_to_edge_temporal_od_and_local(data):
    torch.manual_seed(14)
    model = build_model(VARIANTS["flow_stgatv2_full"], SMALL)
    batch = make_batch(data, np.array([100, 101]), VARIANTS["flow_stgatv2_full"])
    output = forward_batch(model, batch)
    total, parts = dual_loss(output, batch["y"], target_mask(batch["y"], batch["b"]),
                             beta=1.0, lambda_local=0.3)
    assert torch.isfinite(total) and set(parts) == {"graph", "local"}
    total.backward()
    for name, p in (
        ("shared_local_gru", model.encoder.weight_ih_l0),
        ("local_head", model.head_local[0].weight),
        ("edge_history_gru", model.edge_temporal.weight_ih_l0),
        ("inbound_value", model.od_messages.in_value[0].weight),
        ("outbound_value", model.od_messages.out_value[0].weight),
    ):
        assert p.grad is not None and torch.isfinite(p.grad).all(), name
        assert p.grad.norm().item() > 0, name

def test_flow_variant_runs_through_trainer_and_registry(data, cfg, tmp_path):
    from surge_ml.config import config_sha256
    from surge_ml.models.registry import ADAPTERS
    from surge_ml.training.trainer import Trainer

    config = cfg.model_copy(deep=True)
    config.train.epochs = 1
    config.train.scheduler = "none"
    config.train.limit_batches = 1
    config.train.batch_size = 2
    config.train.eval_batch_size = 2
    config.tracking.enabled = False
    variant = VARIANTS["flow_stgatv2_full"]
    sha = config_sha256(config, variant.name)
    out = tmp_path / "flow_model"
    model = build_model(variant, config.model)
    result = Trainer(model, data, variant, config, out, sha, seed=42).fit()
    assert result["epochs_run"] == 1
    assert (out / "best.pt").exists()
    assert (out / "last.pt").exists()
    assert np.isfinite(result["best_score"])
    preds, ks = ADAPTERS[variant.family].predict(
        config, data, variant, out, "val"
    )
    assert len(ks) == 2 and preds["local"].shape == preds["graph"].shape
    assert np.isfinite(preds["graph"]).all()

