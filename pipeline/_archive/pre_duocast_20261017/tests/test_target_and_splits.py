import numpy as np
import pytest

from surge_ml.data.target import build_targets, to_ratio
from surge_ml.features import (END_GAP, INBOUND5, LOCAL37, NEIGHBOR3, STRICT32, WARMUP, WINDOW, candidates,
                               shift_target, split_bounds)
from conftest import SPLITS

DAYS_90 = {"train": [1, 63], "val": [64, 76], "test": [77, 90]}


def test_candidate_counts_match_report():
    assert {s: len(candidates(s, SPLITS)) for s in SPLITS} == {"train": 6025, "val": 1129, "test": 1417}


def test_split_bounds_from_manifest_days():
    splits = split_bounds(DAYS_90, 90)
    assert splits == {"train": (0, 18144), "val": (18144, 21888), "test": (21888, 25920)}
    assert {s: len(candidates(s, splits)) for s in splits} == {"train": 18121, "val": 3721, "test": 4009}


@pytest.mark.parametrize("days", [{"train": [1, 63], "val": [63, 76], "test": [77, 90]},  # overlap
                                  {"train": [1, 63], "val": [64, 76], "test": [77, 91]},  # past the data
                                  {"train": [1, 63], "test": [77, 90]}])  # missing split
def test_split_bounds_rejects_bad_days(days):
    with pytest.raises(ValueError):
        split_bounds(days, 90)


def test_windows_and_horizon_stay_inside_split():
    for splits in (SPLITS, split_bounds(DAYS_90, 90)):
        for split, (a, z) in splits.items():
            ks = candidates(split, splits)
            assert ks[0] - (WINDOW - 1) - 11 == a  # demand_mean_60m support of the earliest window row
            assert ks[-1] + END_GAP < z
            assert ks[0] == a + WARMUP


@pytest.mark.parametrize("window", [4, 6])
def test_wider_window_keeps_history_inside_split(window):
    for split, (a, z) in SPLITS.items():
        ks = candidates(split, SPLITS, window)
        assert ks[0] - (window - 1) - 11 == a
        assert ks[-1] + END_GAP < z
    assert len(candidates("val", SPLITS, 6)) == len(candidates("val", SPLITS)) - 2


@pytest.mark.parametrize("horizon", [1, 2, 3])
def test_shift_target_and_loaded_horizon(data, horizon):
    y = shift_target(data.b, horizon)
    np.testing.assert_array_equal(y[:-horizon], data.b[horizon:])
    assert np.isnan(y[-horizon:]).all()
    moved = data.with_temporal(6, horizon)
    assert moved.window == 6 and moved.horizon == horizon and moved.x is data.x
    for split, (a, z) in SPLITS.items():
        ks = moved.candidates(split)
        assert ks[-1] + horizon < z  # target never crosses into the purge or the next split
        np.testing.assert_array_equal(moved.y[ks], data.b[ks + horizon])
    if horizon == 1:
        np.testing.assert_array_equal(moved.y, data.y)  # default horizon reproduces build_targets


@pytest.mark.parametrize("horizon", [0, 4])
def test_shift_target_rejects_unsupported_horizon(horizon):
    with pytest.raises(ValueError):
        shift_target(np.zeros((10, 2)), horizon)


def test_column_routing():
    assert len(LOCAL37) == 37 and not set(NEIGHBOR3) & set(LOCAL37)
    assert len(STRICT32) == 32 and not set(INBOUND5) & set(STRICT32)


def test_target_bypass_and_inverse():
    x = np.zeros((3, 2, 40), np.float32)
    x[:, :, 0] = [[3, 0], [1, 5], [7, 2]]  # demand_5m
    x[:, :, 29] = [[1, 4], [0, 1], [3, 0]]  # effective_supply_t
    x[:, :, 1] = [[0, 0], [1, 1], [2, 2]]  # idle_supply_t
    y, b, b32 = build_targets(x)
    q = (x[..., 0] + 1) / (x[..., 29] + 1)
    np.testing.assert_allclose(b, np.log(q), rtol=1e-6)
    np.testing.assert_allclose(y[:-1], np.log(q[1:]), rtol=1e-6)
    assert np.isnan(y[-1]).all()
    np.testing.assert_allclose(b32, np.log((x[..., 0] + 1) / (x[..., 1] + 1)), rtol=1e-6)
    np.testing.assert_allclose(to_ratio(y[:-1]), q[1:], rtol=1e-6)
    assert (b < 0).any()  # log-ratio is signed
