"""Prepare a verified clean_v1 release; promote only with --promote.

From repository root (using the project's Python environment)::
  python tools/mock_v3/refresh_clean.py --source data/staging/new_legacy --out data/staging/new_clean
  python tools/mock_v3/refresh_clean.py --prepared data/staging/new_clean --promote

Preparation copies raw/features and diagnostics, never tensors or labels. The
legacy source remains intact. Promotion archives the old canonical directory,
renames the verified candidate into place, and atomically updates CURRENT.json
last. Stop readers/trainers using the canonical directory before promotion.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
LAYOUT = 'clean_v1'
STEP = pd.Timedelta(minutes=5)
PAYLOAD_DIRS = ('raw', 'burn_in', 'features', 'oracle')
DIR_MAP = {
    'raw/orders': 'raw/orders',
    'raw/hex_snapshot_5min': 'raw/hex_snapshot',
    'raw/weather_5min': 'raw/weather',
    'features/hex_features_5min': 'features/hex_features',
    'features/graph_edges_5min': 'features/graph_edges',
}
FILE_MAP = {
    'raw/hexes.parquet': 'raw/hexes/part.parquet',
    'context/orders.parquet': 'burn_in/orders/part.parquet',
    'context/hex_snapshot_5min.parquet': 'burn_in/hex_snapshot/part.parquet',
    'context/weather_5min.parquet': 'burn_in/weather/part.parquet',
    'diagnostics/order_audit.parquet': 'oracle/order_audit/part.parquet',
    'diagnostics/signal_truth.parquet': 'oracle/signal_truth/part.parquet',
    'diagnostics/driver_stats_5min.parquet': 'oracle/driver_stats/part.parquet',
    'diagnostics/calendar.json': 'oracle/calendar.json',
}
RAW_REQUIRED = {
    'order_keys_unique', 'snapshot_keys_unique', 'foreign_keys_valid',
    'complete_hex_grid', 'continuous_5minute_grid', 'orders_demand_exact',
    'no_overlapping_driver_jobs', 'driver_state_accounting', 'censored_lifecycle',
}
FEATURE_REQUIRED = {'node_dim_40', 'edge_dim_10', 'finite_node_tensor', 'exact_day_grid', 'ds_effective_ratio_le_15'}
DS_RATIO_MAX = 15.0


def require(ok, message):
    if not bool(ok):
        raise ValueError(message)


def inside(value, label):
    p = Path(value)
    p = (ROOT / p if not p.is_absolute() else p).resolve()
    require(ROOT in p.parents, f'{label} must be inside this repository: {p}')
    return p


def relative(p):
    return p.relative_to(ROOT).as_posix()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def files_under(path):
    require(path.is_dir(), f'Missing directory: {path}')
    paths = sorted(path.rglob('*'))
    require(not any(p.is_symlink() for p in paths), f'Symlinks are not supported: {path}')
    for p in paths:
        inside(p, 'Payload file')
    return [p for p in paths if p.is_file()]


def all_pass(path, required=()):
    checks = read_json(path)
    require(isinstance(checks, dict) and checks, f'Empty validation report: {path}')
    require(set(required) <= checks.keys(), f'Missing required validation checks: {path}')
    require(all(v is True for v in checks.values()), f'Failed/incomplete validation report: {path}')
    return checks


def payload_hashes(root):
    return {p.relative_to(root).as_posix(): sha(p)
            for directory in PAYLOAD_DIRS for p in files_under(root / directory)}


def fingerprint(checksums):
    text = ''.join(f'{path}  {digest}\n' for path, digest in sorted(checksums.items()))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def table(root, path, columns=None):
    frame = ds.dataset(root / path, format='parquet', partitioning='hive').to_table(columns=columns).to_pandas().drop(columns='date', errors='ignore')
    if 'ts' in frame:
        frame['ts'] = pd.to_datetime(frame.ts).astype('datetime64[ns]')
    return frame


def copy_release(source, out):
    """Copy independently; no hard links to a source or a previous release."""
    copied = {}
    for old, new in DIR_MAP.items():
        for p in files_under(source / old):
            require(p.suffix == '.parquet', f'Unexpected file in table: {p}')
            copied[p.relative_to(source).as_posix()] = new + '/' + p.relative_to(source / old).as_posix()
    copied.update(FILE_MAP)
    for p in files_under(source / 'reports'):
        copied[p.relative_to(source).as_posix()] = 'meta/validation/' + p.relative_to(source / 'reports').as_posix()
    copied.update({'config.yaml': 'meta/generator_config.yaml',
                   'feature_contract.json': 'meta/source_feature_contract.json',
                   'dataset_manifest.json': 'meta/source_dataset_manifest.json'})
    source_hashes = {}
    for old, new in copied.items():
        src, dest = source / old, out / new
        require(src.is_file() and not src.is_symlink(), f'Missing/unsafe source: {src}')
        inside(src, 'Source file')
        digest = sha(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        require(sha(dest) == digest, f'Copy checksum mismatch: {old}')
        source_hashes[old] = digest
    write_json(out / 'meta/source_payload_sha256.json', source_hashes)


def snapshot_sources(source, out, manifest):
    hashes = manifest.get('source_sha256', {})
    require(bool(hashes), 'Source manifest must include generator source_sha256')
    saved = {}
    for name, expected in hashes.items():
        name = name.replace('\\', '/')
        rel = Path(name)
        require(not rel.is_absolute() and '..' not in rel.parts, f'Unsafe source name: {name}')
        choices = [source / 'source_snapshot' / rel, source / 'meta/source_snapshot' / rel, ROOT / rel]
        src = next((p for p in choices if p.is_file() and sha(p) == expected), None)
        require(src is not None, f'Exact generation source unavailable: {name}')
        inside(src, 'Generation source')
        dest = out / 'meta/source_snapshot' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        saved[name] = expected
    # This is conversion provenance, distinguished from generation provenance.
    own = Path(__file__).resolve()
    dest = out / 'meta/source_snapshot/tools/mock_v3/refresh_clean.py'
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(own, dest)
    write_json(out / 'meta/source_sha256.json', saved)
    write_json(out / 'meta/conversion_source_sha256.json', {'tools/mock_v3/refresh_clean.py': sha(own)})


def check_grid(frame, times, cells, label):
    expected = pd.MultiIndex.from_product([times.astype('datetime64[ns]'), cells], names=['ts', 'hex_id'])
    require(not frame.duplicated(['ts', 'hex_id']).any(), f'{label}: duplicate grid keys')
    aligned = frame.set_index(['ts', 'hex_id']).sort_index()
    require(aligned.index.equals(expected), f'{label}: incomplete, extra or noncontinuous 5-minute grid')
    return aligned


def validate_data(out, manifest, schema):
    """Recheck the physical copied payload, not only previous report flags."""
    start = pd.Timestamp(manifest['start_date'])
    n_days = manifest.get('days')
    require(isinstance(n_days, int) and n_days >= 30, 'Only a complete release of at least 30 days can be promoted')
    end = start + pd.Timedelta(days=n_days)
    require(pd.Timestamp(manifest['end_exclusive']) == end, f'Manifest end differs from the {n_days}-day boundary')
    require(manifest.get('timezone') == 'Asia/Ho_Chi_Minh' and manifest.get('snapshot_minutes') == 5, 'Unexpected time contract')
    expected_times = pd.date_range(start + STEP, end, freq='5min').astype('datetime64[ns]')
    burn_times = pd.date_range(start - pd.Timedelta(days=1) + STEP, start, freq='5min').astype('datetime64[ns]')
    days = set(pd.date_range(start, periods=n_days, freq='D').strftime('date=%Y-%m-%d'))
    for path in DIR_MAP.values():
        require({p.name for p in (out / path).iterdir()} == days, f'{path}: requires exactly {n_days} expected date partitions')
        for p in (out / path).iterdir():
            day = pd.Timestamp(p.name.removeprefix('date='))
            col = 'created_ts' if path == 'raw/orders' else 'ts'
            t = table(out, str(p.relative_to(out)), [col])[col]
            require(t.notna().all() and t.gt(day).all() and t.le(day + pd.Timedelta(days=1)).all(), f'{path}: incorrect right-closed date partition {p.name}')
    tables = {t['name']: t for t in schema['tables']}
    counts = {}
    for spec in schema['tables']:
        dataset = ds.dataset(out / spec['path'], format='parquet', partitioning='hive')
        original = tables[spec['same_as']] if 'same_as' in spec else spec
        expected_columns = {c['name'] for c in original['columns']}
        require(set(dataset.schema.names) - {'date'} == expected_columns, f'{spec["path"]}: schema columns differ')
        counts[spec['path']] = int(dataset.count_rows())
    hexes = table(out, 'raw/hexes').sort_values('hex_id')
    cells = hexes.hex_id.tolist()
    require(len(cells) == 61 and len(set(cells)) == 61 and manifest['hex_count'] == 61, 'Expected 61 unique hexes')
    snap = check_grid(table(out, 'raw/hex_snapshot'), expected_times, cells, 'raw snapshot')
    burn_snap = check_grid(table(out, 'burn_in/hex_snapshot'), burn_times, cells, 'burn-in snapshot')
    for name, f in [('main', snap), ('burn-in', burn_snap)]:
        require(np.isfinite(f.to_numpy(dtype=float)).all() and f.ge(0).all().all(), f'{name}: invalid raw values')
        require(np.equal(f[['demand', 'supply']], np.floor(f[['demand', 'supply']])).all().all(), f'{name}: demand/supply must be integer counts')
    for path, times in [('raw/weather', expected_times), ('burn_in/weather', burn_times)]:
        weather = table(out, path).sort_values('ts')
        require(pd.DatetimeIndex(weather.ts).equals(times), f'{path}: missing/duplicate timestamps')
        require(np.isfinite(weather.rain_intensity).all() and weather.rain_intensity.between(0, 1).all(), f'{path}: invalid weather')
    orders = table(out, 'raw/orders')
    burn_orders = table(out, 'burn_in/orders')
    all_orders = pd.concat([burn_orders, orders], ignore_index=True)
    require(all_orders.order_id.notna().all() and not all_orders.order_id.duplicated().any(), 'Duplicate or null order IDs')
    for label, o, lo, hi in [('main', orders, start, end), ('burn-in', burn_orders, start - pd.Timedelta(days=1), start)]:
        require(o.created_ts.gt(lo).all() and o.created_ts.le(hi).all(), f'{label}: orders outside period')
        require(o.origin_hex.isin(cells).all() and o.dest_hex.isin(cells).all(), f'{label}: invalid hex FK')
        grouped = o.assign(ts=o.created_ts.dt.ceil('5min')).groupby(['ts', 'origin_hex']).size()
        grid = snap if label == 'main' else burn_snap
        grouped.index.names = ['ts', 'hex_id']
        require(np.array_equal(grouped.reindex(grid.index, fill_value=0).to_numpy(), grid.demand.to_numpy()), f'{label}: orders do not reconcile to demand')
    for child, parent, strict in [('accepted_ts', 'created_ts', False), ('pickup_ts', 'accepted_ts', False), ('dropoff_ts', 'pickup_ts', True), ('cancel_ts', 'created_ts', False)]:
        valid = all_orders[child].notna()
        before = all_orders.loc[valid, parent]
        after = all_orders.loc[valid, child]
        require(before.notna().all() and (after.gt(before) if strict else after.ge(before)).all() and after.le(end).all(), f'Invalid/censoring lifecycle: {child}')
    require(not bool((all_orders.pickup_ts.notna() & all_orders.cancel_ts.notna()).any()), 'Cancelled order has pickup')
    require(np.isfinite(all_orders.est_trip_duration_min).all() and all_orders.est_trip_duration_min.gt(0).all(), 'Invalid trip estimate')
    nodes = check_grid(table(out, 'features/hex_features'), expected_times, cells, 'node features')
    require(np.isfinite(nodes.to_numpy(dtype=float)).all(), 'Nonfinite node feature/support')
    for nc, sc in [('demand_5m', 'demand'), ('idle_supply_t', 'supply'), ('eta_sec_t', 'eta_sec'), ('current_surge_t', 'surge_multiplier')]:
        require(np.allclose(nodes[nc], snap[sc], rtol=1e-6, atol=1e-5), f'Node/raw mismatch: {nc}')
    require(nodes.history_steps_available.eq(12).all(), 'Incomplete burn-in history')
    arrivals = ['arriving_trip_count_eta_0_5_t', 'arriving_trip_count_eta_5_10_t', 'arriving_trip_count_eta_10_15_t']
    require(nodes[arrivals + ['effective_supply_t']].ge(0).all().all(), 'Negative effective supply/arrival counts')
    expected_supply = nodes.idle_supply_t + nodes[arrivals[0]] + .5 * nodes[arrivals[1]] + .2 * nodes[arrivals[2]]
    require(np.allclose(nodes.effective_supply_t, expected_supply, rtol=1e-6, atol=1e-5), 'Effective supply formula mismatch')
    for day in sorted(days):
        edges = table(out, 'features/graph_edges/' + day)
        keys = ['ts', 'src_hex', 'dst_hex', 'edge_is_od']
        require(not edges.duplicated(keys).any(), f'{day}: duplicate graph key')
        require(edges.src_hex.isin(cells).all() and edges.dst_hex.isin(cells).all(), f'{day}: invalid graph FK')
        numeric = edges.drop(columns=['ts', 'src_hex', 'dst_hex'])
        require(np.isfinite(numeric.to_numpy()).all() and numeric.ge(0).all().all(), f'{day}: invalid edge value')
        require(edges.edge_is_adjacent.isin([0, 1]).all() and edges.edge_is_od.isin([0, 1]).all() and (edges.edge_is_adjacent + edges.edge_is_od).eq(1).all(), f'{day}: relation flags are not exclusive')
        require(edges.od_transition_prob_30m.le(1).all() and edges.travel_time_est_min.gt(0).all(), f'{day}: invalid probability/travel time')
        adjacent = edges.loc[edges.edge_is_adjacent.eq(1)]
        od_cols = [c for c in edges if c.startswith('od_')]
        require(adjacent[od_cols].eq(0).all().all() and adjacent.src_hex.ne(adjacent.dst_hex).all(), f'{day}: invalid adjacency row')
        begin = pd.Timestamp(day.removeprefix('date='))
        ts = pd.date_range(begin + STEP, begin + pd.Timedelta(days=1), freq='5min').astype('datetime64[ns]')
        require(pd.DatetimeIndex(edges.ts.unique()).sort_values().equals(ts), f'{day}: graph missing timestamps')
        target = nodes.loc[(ts, slice(None)), :]
        od = edges.loc[edges.edge_is_od.eq(1)]
        for ec, group, nc in [('od_requests_5m', 'src_hex', 'demand_5m'), ('od_requests_30m', 'src_hex', 'od_support_30m'), ('od_arrivals_eta_le5m_t', 'dst_hex', arrivals[0])]:
            total = od.groupby(['ts', group])[ec].sum()
            total.index.names = ['ts', 'hex_id']
            require(np.allclose(total.reindex(target.index, fill_value=0), target[nc], rtol=1e-6, atol=1e-5), f'{day}: graph/node mismatch {ec}')
    metrics = read_json(out / 'meta/validation/eda_metrics.json')
    require(metrics['n_orders'] == len(orders) and metrics['n_snapshot_rows'] == len(snap), 'Source EDA row counts disagree with payload')
    zone_map = hexes.set_index('hex_id').zone
    balance = nodes[['demand_5m', 'idle_supply_t', 'effective_supply_t', 'eta_sec_t', 'current_surge_t']].reset_index()
    physical = ['demand_5m', 'idle_supply_t', 'effective_supply_t']
    balance[physical] = balance[physical].astype(float).round(4)
    balance['zone'] = balance.hex_id.map(zone_map)
    balance['hour'] = (balance.ts - STEP).dt.hour
    balance['demand_gt_idle'] = balance.demand_5m > balance.idle_supply_t
    balance['demand_gt_effective'] = balance.demand_5m > balance.effective_supply_t
    city = balance.groupby('ts')[physical].sum().round(4)
    d, idle, seff = balance.demand_5m, balance.idle_supply_t, balance.effective_supply_t
    positive = seff > 0
    ratios = d[positive] / seff[positive]
    require(np.isfinite(ratios).all() and float(ratios.max()) <= DS_RATIO_MAX, f'D/S_eff exceeds {DS_RATIO_MAX:g} on positive-supply rows')
    metrics.update({
        'n_orders': len(orders), 'n_snapshot_rows': len(snap),
        'demand_mean': float(d.mean()), 'idle_mean': float(idle.mean()),
        'surge_max_observed': float(snap.surge_multiplier.max()),
        'effective_supply_mean': float(seff.mean()),
        'demand_gt_idle_share': float((d > idle).mean()),
        'demand_gt_effective_share': float((d > seff).mean()),
        'demand_lt_effective_share': float((d < seff).mean()),
        'zero_effective_supply_share': float((seff == 0).mean()),
        'positive_demand_zero_effective_share': float(((d > 0) & (seff == 0)).mean()),
        'city_demand_gt_idle_share': float((city.demand_5m > city.idle_supply_t).mean()),
        'city_demand_gt_effective_share': float((city.demand_5m > city.effective_supply_t).mean()),
        'ds_positive_supply_quantiles': {str(q): float(ratios.quantile(q)) for q in [.5, .9, .99, .999, 1.]},
        'ds_gt10_share': float((ratios > 10).mean()),
        'ds_gt15_count': int((ratios > DS_RATIO_MAX).sum()),
        'effective_supply_definition': 'idle + arrivals_0_5 + 0.5*arrivals_5_10 + 0.2*arrivals_10_15; same original feature contract',
    })
    aggregations = dict(demand_mean=('demand_5m', 'mean'), idle_mean=('idle_supply_t', 'mean'),
                        effective_supply_mean=('effective_supply_t', 'mean'), eta_sec_mean=('eta_sec_t', 'mean'),
                        surge_mean=('current_surge_t', 'mean'), demand_gt_idle_share=('demand_gt_idle', 'mean'),
                        demand_gt_effective_share=('demand_gt_effective', 'mean'))
    for group in ['zone', 'hour']:
        summary = balance.groupby(group).agg(**aggregations)
        if group == 'zone':
            summary['orders'] = orders.origin_hex.map(zone_map).value_counts().reindex(summary.index, fill_value=0)
        summary.to_csv(out / f'meta/validation/by_{group}.csv')
    city.to_csv(out / 'meta/validation/city_supply_balance_5min.csv')
    write_json(out / 'meta/validation/eda_metrics.json', metrics)
    return counts, metrics, start, end, n_days


def longest_episode(flags):
    """A deficit episode counts contiguous 5-minute windows, not calendar hours."""
    best = current = 0
    end_index = None
    previous = None
    for i, (stamp, deficit) in enumerate(flags.items()):
        current = current + 1 if deficit and (previous is None or stamp - previous == STEP) else int(deficit)
        if current > best:
            best, end_index = current, i
        previous = stamp
    return {'snapshots': best, 'minutes': best * 5,
            'window_start': str(flags.index[end_index - best + 1] - STEP) if best else None,
            'window_end': str(flags.index[end_index]) if best else None}


def balance_summary(frame):
    require(len(frame) > 0, 'Cannot compare an empty demand/supply slice')
    cols = ['demand_5m', 'idle_supply_t', 'effective_supply_t']
    values = frame[cols].astype(float).round(4)
    city = values.assign(ts=frame.ts.to_numpy()).groupby('ts').sum().round(4)
    positive = city.effective_supply_t.gt(0)
    ratios = city.loc[positive, 'demand_5m'] / city.loc[positive, 'effective_supply_t']
    at = ratios.idxmax() if len(ratios) else None
    maximum = ({'ts': str(at), 'demand': float(city.loc[at, 'demand_5m']),
                'idle_supply': float(city.loc[at, 'idle_supply_t']),
                'effective_supply': float(city.loc[at, 'effective_supply_t']),
                'demand_effective_ratio': float(ratios.loc[at])} if at is not None else None)
    deficit = city.demand_5m.gt(city.effective_supply_t)
    return {'rows': len(frame), 'snapshots': len(city), 'hex_count': int(frame.hex_id.nunique()),
            'demand_mean': float(values.demand_5m.mean()),
            'idle_supply_mean': float(values.idle_supply_t.mean()),
            'effective_supply_mean': float(values.effective_supply_t.mean()),
            'local_demand_gt_idle_share': float(values.demand_5m.gt(values.idle_supply_t).mean()),
            'local_demand_gt_effective_share': float(values.demand_5m.gt(values.effective_supply_t).mean()),
            'city_demand_gt_idle_snapshots': int(city.demand_5m.gt(city.idle_supply_t).sum()),
            'city_demand_gt_effective_snapshots': int(deficit.sum()),
            'city_demand_gt_effective_share': float(deficit.mean()),
            'city_positive_demand_zero_effective_snapshots': int((city.demand_5m.gt(0) & ~positive).sum()),
            'city_demand_effective_ratio_max': float(ratios.max()) if len(ratios) else None,
            'longest_city_effective_deficit_episode': longest_episode(deficit),
            'max_ratio_example': maximum}


def compare_before_after(target, out, compare_day):
    """Read only five physical columns; no model inference or arbitrary rescaling."""
    comparison = {'physical_comparison_rounding_decimals': 4,
                  'deficit_definition': 'D > supply after rounding physical counts to 0.0001; ratios require supply > 0',
                  'day_definition': 'date of window start (ts - 5 minutes)', 'before': None, 'after': None}
    cols = ['ts', 'hex_id', 'demand_5m', 'idle_supply_t', 'effective_supply_t']
    for name, root in [('before', target), ('after', out)]:
        if not root.exists():
            continue
        frame = table(root, 'features/hex_features', cols)
        selected = frame.loc[(frame.ts - STEP).dt.strftime('%Y-%m-%d').eq(compare_day)]
        comparison[name] = {'path_at_preparation': relative(root),
                            'full_period': balance_summary(frame),
                            compare_day: balance_summary(selected) if len(selected) else None}
    write_json(out / 'meta/validation/comparison_before_after.json', comparison)


def target_state(target):
    current = DATA / 'CURRENT.json'
    if target.exists():
        m = target / 'meta/manifest.json'
        require(m.is_file() and read_json(m).get('layout_version') == LAYOUT, 'Existing target is not a clean_v1 dataset')
    return {'target_manifest_sha256': sha(target / 'meta/manifest.json') if target.exists() else None,
            'current_sha256': sha(current) if current.exists() else None}


def prepare(source, out, target, template, dataset_id, compare_day='2026-01-27'):
    require(source.is_dir() and not out.exists(), 'Source must exist and output must be a NEW path')
    require(source != target and source not in target.parents and target not in source.parents, 'Source and target must be separate directories')
    require(all(out != p and out not in p.parents and p not in out.parents for p in [source, target]), 'Output must be separate from source and target')
    baseline = target_state(target)
    manifest = read_json(source / 'dataset_manifest.json')
    require(manifest.get('raw_integrity_pass') is True and manifest.get('feature_integrity_pass') is True, 'Source manifest must pass raw and feature integrity')
    raw_checks = all_pass(source / 'reports/raw_integrity.json', RAW_REQUIRED)
    feature_checks = all_pass(source / 'reports/feature_validation.json', FEATURE_REQUIRED)
    require(any(k.startswith('node_prefix_') for k in feature_checks) and any(k.startswith('edge_prefix_') for k in feature_checks), 'Missing point-in-time prefix checks')
    schema = yaml.safe_load(template.read_text(encoding='utf-8-sig'))
    require(schema['dataset']['feature_contract'] == manifest['feature_version'], 'Schema template feature contract differs from generated features')
    old_id = schema['dataset']['id']
    case = manifest['case']
    dataset_id = dataset_id or manifest['dataset_id']
    if dataset_id == old_id and case not in dataset_id:
        dataset_id += '_' + case
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', dataset_id)), 'Dataset ID must be a simple nonempty identifier')
    out.mkdir(parents=True, exist_ok=False)
    copy_release(source, out)
    snapshot_sources(source, out, manifest)
    counts, metrics, start, end, n_days = validate_data(out, manifest, schema)
    compare_before_after(target, out, compare_day)
    config = yaml.safe_load((out / 'meta/generator_config.yaml').read_text(encoding='utf-8-sig'))
    price_min = float(config['base_surge']['min'])
    price_max = float(config['base_surge']['max'])
    require(price_min <= metrics['surge_max_observed'] <= price_max + 1e-5, 'Observed surge exceeds configuration range')
    for spec in schema['tables']:
        spec['rows'] = counts[spec['path']]
        if spec['name'] == 'burn_in_orders':
            spec['note'] = f'History only; lifecycle timestamps censored at {end}'
        if spec['name'] == 'graph_edges':
            spec['description'] = re.sub(r'About \d+ rows per ts on average\.', f'About {counts[spec["path"]] / (n_days * 288):.1f} rows per ts on average.', spec['description'])
        if spec['name'] == 'signal_truth':
            ramp = next(c for c in spec['columns'] if c['name'] == 's1_ramp')
            low, high = config['signals']['s1_ramp']['range']
            rise = config['signals']['s1_ramp']['lead_min']
            decay = config['signals']['s1_ramp']['decay_min']
            ramp['description'] = (
                f'S1 demand ramp multiplier, from 1.0 to a daily peak sampled '
                f'in Uniform({low:g}, {high:g}); rise {rise:g} min, decay {decay:g} min')
        if spec['name'] == 'hex_snapshot':
            surge = next(c for c in spec['columns'] if c['name'] == 'surge_multiplier')
            surge['description'] = f'Surge multiplier in force at ts (configured valid range {price_min:g} .. {price_max:g})'
            surge['valid_range'] = [price_min, price_max]
    schema['dataset'].update(id=dataset_id, period={'burn_in': [str(start - pd.Timedelta(days=1) + STEP), str(start)], 'main': [str(start + STEP), str(end)]})
    schema_text = yaml.safe_dump(schema, sort_keys=False, allow_unicode=True)
    # Update only known stale explanatory references in the reused schema.
    for old in [str(x) for x in yaml.safe_load(template.read_text(encoding='utf-8-sig'))['dataset']['period']['main'][-1:]]:
        schema_text = re.sub(re.escape(old) + r'(?!:\d)', str(end), schema_text)
    (out / 'schema.yaml').write_text('# clean_v1: physical raw/feature schemas; training labels are built downstream.\n' + schema_text, encoding='utf-8')
    contract = read_json(source / 'feature_contract.json')
    for key in ['window', 'horizons_min', 'epsilon', 'purge_min', 'target', 'normalization']:
        contract.pop(key, None)
    contract['training_scope'] = 'Labels, transforms, windows, splits and normalization are constructed downstream per docs/model/technical_report.md.'
    write_json(out / 'meta/feature_contract.json', contract)
    checksums = payload_hashes(out)
    digest = fingerprint(checksums)
    write_json(out / 'meta/checksums.json', checksums)
    keep = ['days', 'hex_count', 'start_date', 'end_exclusive', 'timezone', 'snapshot_minutes', 'seed', 'case', 'package_versions', 'feature_version', 'limitations']
    clean = {key: manifest[key] for key in keep if key in manifest}
    warnings = [{'metric': name, 'value': metrics[name], 'reference_range': bounds,
                 'basis': 'Existing synthetic calibration heuristic; not an empirical HCMC requirement'}
                for name, bounds in [('completion_rate_mature', [.75, .90]), ('surge_gt1_share', [.15, .30])]]
    warnings = [w for w in warnings if not w['reference_range'][0] <= w['value'] <= w['reference_range'][1]]
    clean.update(dataset_id=dataset_id, layout_version=LAYOUT, schema='schema.yaml',
                 feature_contract='meta/feature_contract.json', checksums='meta/checksums.json',
                 data_fingerprint=digest,
                 data_fingerprint_rule='sha256 of lines "<path>  <sha256>\\n" from meta/checksums.json, sorted by path',
                 raw_integrity_pass=True, feature_integrity_pass=True, clean_validation_pass=True,
                 row_counts=counts, eda_metrics=metrics, realism_warnings=warnings,
                 readiness_scope='Validated synthetic raw and point-in-time feature inputs; downstream training and marketplace validity are separate.',
                 realism_validation_complete=False, deployment_ready=False,
                 burn_in={'start': str(start - pd.Timedelta(days=1) + STEP), 'end': str(start), 'use': 'history only'},
                 suggested_split_days_inclusive=manifest.get('split_days_inclusive', manifest.get('suggested_split_days_inclusive', {})),
                 suggested_split_note='Generator calendar suggestion only; model pipeline owns final split, purge and windows.',
                 excluded_from_this_layout='Legacy training/ and targets/ remain in the untouched legacy source; never copied to clean_v1.',
                 source_legacy_path=relative(source), source_dataset_id=manifest['dataset_id'],
                 source_sha256=read_json(out / 'meta/source_sha256.json'),
                 prepared_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(out / 'meta/manifest.json', clean)
    q = metrics['ds_positive_supply_quantiles']
    readme = f'''# {dataset_id}

Synthetic HCMC ride-hailing data: 61 H3 cells, five-minute windows, exactly {n_days} main days from {start.date()} through {(end - STEP).date()}, plus one history-only burn-in day.

Read `schema.yaml` for every table, column, key, feature group and role. This release contains raw observations and point-in-time features; model labels, windows, normalization, graph tensors and splits are built downstream according to `../../docs/model/technical_report.md`.

## Contents and actual counts

| Table | Rows |
|---|---:|
''' + ''.join(f'| `{path}` | {count:,} |\n' for path, count in counts.items()) + f'''
`oracle/` contains simulator-only audit/ground truth. Use it for diagnostics and evaluation slices, never as model input. `meta/validation/` contains integrity reports and recalculated EDA. `meta/source_snapshot/` preserves the exact available generation sources and this conversion utility. Legacy tensors/targets remain in `{relative(source)}`; none are published here.

## Time and supply definitions

Timestamps are timezone-naive local Asia/Ho_Chi_Minh. Each snapshot `ts` covers `(ts - 5min, ts]`; partition `date` is the date of `ts - 5min`. First main snapshot: {start + STEP}; last: {end}. Burn-in is history only. Unknown lifecycle timestamps are censored at the last snapshot.

Demand is requests in the five-minute window. Raw `supply` and feature `idle_supply_t` count idle drivers at its end. `effective_supply_t = idle + arriving_0_5 + 0.5*arriving_5_10 + 0.2*arriving_10_15`. Repositioning drivers are unavailable until arrival. Arrivals use observed pickups and their original trip-duration estimates. These are simulation assumptions, not measurements of real HCMC operations.

## Actual demand/supply profile

| Metric | Value |
|---|---:|
| Mean demand per hex/window | {metrics['demand_mean']:.4f} |
| Mean idle supply | {metrics['idle_mean']:.4f} |
| Mean effective supply | {metrics['effective_supply_mean']:.4f} |
| Hex/window demand > idle | {metrics['demand_gt_idle_share']:.2%} |
| Hex/window demand > effective supply | {metrics['demand_gt_effective_share']:.2%} |
| Citywide demand > effective supply | {metrics['city_demand_gt_effective_share']:.2%} |
| Effective supply = 0 | {metrics['zero_effective_supply_share']:.2%} |
| Demand > 0 and effective supply = 0 | {metrics['positive_demand_zero_effective_share']:.2%} |
| Mature completion rate | {metrics['completion_rate_mature']:.2%} |
| D/S_eff > 10 (positive supply) | {metrics['ds_gt10_share']:.3%} |
| D/S_eff > 15 (positive supply) | {metrics['ds_gt15_count']:,} |

The raw D/S ratio is undefined when effective supply is zero; preserve a mask. Among positive-supply rows, D/S p50={q['0.5']:.3f}, p90={q['0.9']:.3f}, p99={q['0.99']:.3f}, p99.9={q['0.999']:.3f}, max={q['1.0']:.3f}. The generator bounds it at {DS_RATIO_MAX:g} by simulation (a no-cars booking filter plus local-supply protection), not by clipping. No ratio or supply value was rescaled for display. See `meta/validation/by_hour.csv`, `by_zone.csv` and `city_supply_balance_5min.csv` for the full distribution. Citywide averages can hide simultaneous local shortages and surpluses.

## Provenance and limits

Case: `{case}`; seed: `{manifest['seed']}`. Data fingerprint: `{digest}`. The manifest records all current row counts, source hashes and any heuristic realism warnings. Integrity checks establish technical consistency; they do not establish real-world calibration, GNN benefit, causal pricing impact or production readiness. Booking-rate and profit effects cannot be inferred from this synthetic profile. Training caches and fitted models from an earlier fingerprint need to be rebuilt downstream.
'''
    (out / 'README.md').write_text(readme, encoding='utf-8')
    all_pass(out / 'meta/validation/raw_integrity.json', RAW_REQUIRED)
    all_pass(out / 'meta/validation/feature_validation.json', FEATURE_REQUIRED)
    require(sha(source / 'dataset_manifest.json') == read_json(out / 'meta/source_payload_sha256.json')['dataset_manifest.json'], 'Source changed during preparation')
    clean_checks = dict(complete_day_grid=True, ds_effective_ratio_bounded=True, schema_columns_match=True, row_counts_verified=True,
                        burn_in_coverage=True, order_demand_reconciliation=True, lifecycle_censoring=True,
                        raw_feature_alignment=True, effective_supply_formula=True, graph_node_alignment=True,
                        copied_source_checksums=True, source_integrity_reports_pass=True)
    write_json(out / 'meta/validation/clean_layout_validation.json', clean_checks)
    metadata = {p.relative_to(out).as_posix(): sha(p) for p in files_under(out / 'meta')}
    metadata.update({'schema.yaml': sha(out / 'schema.yaml'), 'README.md': sha(out / 'README.md')})
    write_json(out / 'meta/READY.json', {'layout_version': LAYOUT, 'target': relative(target),
               'data_fingerprint': digest, 'expected_previous_state': baseline, 'metadata_sha256': metadata})
    return out


def verify_ready(candidate, target):
    marker = read_json(candidate / 'meta/READY.json')
    require(marker['layout_version'] == LAYOUT and marker['target'] == relative(target), 'Candidate was prepared for a different target/layout')
    for name, expected in marker['metadata_sha256'].items():
        p = inside(candidate / name, 'Candidate metadata')
        require(candidate in p.parents and sha(p) == expected, f'Candidate metadata changed: {name}')
    actual = payload_hashes(candidate)
    require(actual == read_json(candidate / 'meta/checksums.json'), 'Candidate payload checksum mismatch')
    require(fingerprint(actual) == marker['data_fingerprint'], 'Candidate fingerprint mismatch')
    require(not (candidate / 'training').exists() and not (candidate / 'targets').exists(), 'Candidate contains legacy training artifacts')
    all_pass(candidate / 'meta/validation/clean_layout_validation.json')
    require(target_state(target) == marker['expected_previous_state'], 'Target/CURRENT changed since preparation; re-prepare after reviewing the change')
    return read_json(candidate / 'meta/manifest.json')


def replace_bytes(path, data):
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with temp.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def promote(candidate, target):
    require(target.parent == DATA, 'Canonical target must be a direct child of data/ (CURRENT.json scope)')
    manifest = verify_ready(candidate, target)
    lock = DATA / '.refresh_clean.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    archive = None
    current = DATA / 'CURRENT.json'
    prior = None
    installed = archived = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'candidate': relative(candidate), 'target': relative(target)}))
        require(target_state(target) == read_json(candidate / 'meta/READY.json')['expected_previous_state'], 'Target changed before lock acquisition')
        prior = current.read_bytes() if current.exists() else None
        require(candidate.stat().st_dev == DATA.stat().st_dev, 'Promotion requires candidate and target on the same volume')
        if target.exists():
            archive_root = DATA / '_archive'
            archive_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            archive = archive_root / f'{target.name}_{stamp}_{uuid.uuid4().hex[:10]}'
            require(not archive.exists(), 'Archive collision')
            target.rename(archive)
            archived = True
        candidate.rename(target)
        installed = True
        pointer = {key: manifest[key] for key in ['dataset_id', 'data_fingerprint', 'layout_version']}
        pointer.update(path=relative(target), schema=relative(target / 'schema.yaml'), manifest=relative(target / 'meta/manifest.json'))
        # Commit point: CURRENT is replaced only after both directory renames.
        replace_bytes(current, (json.dumps(pointer, indent=2) + '\n').encode('utf-8'))
    except BaseException as original:
        failures = []
        try:
            if installed:
                target.rename(candidate)
            if archived:
                archive.rename(target)
        except Exception as e:
            failures.append(f'directory rollback: {e}')
        try:
            if installed or archived:
                if prior is None:
                    if current.exists():
                        current.unlink()
                elif not current.exists() or current.read_bytes() != prior:
                    replace_bytes(current, prior)
        except Exception as e:
            failures.append(f'CURRENT rollback: {e}')
        if failures:
            raise RuntimeError(f'Promotion failed: {original}; manual recovery required: {failures}; archive={archive}; candidate={candidate}') from original
        raise
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError as e:
            print(f'Could not remove promotion lock {lock}: {e}', file=sys.stderr)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source', help='Complete legacy staging release from tools/mock_v3/run.py')
    mode.add_argument('--prepared', help='Existing clean candidate, previously prepared by this utility')
    parser.add_argument('--target', default='data/hcm_data_2')
    parser.add_argument('--out', help='New clean candidate directory (never overwritten)')
    parser.add_argument('--schema-template', help='Existing clean_v1 schema; defaults to TARGET/schema.yaml')
    parser.add_argument('--dataset-id', help='Optional new dataset identifier')
    parser.add_argument('--compare-day', default='2026-01-27', help='Day (YYYY-MM-DD) summarised in comparison_before_after.json')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--promote', action='store_true', help='Explicitly archive/replace canonical dataset and CURRENT.json')
    action.add_argument('--prepare-only', action='store_true', help='Default: leave a verified candidate for review')
    args = parser.parse_args()
    target = inside(args.target, 'Target')
    require(target.parent == DATA, 'Target must be a direct child of data/')
    if args.source:
        source = inside(args.source, 'Source')
        name = f'data/staging/{target.name}_clean_{uuid.uuid4().hex[:12]}'
        candidate = inside(args.out or name, 'Output')
        template = inside(args.schema_template or target / 'schema.yaml', 'Schema template')
        prepare(source, candidate, target, template, args.dataset_id, args.compare_day)
    else:
        require(not args.out and not args.schema_template and not args.dataset_id, '--prepared cannot be combined with preparation options')
        candidate = inside(args.prepared, 'Prepared candidate')
        require(candidate != target and candidate not in target.parents and target not in candidate.parents, 'Candidate and target must be separate directories')
    manifest = verify_ready(candidate, target)
    result = {'status': 'prepared', 'candidate': relative(candidate), 'dataset_id': manifest['dataset_id'], 'data_fingerprint': manifest['data_fingerprint'], 'row_counts': manifest['row_counts']}
    if args.promote:
        archive = promote(candidate, target)
        result.update(status='promoted', path=relative(target), archive=relative(archive) if archive else None)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
