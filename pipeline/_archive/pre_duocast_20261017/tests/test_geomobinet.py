"""Executable acceptance tests for docs/model/model.md (not the legacy ratio model)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import torch

from surge_ml.geomobinet.batch import Batcher, fit_scalers
from surge_ml.geomobinet.config import NEURAL_VARIANTS, ModelConfig, load_config
from surge_ml.geomobinet.data import load_panel, make_splits
from surge_ml.geomobinet.demo import write_demo
from surge_ml.geomobinet.metrics import point_metrics
from surge_ml.geomobinet.model import GeoMobiNet, count_predictions, loss_parts


@pytest.fixture
def sample(tmp_path):
    config_path = write_demo(tmp_path / "data", steps=120, nodes=3)
    cfg = load_config(config_path)
    panel = load_panel(cfg.data)
    splits = make_splits(len(panel.timestamps), cfg.data)
    scalers = fit_scalers(panel, splits["train"], cfg.data)
    return cfg, panel, splits, scalers


def test_target_window_and_graph_batch_alignment(sample):
    cfg, panel, splits, scalers = sample
    batcher = Batcher(panel, cfg.data, scalers)
    ks = splits["train"][:2]
    batch = batcher.build(ks)
    n = panel.n_nodes
    assert batch["x_dyn"].shape == (2 * n, 12, 5)
    np.testing.assert_allclose(batch["y"], panel.target[ks + 1].reshape(-1, 2))
    np.testing.assert_allclose(batch["x_dyn"].reshape(2, n, 12, -1)[:, :, -1], batcher.dynamic[ks])
    for kind in ("spatial", "mobility"):
        edges = batch[f"{kind}_index"]
        assert torch.equal(edges[0] // n, edges[1] // n)
    # At cutoff 12, synthetic OD is reverse-directed; no reverse edge is added.
    k = 12
    directed = batcher.build([k])["mobility_index"].numpy()
    assert set(map(tuple, directed.T)) == {(1, 0), (2, 1)}


@pytest.mark.parametrize("variant", list(NEURAL_VARIANTS))
def test_real_pyg_forward_backward_and_nonnegative_counts(sample, variant):
    cfg, panel, splits, scalers = sample
    batcher = Batcher(panel, cfg.data, scalers)
    batch = batcher.build([12, 13])
    model = GeoMobiNet(batcher.n_dynamic, panel.geo.shape[1], panel.spatial_attr.shape[1],
                       panel.mobility_attr.shape[1], cfg.model, variant)
    output = model(batch)
    assert output.shape == (6, 2)
    assert torch.isfinite(count_predictions(output)).all()
    assert (count_predictions(output) >= 0).all()
    total, _, _ = loss_parts(output, batch["y"], cfg.train)
    total.backward()
    assert model.temporal.weight_ih_l0.grad is not None
    assert model.demand_head[0].weight.grad is not None
    assert model.supply_head[0].weight.grad is not None
    if model.geo_encoder is not None:
        assert model.geo_encoder[0].weight.grad is not None


def test_empty_mobility_and_batch_isolation(sample):
    cfg, panel, _, scalers = sample
    batcher = Batcher(panel, cfg.data, scalers)
    cfg.model.dropout = 0
    model = GeoMobiNet(batcher.n_dynamic, 4, 2, 3, cfg.model).eval()
    first = batcher.build([11])
    assert first["mobility_index"].shape == (2, 0)
    with torch.no_grad():
        single = model(first)
        joined = model(batcher.build([11, 12]))[:panel.n_nodes]
    torch.testing.assert_close(single, joined, atol=1e-6, rtol=1e-5)
    message = model.graph_message(model.mobility_gat, torch.randn(3, cfg.model.hidden),
                                   first["mobility_index"], first["mobility_attr"])
    assert torch.equal(message, torch.zeros_like(message))


def test_latest_inference_does_not_require_future_target(sample):
    cfg, panel, _, scalers = sample
    batcher = Batcher(panel, cfg.data, scalers)
    batch = batcher.build([len(panel.timestamps) - 1], targets=False)
    assert "y" not in batch
    with pytest.raises(ValueError, match="target is unavailable"):
        batcher.build([len(panel.timestamps) - 1])


def test_scalers_never_fit_validation_or_target_rows(sample):
    cfg, panel, splits, scalers = sample
    panel.dynamic[int(splits["train"][-1]) + 1:] = 1e6
    after = fit_scalers(panel, splits["train"], cfg.data)
    assert after == scalers
    train_end_target = splits["train"][-1] + 1
    val_first_input = splits["val"][0] - cfg.data.history + 1
    assert val_first_input > train_end_target


@pytest.mark.parametrize("corruption", ["missing_row", "negative_target", "future_available", "duplicate_row", "nan_target"])
def test_bad_market_input_is_rejected(sample, corruption):
    cfg, _, _, _ = sample
    frame = pd.read_csv(cfg.data.market)
    if corruption == "missing_row":
        frame = frame.iloc[1:]
    elif corruption == "duplicate_row":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif corruption == "negative_target":
        frame.loc[0, "demand_5m"] = -1
    elif corruption == "nan_target":
        frame.loc[0, "idle_supply_t"] = np.nan
    else:
        frame.loc[0, "available_at"] = "2030-01-01T00:00:00+07:00"
    frame.to_csv(cfg.data.market, index=False)
    with pytest.raises(ValueError):
        load_panel(cfg.data)


def test_passenger_od_and_unknown_nodes_are_rejected(sample):
    cfg, _, _, _ = sample
    meta = json.loads(cfg.data.metadata.read_text())
    meta["mobility_semantics"] = "passenger_request_od"
    cfg.data.metadata.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="physical_driver_transitions"):
        load_panel(cfg.data)


def test_nullable_masks_are_stable_and_train_mean_imputation_is_explicit(sample):
    cfg, _, _, _ = sample
    cfg.data.nullable_dynamic = ["eta_sec_t"]
    frame = pd.read_csv(cfg.data.market)
    frame.loc[0, "eta_sec_t"] = np.nan
    frame.to_csv(cfg.data.market, index=False)
    panel = load_panel(cfg.data)
    splits = make_splits(len(panel.timestamps), cfg.data)
    states = fit_scalers(panel, splits["train"], cfg.data)
    batcher = Batcher(panel, cfg.data, states)
    assert batcher.n_dynamic == 6
    assert batcher.dynamic[0, 0, -1] == 0
    assert batcher.dynamic[0, 0, 3] == 0
    assert batcher.dynamic[1, 0, -1] == 1


def test_loss_and_zero_denominator_metrics(sample):
    cfg, _, _, _ = sample
    truth = torch.tensor([[0.0, 0.0], [4.0, 2.0]])
    output = torch.log1p(truth)
    total, _, _ = loss_parts(output, truth, cfg.train)
    assert total.item() == 0
    metrics = point_metrics(np.zeros((2, 2)), np.zeros((2, 2)), cfg.evaluation, cfg.train)
    assert metrics["demand_wape"] is None
    assert metrics["shortage_precision"] is None
    assert metrics["shortage_recall"] is None
    assert metrics["ds_proxy_mae"] == 0


def test_loss_averages_demand_and_supply_equally(sample):
    cfg, _, _, _ = sample
    truth = torch.zeros((1, 2))
    output_log = torch.tensor([[0.2, 0.4]])

    total, demand, supply = loss_parts(output_log, truth, cfg.train)

    assert demand.item() == pytest.approx(0.02)
    assert supply.item() == pytest.approx(0.08)
    assert total.item() == pytest.approx(0.05)

    pred = torch.expm1(output_log).numpy()
    metrics = point_metrics(pred, truth.numpy(), cfg.evaluation, cfg.train)
    assert metrics["loss_log_huber"] == pytest.approx(0.05)


def test_invalid_model_dimensions_rejected():
    with pytest.raises(ValueError, match="divisible"):
        ModelConfig(hidden=7, heads=2)
