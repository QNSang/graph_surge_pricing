"""Fast tests: geography, determinism and a 3-day end-to-end smoke run (dev profile)."""
import os

import numpy as np
import pandas as pd
import pytest

from surge_mock.config import load_config
from surge_mock.pipeline import generate
from surge_mock.rng import stream
from surge_mock.geo import Geo
from surge_mock.writers import read_table


@pytest.fixture(scope="module")
def cfg():
    c = load_config(None, "dev", {})
    c["n_days"] = 3
    c["split"] = {"train": [1, 1], "val": [2, 2], "test": [3, 3]}
    return c


def test_rng_streams_are_reproducible_and_independent():
    a = stream(42, "x").random(5)
    assert np.allclose(a, stream(42, "x").random(5))
    assert not np.allclose(a, stream(42, "y").random(5))


def test_geo_layout(cfg):
    geo = Geo(cfg, stream(cfg.seed, "geo"))
    assert geo.n == 61
    counts = {z: len(geo.hexes_of(z)) for z in ("cbd", "office", "venue", "residential", "airport", "suburb")}
    assert counts == {"cbd": 7, "office": 11, "venue": 1, "residential": 18, "airport": 3, "suburb": 21}


def test_overrides_apply():
    c = load_config(None, "dev", {"demand.scale": 3.0})
    assert c.demand["scale"] == 3.0
    assert c.n_days == 35


@pytest.fixture(scope="module")
def dataset(cfg, tmp_path_factory):
    out = str(tmp_path_factory.mktemp("ds"))
    generate(cfg, out, strengths=[1.0], shuffled=True, log=lambda *_: None)
    return out


def test_layout(dataset):
    assert sorted(d for d in os.listdir(dataset) if d.startswith("g")) == ["g1.0", "g1.0_shuffled"]
    for t in ("orders", "hex_snapshot_5min", "weather_5min", "signal_truth"):
        assert os.path.isdir(os.path.join(dataset, "g1.0", t))


def test_snapshot_timestamps(dataset):
    s = read_table(os.path.join(dataset, "g1.0"), "hex_snapshot_5min")
    ts = np.sort(s["ts"].unique())
    assert ts[0] == np.datetime64("2026-01-05T00:05:00")
    assert ts[-1] == np.datetime64("2026-01-08T00:00:00")
    assert len(ts) == 3 * 288
    assert (np.diff(ts) == np.timedelta64(5, "m")).all()
    assert s.groupby("ts").size().eq(61).all()
    assert s["surge_multiplier"].between(1.0, 3.0).all()
    assert np.allclose(s["surge_multiplier"] * 20, np.round(s["surge_multiplier"] * 20))


def test_orders_are_consistent(dataset):
    o = read_table(os.path.join(dataset, "g1.0"), "orders")
    assert o["order_id"].is_unique
    done = o["dropoff_ts"].notna()
    assert (done == o["pickup_ts"].notna()).all()
    assert not (done & o["cancel_ts"].notna()).any()
    assert (o.loc[done, "dropoff_ts"] > o.loc[done, "pickup_ts"]).all()
    assert (o["accepted_ts"].dropna() >= o.loc[o["accepted_ts"].notna(), "created_ts"]).all()
    assert 0.5 < done.mean() < 1.0


def test_shuffled_only_changes_destinations(dataset):
    a = read_table(os.path.join(dataset, "g1.0"), "orders").sort_values("order_id").reset_index(drop=True)
    b = read_table(os.path.join(dataset, "g1.0_shuffled"), "orders").sort_values("order_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(a.drop(columns="dest_hex"), b.drop(columns="dest_hex"))
    assert (a["dest_hex"] != b["dest_hex"]).mean() > 0.2
    assert sorted(a["dest_hex"]) == sorted(b["dest_hex"])


def test_long_run_timestamps_do_not_overflow(tmp_path):
    """Regression: int32 window index * 300000 ms wrapped on Windows after ~25 days."""
    c = load_config(None, "dev", {"demand.scale": 0.2})
    c["n_days"] = 27
    c["split"] = {"train": [1, 20], "val": [21, 24], "test": [25, 27]}
    generate(c, str(tmp_path), strengths=[1.0], shuffled=False, log=lambda *_: None)
    w = read_table(str(tmp_path), "weather_5min")
    assert w["ts"].is_monotonic_increasing and w["ts"].is_unique
    assert w["ts"].iloc[-1] == np.datetime64("2026-01-05T00:00:00") + np.timedelta64(27, "D")


def test_default_run_is_one_flat_dataset(cfg, tmp_path):
    generate(cfg, str(tmp_path), log=lambda *_: None)
    assert sorted(os.listdir(tmp_path)) == ["_debug", "calendar.json", "config.yaml", "hex_snapshot_5min",
                                            "hexes.parquet", "orders", "signal_truth", "weather_5min"]
