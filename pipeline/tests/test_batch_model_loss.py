from dataclasses import replace

import numpy as np
import torch

from surge_ml.config import ModelConfig
from surge_ml.data.batch import make_batch
from surge_ml.features import EDGE_DIM, VARIANTS
from surge_ml.models.dual_gru_gatv2 import build_model, forward_batch
from surge_ml.training.losses import dual_loss, target_mask

SMALL = ModelConfig(gru_hidden=8, neighbor_hidden=4, gat_layers=2, gat_heads=2, head_hidden=8, dropout=0.0)


def test_batch_offsets_and_self_loops(data):
    ks = np.array([100, 200, 300])
    batch = make_batch(data, ks, VARIANTS["gru_gatv2_40"])
    n, ei, ea = data.n_nodes, batch["edge_index"].numpy(), batch["edge_attr"].numpy()
    assert batch["x_local"].shape == (3, 4, n, 37) and batch["x_neighbor"].shape == (3, 4, n, 3)
    assert ea.shape[1] == EDGE_DIM
    assert np.array_equal(ei[0] // n, ei[1] // n)  # no cross-sample edges
    is_self = ea[:, -1] == 1
    assert is_self.sum() == 3 * n and np.array_equal(ei[0, is_self], ei[1, is_self])
    assert len(ei[0]) == 3 * (5 + n)  # 4 adjacency + 1 OD per snapshot + self-loops


def test_relation_ablations_filter_rows(data):
    ks = np.array([500])
    base = VARIANTS["gru_gatv2_40"]
    no_od = make_batch(data, ks, replace(base, relations=("adj",)))["edge_index"].shape[1]
    no_adj = make_batch(data, ks, replace(base, relations=("od",)))["edge_index"].shape[1]
    assert no_od == 4 + data.n_nodes and no_adj == 1 + data.n_nodes


def test_neighbor_columns_do_not_reach_local_head(data):
    torch.manual_seed(0)
    model = build_model(VARIANTS["gru_gatv2_40"], SMALL).eval()
    batch = make_batch(data, np.array([100, 101]), VARIANTS["gru_gatv2_40"])
    out1 = forward_batch(model, batch)
    batch["x_neighbor"] = batch["x_neighbor"] + 5.0
    out2 = forward_batch(model, batch)
    assert torch.equal(out1["local"], out2["local"])
    assert not torch.equal(out1["graph"], out2["graph"])


def test_outputs_can_be_negative(data):
    local_only = replace(VARIANTS["gru_gatv2_40"], graph=False, relations=())
    model = build_model(local_only, SMALL).eval()
    batch = make_batch(data, np.array([100]), local_only)
    batch["b"] = torch.full_like(batch["b"], -10.0)
    assert (forward_batch(model, batch)["local"] < 0).all()


def test_masked_loss():
    y = torch.tensor([[0.5, float("nan")], [1.0, 2.0]])
    b = torch.zeros_like(y)
    out = {"local": torch.zeros_like(y), "graph": torch.ones_like(y)}
    total, parts = dual_loss(out, y, target_mask(y, b), beta=1.0, lambda_local=0.5)
    assert torch.isfinite(total)
    assert torch.isclose(parts["local"], torch.tensor((0.125 + 0.5 + 1.5) / 3))
    assert torch.isclose(total, parts["graph"] + 0.5 * parts["local"])
    assert dual_loss(out, torch.full_like(y, float("nan")), torch.zeros_like(y, dtype=bool), 1.0, 0.5) is None
