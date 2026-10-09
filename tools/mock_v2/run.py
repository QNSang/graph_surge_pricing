"""Generate/validate versioned mock candidates without touching legacy datasets.

Examples (from repository root):
  python tools/mock_v2/run.py --mode smoke --out artifacts/mock_v2_smoke
  python tools/mock_v2/run.py --mode calibrate --out artifacts/mock_v2_calibration
  python tools/mock_v2/run.py --mode release --out data/staging/hcm_mock_v2_30d_seed42
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'mock_data_pipeline'))
import numpy as np
import pandas as pd
import yaml
from surge_mock.config import load_config
from surge_mock.geo import Geo
from surge_mock.rng import stream
from surge_mock.calendar_gen import build_calendar
from surge_mock.exogenous import Exogenous
from surge_mock.simulate import run_simulation
from surge_mock.dataset_v2 import observed_tables, validate_raw, basic_metrics

CASES = {'fixed_baseline': {}, 'moderate_reposition': {'drivers.reposition.prob': 0.35, 'drivers.reposition.power': 4.0},
         'moderate_supply_low': {'drivers.reposition.prob': 0.35, 'drivers.reposition.power': 4.0, 'drivers.online_scale': 0.50}}


def log(*s):
    print(*s, flush=True)


def configuration(days=30, seed=42, case='fixed_baseline'):
    cfg = load_config(None, 'full', CASES[case])
    cfg['seed'] = seed
    cfg['n_days'] = days
    cfg['profile'] = 'training_v2_30d' if days == 30 else 'development_v2'
    if days == 30:
        cfg['split'] = {'train': [1, 21], 'val': [22, 25], 'test': [26, 30]}
    else:
        assert days >= 3
        cfg['split'] = {'train': [1, days-2], 'val': [days-1, days-1], 'test': [days, days]}
    cfg['rain']['days'] = min(days, max(3, round(days/6)))
    cfg['signals']['s4']['events'] = min(days, max(3, round(days/8)))
    return cfg


def simulate(days, seed, case):
    cfg = configuration(days, seed, case)
    geo = Geo(cfg, stream(seed, 'geo'))
    cal = build_calendar(cfg, geo, stream(seed, 'calendar'))
    exo = Exogenous(cfg, geo, cal, stream(seed, 'intents'))
    state = run_simulation(cfg, geo, exo, 1.0, log=log)
    tables = observed_tables(cfg, geo, exo, state)
    checks = validate_raw(tables, geo)
    metrics, zones, hours = basic_metrics(tables, geo)
    del state
    gc.collect()
    return cfg, geo, cal, exo, tables, checks, metrics, zones, hours


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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['smoke', 'calibrate', 'release'], required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--case', choices=list(CASES), default='fixed_baseline')
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    out = (ROOT/args.out).resolve()
    if ROOT not in out.parents:
        raise ValueError('Output must be inside this repository')
    if out.exists():
        raise FileExistsError(f'Refusing to overwrite {out}')
    t0 = time.time()
    if args.mode == 'calibrate':
        out.mkdir(parents=True)
        rows = []
        for seed in [101, 202]:
            for case in CASES:
                cfg, geo, cal, exo, tables, checks, metrics, zones, hours = simulate(7, seed, case)
                row = {'case': case, 'seed': seed, **metrics, 'integrity_pass': all(checks.values())}
                rows.append(row)
                write_json(out/f'{case}_{seed}.json', {'metrics': row, 'checks': checks})
                pd.DataFrame(rows).to_csv(out/'results.csv', index=False)
                log(json.dumps(row))
                if not all(checks.values()):
                    raise AssertionError(checks)
                del exo, tables
                gc.collect()
        log('CALIBRATION COMPLETE', out)
        return
    days = 3 if args.mode == 'smoke' else 30
    cfg, geo, cal, exo, tables, checks, metrics, zones, hours = simulate(days, args.seed, args.case)
    log('RAW_CHECKS', json.dumps(checks))
    log('METRICS', json.dumps(metrics))
    if not all(checks.values()):
        raise AssertionError({k:v for k,v in checks.items() if not v})
    save_raw(out, cfg, geo, cal, exo, tables)
    write_json(out/'reports'/'raw_integrity.json', checks)
    write_json(out/'reports'/'eda_metrics.json', metrics)
    zones.to_csv(out/'reports'/'by_zone.csv')
    hours.to_csv(out/'reports'/'by_hour.csv')
    source = {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in (ROOT/'mock_data_pipeline'/'surge_mock').glob('*.py')}
    versions = {}
    for package in ['numpy','pandas','numba','h3','pyarrow','torch','lightgbm']:
        try: versions[package] = md.version(package)
        except md.PackageNotFoundError: versions[package] = None
    manifest = {'dataset_id': f'hcm_mock_v2_{days}d_seed{args.seed}', 'days': days,
        'hex_count': geo.n, 'start_date': cfg.start_date, 'end_exclusive': str(tables['end']),
        'timezone': 'Asia/Ho_Chi_Minh', 'snapshot_minutes': 5, 'seed': args.seed, 'case': args.case,
        'split_days_inclusive': cfg.deep()['split'], 'source_sha256': source, 'package_versions': versions,
        'raw_integrity_pass': True, 'training_ready': False,
        'limitations': ['Synthetic assumptions, not calibrated to real HCMC operations.',
                       'Repositioning drivers unavailable until arrival.',
                       'Utilization sampled at minute ends; no exact driver-minute integration.',
                       'Potential intents are not exported as quote events; booking rate unavailable.',
                       'Private audit contains planned deadlines; forbidden as model inputs.',
                       'Raw order partitions follow right-closed window convention at midnight.']}
    if args.mode == 'release':
        from surge_mock.feature_v2 import export_features
        manifest.update(export_features(out, cfg, geo, tables, log=log))
    write_json(out/'dataset_manifest.json', manifest)
    log('GENERATED', str(out), 'seconds', round(time.time()-t0, 2))

if __name__ == '__main__':
    main()
