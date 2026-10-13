"""Unit-level checks for V3 demand DGP and V2 compatibility boundaries."""
from __future__ import annotations

import numpy as np
import pytest

from tools.mock_v3.run import DEFAULT_PROFILE, configuration, load_v3_profile, v3_intents


class GeoStub:
    n = 4
    hex_dist = np.array([
        [0, 1, 2, 1],
        [1, 0, 1, 2],
        [2, 1, 0, 1],
        [1, 2, 1, 0],
    ])


class ExoStub:
    def __init__(self, w=300):
        self.W = w
        self.mu = np.full((w * 5, 4), 1.5, dtype=np.float64)
        self.intents = np.zeros((w * 5, 4), dtype=np.int32)


def test_temporal_demand_deterministic_nonnegative():
    cfg = {"v3_dgp": {"rho": .88, "neighbor_diffusion": .28, "log_intensity_sigma": .42},
           "demand": {"gamma_k": 18}}
    a, b = ExoStub(), ExoStub()
    xa = v3_intents(a, cfg, GeoStub(), seed=42)
    xb = v3_intents(b, cfg, GeoStub(), seed=42)
    assert a.intents.shape == a.mu.shape
    assert np.array_equal(a.intents, b.intents)
    assert np.array_equal(xa["factor"], xb["factor"])
    assert np.isfinite(xa["factor"]).all() and (xa["factor"] > 0).all()
    assert (a.intents >= 0).all()
    assert a.intents.sum() == xa["potential_intents_5m"].sum()


def test_v3_innovations_have_temporal_dependence():
    cfg = {"v3_dgp": {"rho": .88, "neighbor_diffusion": .28, "log_intensity_sigma": .42},
           "demand": {"gamma_k": 18}}
    x = v3_intents(ExoStub(w=1000), cfg, GeoStub(), seed=45)
    latent = x["latent"][:, 0]
    acf = float(np.corrcoef(latent[:-1], latent[1:])[0, 1])
    assert .35 < acf < .995


def test_v3_profile_does_not_modify_v2_defaults():
    profile = load_v3_profile(DEFAULT_PROFILE)
    cfg = configuration(7, 42, profile)
    assert cfg["v3_generator_version"] == "v3_temporal_od_1"
    assert cfg["demand"]["gamma_k"] == 18
    assert cfg["drivers"]["online_scale"] == .50
    assert cfg["split"]["train"] == [1, 5]


def test_bad_v3_profile_is_rejected(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("version: v3_temporal_od_1\ncase: temporal_od\ntemporal_demand: {rho: 1.2, neighbor_diffusion: 0.2, log_intensity_sigma: 0.3}\n")
    with pytest.raises(ValueError):
        load_v3_profile(p)
