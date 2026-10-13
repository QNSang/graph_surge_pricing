"""Create a new Mock V3 dataset from the bounded D/S contract.

Commands from repository root:
    python tools/mock_v3/run.py --mode calibrate --days 7 --out artifacts/mock_v3_calibration_7d
    python tools/mock_v3/run.py --mode release --days 90 --out data/staging/hcm_mock_v3_90d_seed42_temporal_od

V3 keeps the v2.1 physical node/edge feature contract, but changes the *demand
generating process* and driver-calibration inputs upstream of the state simulator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import importlib.metadata as importlib_metadata
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mock_data_pipeline"))

import numpy as np
import pandas as pd
import yaml
from surge_mock.calendar_gen import build_calendar
from surge_mock.dataset_v2 import (
    DS_RATIO_MAX, basic_metrics, demand_supply_frame, observed_tables, validate_raw,
)
from surge_mock.exogenous import Exogenous
from surge_mock.geo import Geo
from surge_mock.rng import stream
from surge_mock.simulate import run_simulation
from surge_mock.config import load_config

DEFAULT_PROFILE = ROOT / "tools/mock_v3/profile.yaml"


# Bounded D/S tail case (7-day calibration, see README): booking thins once
# (window requests + 1) / supply left after the booking exceeds theta.
BASE_OVERRIDES = {
    'drivers.reposition.prob': 0.35, 'drivers.reposition.power': 4.0,
    'drivers.online_scale': 0.50, 'demand.scale': 1.8,
    'signals.s1_ramp.range': [2.2, 2.8], 'signals.s1_ramp.lead_min': 15, 'signals.s1_ramp.decay_min': 25,
    'demand.no_cars_filter.theta': 12.0, 'demand.no_cars_filter.beta': 3.0, 'demand.no_cars_filter.floor': 0.2}


def log(*s):
    print(*s, flush=True)


def base_configuration(days: int, seed: int):
    cfg = load_config(None, 'full', BASE_OVERRIDES)
    cfg['seed'] = seed
    cfg['n_days'] = days
    cfg['profile'] = f'training_v2_{days}d' if days >= 30 else 'development_v2'
    if days >= 30:
        # Only spreads rain/venue days across periods; the model split belongs to DS.
        tr, va = days*70//100, days*15//100   # integer math: .70*90 is 62.999...
        cfg['split'] = {'train': [1, tr], 'val': [tr+1, tr+va], 'test': [tr+va+1, days]}
    else:
        assert days >= 3
        cfg['split'] = {'train': [1, days-2], 'val': [days-1, days-1], 'test': [days, days]}
    cfg['rain']['days'] = min(days, max(3, round(days/6)))
    cfg['signals']['s4']['events'] = min(days, max(3, round(days/8)))
    return cfg


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False, default=str), encoding='utf-8')


def save_raw(out, cfg, geo, cal, exo, tables):
    from surge_mock.writers import calendar_json
    out.mkdir(parents=True, exist_ok=False)
    (out/'raw').mkdir()
    (out/'reports').mkdir()
    (out/'context').mkdir()
    (out/'diagnostics').mkdir()
    (out/'config.yaml').write_text(yaml.safe_dump(cfg.deep(), sort_keys=False), encoding='utf-8')
    geo.static_table().to_parquet(out/'raw'/'hexes.parquet', index=False)
    write_json(out/'diagnostics'/'calendar.json', calendar_json(cal, geo, cfg))
    start = tables['start']
    for key, name in [('orders', 'orders'), ('snap', 'hex_snapshot_5min'), ('weather', 'weather_5min')]:
        df = tables[key]
        timecol = 'created_ts' if key == 'orders' else 'ts'
        actual = df.loc[df[timecol] > start].copy()
        context = df.loc[df[timecol] <= start].copy()
        context.to_parquet(out/'context'/f'{name}.parquet', index=False)
        # Windows (t-5,t]; an order at exactly midnight belongs to the preceding window.
        shift = pd.Timedelta(microseconds=1) if key == 'orders' else pd.Timedelta(minutes=5)
        dates = (actual[timecol] - shift).dt.strftime('%Y-%m-%d')
        for day, frame in actual.groupby(dates, sort=True):
            path = out/'raw'/name/f'date={day}'
            path.mkdir(parents=True)
            frame.to_parquet(path/'part.parquet', index=False)
    tables['audit'].to_parquet(out/'diagnostics'/'order_audit.parquet', index=False)
    tables['stats'].to_parquet(out/'diagnostics'/'driver_stats_5min.parquet', index=False)
    nw, N = cfg.n_days*288, geo.n
    sl = slice(cfg.burn_in_days*288, None)
    truth = pd.DataFrame({'ts': np.repeat(tables['weather'].ts.iloc[sl].values, N), 'hex_id': np.tile(geo.cells, nw)})
    for key, arr in exo.truth.items():
        truth[key] = arr[sl].ravel() if arr.ndim == 2 else np.repeat(arr[sl], N)
    truth['s6_sparse'] = np.tile(geo.s6_sparse, nw)
    truth['s7_boundary'] = np.tile(geo.s7_boundary, nw)
    truth.to_parquet(out/'diagnostics'/'signal_truth.parquet', index=False)


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n",
                    encoding="utf-8")


def _set_nested(obj: dict, key: str, value) -> None:
    target = obj
    bits = key.split(".")
    for bit in bits[:-1]:
        if bit not in target or not isinstance(target[bit], dict):
            raise ValueError(f"Unknown adjustment path: {key}")
        target = target[bit]
    if bits[-1] not in target:
        raise ValueError(f"Unknown adjustment path: {key}")
    target[bits[-1]] = value


def load_v3_profile(path: Path) -> dict:
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    if profile.get("version") != "v3_temporal_od_1" or profile.get("case") != "temporal_od":
        raise ValueError("V3 profile version/case mismatch")
    dgp = profile["temporal_demand"]
    if not (0 <= dgp["rho"] < 1 and 0 <= dgp["neighbor_diffusion"] <= 1
            and 0 <= dgp["log_intensity_sigma"] <= 1.5):
        raise ValueError("Invalid temporal demand settings")
    return profile


def configuration(days: int, seed: int, profile: dict):
    # Start from bounded V2 contract; changes are scoped to this new dataset only.
    cfg = base_configuration(days, seed)
    for path, value in profile["adjustments"].items():
        _set_nested(cfg, path, value)
    cfg["profile"] = f"mock_v3_{days}d"
    cfg["v3_dgp"] = dict(profile["temporal_demand"])
    cfg["v3_generator_version"] = profile["version"]
    return cfg


def v3_intents(exo: Exogenous, cfg, geo: Geo, seed: int) -> dict:
    """Make a stationary-ish spatial AR demand factor; keep physical market updates unchanged.

    X(t) = rho * [(1-mix)*X(t-1) + mix*A*X(t-1)] + sqrt(1-rho^2)*epsilon(t).
    Actual requests still undergo fare/no-car thinning in surge_mock.kernel.
    """
    settings = cfg["v3_dgp"]
    rho = float(settings["rho"])
    mix = float(settings["neighbor_diffusion"])
    sigma = float(settings["log_intensity_sigma"])
    rng = stream(seed, "mock_v3_temporal_demand")
    n = geo.n
    w = exo.W
    adj = np.asarray(geo.hex_dist == 1, dtype=np.float32)
    adj /= np.maximum(adj.sum(axis=1, keepdims=True), 1.0)
    innovation = rng.standard_normal((w, n)).astype(np.float32)
    latent = np.zeros_like(innovation)
    diffusion_noise_scale = np.sqrt(1.0 - rho * rho)
    for t in range(w):
        prev = latent[t - 1] if t else np.zeros(n, np.float32)
        latent[t] = (rho * ((1 - mix) * prev + mix * (adj @ prev))
                     + diffusion_noise_scale * innovation[t])
    # Recenter using the realized latent variance only within the synthetic DGP;
    # this state is oracle-only and is NEVER fitted on held-out labels.
    factor = np.exp(sigma * latent - 0.5 * sigma * sigma).astype(np.float32)
    k = float(cfg["demand"]["gamma_k"])
    gamma = rng.gamma(k, 1.0 / k, size=(w, n)).astype(np.float32)
    intensity = np.repeat(factor * gamma, 5, axis=0)
    if intensity.shape != exo.mu.shape:
        raise AssertionError("Demand intensity does not align with 1-minute exogenous grid")
    lam = np.asarray(exo.mu * intensity, dtype=np.float64)
    if not np.isfinite(lam).all() or (lam < 0).any():
        raise AssertionError("Invalid intensities")
    exo.intents = rng.poisson(lam).astype(np.int32)
    # These arrays are oracle diagnostics, never part of feature tensors.
    return {"latent": latent, "factor": factor,
            "potential_intents_5m": exo.intents.reshape(w, 5, n).sum(axis=1).astype(np.int32)}


def _median_acf(x: np.ndarray, lag: int) -> float | None:
    if len(x) <= lag:
        return None
    left, right = x[:-lag].astype(np.float64), x[lag:].astype(np.float64)
    left -= left.mean(axis=0, keepdims=True)
    right -= right.mean(axis=0, keepdims=True)
    num = np.sum(left * right, axis=0)
    den = np.sqrt(np.sum(left * left, axis=0) * np.sum(right * right, axis=0))
    good = den > 1e-9
    return float(np.median(num[good] / den[good])) if good.any() else None


def market_diagnostics(tables, geo) -> dict:
    frame = demand_supply_frame(tables, geo).sort_values(["ts", "hex_id"])
    n = geo.n
    if len(frame) % n:
        raise AssertionError("Incomplete hex grid")
    demand = frame.demand.to_numpy().reshape(-1, n)
    idle = frame.supply.to_numpy().reshape(-1, n)
    effective = frame.effective_supply.to_numpy().reshape(-1, n)
    state = np.where(demand > effective + 1e-6, 2,
                     np.where(demand + 1e-6 < effective, 0, 1)).astype(np.int8)
    transitions = np.zeros((3, 3), np.int64)
    for a, b in zip(state[:-1].ravel(), state[1:].ravel()):
        transitions[a, b] += 1
    # A transition means a state change; shortage episode length is contiguous in 5min units.
    episodes = []
    for col in state.T:
        positions = np.flatnonzero(np.r_[True, col[1:] != col[:-1], True])
        episodes.extend((int(col[lo]), int(hi - lo)) for lo, hi in zip(positions[:-1], positions[1:]))
    short = [length for group, length in episodes if group == 2]
    surplus = [length for group, length in episodes if group == 0]
    def duration(v):
        return {"count": len(v), "median_min": float(np.median(v) * 5) if v else 0,
                "p90_min": float(np.percentile(v, 90) * 5) if v else 0}
    return {
        "total_hex_snapshots": int(state.size),
        "zero_demand_share": float((demand == 0).mean()),
        "demand_gt_effective_share": float((state == 2).mean()),
        "effective_gt_demand_share": float((state == 0).mean()),
        "balanced_share": float((state == 1).mean()),
        "state_order": ["surplus", "balanced", "shortage"],
        "transition_counts_5m": transitions.tolist(),
        "change_share_5m": float((state[1:] != state[:-1]).mean()),
        "direct_surplus_shortage_flip_share_5m": float(
            (((state[:-1] == 0) & (state[1:] == 2)) |
             ((state[:-1] == 2) & (state[1:] == 0))).mean()),
        "shortage_episodes": duration(short),
        "surplus_episodes": duration(surplus),
        "median_node_autocorr": {
            "demand_lag5m": _median_acf(demand, 1),
            "demand_lag15m": _median_acf(demand, 3),
            "demand_lag60m": _median_acf(demand, 12),
            "supply_lag5m": _median_acf(effective, 1),
            "supply_lag15m": _median_acf(effective, 3),
            "idle_supply_lag5m": _median_acf(idle, 1),
        },
    }


def run(days: int, seed: int, profile: dict):
    cfg = configuration(days, seed, profile)
    geo = Geo(cfg, stream(seed, "geo"))
    cal = build_calendar(cfg, geo, stream(seed, "calendar"))
    exo = Exogenous(cfg, geo, cal, stream(seed, "intents"))
    oracle = v3_intents(exo, cfg, geo, seed)
    state = run_simulation(cfg, geo, exo, 1.0, log=log)
    tables = observed_tables(cfg, geo, exo, state)
    checks = validate_raw(tables, geo)
    metrics, zones, hours = basic_metrics(tables, geo)
    transitions = market_diagnostics(tables, geo)
    del state
    gc.collect()
    return cfg, geo, cal, exo, oracle, tables, checks, metrics, zones, hours, transitions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("calibrate", "release"), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    args = parser.parse_args()
    profile = load_v3_profile(Path(args.profile))
    out = (ROOT / args.out).resolve()
    dest_parent = ROOT / ("artifacts" if args.mode == "calibrate" else "data/staging")
    if dest_parent not in out.parents:
        raise ValueError(f"Expected a new child directory of {dest_parent}")
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite {out}")
    if args.days < 3:
        raise ValueError("Need at least three days to preserve train/validation/test splits")
    t0 = time.perf_counter()
    cfg, geo, cal, exo, oracle, tables, checks, metrics, zones, hours, diag = run(
        args.days, args.seed, profile)
    result = {
        "generator": profile["version"], "case": profile["case"], "days": args.days,
        "seed": args.seed, "parameters": cfg["v3_dgp"],
        "calibration_adjustments": profile["adjustments"],
        "market": diag, "metrics": metrics, "raw_integrity": checks,
        "elapsed_seconds": round(time.perf_counter() - t0, 3),
    }
    if not all(checks.values()):
        raise AssertionError({k: v for k, v in checks.items() if not v})
    tail_bounded = metrics["ds_eff_gt_max_count"] == 0
    result["ds_effective_tail_bounded"] = tail_bounded
    if args.mode == "calibrate":
        out.mkdir(parents=True, exist_ok=False)
        _json(out / "v3_diagnostics.json", result)
        zones.to_csv(out / "by_zone.csv")
        hours.to_csv(out / "by_hour.csv")
        print(json.dumps({"status": "calibrated", "out": str(out), "zero_demand_share": diag["zero_demand_share"],
                          "shortage_share": diag["demand_gt_effective_share"],
                          "transition_change_share": diag["change_share_5m"],
                          "max_ds_eff": metrics["ds_eff_max"]}, ensure_ascii=False), flush=True)
        return
    if not tail_bounded:
        raise AssertionError(f"D/S_eff exceeds {DS_RATIO_MAX}: max={metrics['ds_eff_max']}, "
                             f"count={metrics['ds_eff_gt_max_count']}. Calibrate before release.")
    save_raw(out, cfg, geo, cal, exo, tables)
    _json(out / "reports/v3_diagnostics.json", result)
    np.savez_compressed(out / "diagnostics/v3_latent_oracle.npz", **oracle)
    _json(out / "reports/raw_integrity.json", checks)
    _json(out / "reports/eda_metrics.json", metrics)
    zones.to_csv(out / "reports/by_zone.csv")
    hours.to_csv(out / "reports/by_hour.csv")
    city = demand_supply_frame(tables, geo).groupby("ts")[["demand", "supply", "effective_supply"]].sum()
    city["demand_gt_effective"] = city.demand > city.effective_supply + 1e-6
    city.to_csv(out / "reports/demand_supply_city_5min.csv")
    versions = {}
    for package in ("numpy", "pandas", "numba", "h3", "pyarrow", "torch", "lightgbm"):
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            versions[package] = None
    source_paths = [*sorted((ROOT / "mock_data_pipeline/surge_mock").glob("*.py")),
                    Path(__file__), Path(args.profile)]
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    manifest = {
        "dataset_id": f"hcm_mock_v3_{args.days}d_seed{args.seed}_temporal_od",
        "days": args.days, "hex_count": geo.n, "seed": args.seed,
        "start_date": cfg.start_date, "end_exclusive": str(tables["end"]),
        "timezone": "Asia/Ho_Chi_Minh", "snapshot_minutes": 5,
        "case": "temporal_od", "generator_version": profile["version"],
        "generator_profile": "tools/mock_v3/profile.yaml",
        "temporal_demand_params": profile["temporal_demand"],
        "adjustments": profile["adjustments"], "ds_effective_tail_bounded": True,
        "split_days_inclusive": cfg.deep()["split"], "source_sha256": sources,
        "package_versions": versions, "raw_integrity_pass": True, "training_ready": False,
        "limitations": [
            "Synthetic DGP, not calibrated to real HCMC operations.",
            "Only realized demand becomes a training feature; latent potential intents are diagnostic oracle.",
            "Repositioning drivers unavailable until arrival.",
            "Utilization sampled at minute ends; no exact driver-minute integration.",
            "Private audit/planned deadlines must not enter training.",
            "Raw order partitions follow right-closed window convention at midnight.",
        ],
    }
    from surge_mock.feature_v2 import export_features
    manifest.update(export_features(out, cfg, geo, tables, log=log))
    _json(out / "dataset_manifest.json", manifest)
    print(json.dumps({"status": "generated", "out": str(out),
                      "dataset_id": manifest["dataset_id"], "feature_integrity_pass": manifest["feature_integrity_pass"],
                      "zero_demand_share": diag["zero_demand_share"],
                      "demand_gt_effective_share": diag["demand_gt_effective_share"],
                      "elapsed_seconds": round(time.perf_counter() - t0, 2)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
