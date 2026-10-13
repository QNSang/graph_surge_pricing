"""Observed data and integrity checks for the versioned N-day training release.

Burn-in is retained as context only. Lifecycle fields are independently censored;
unknown dropoff is NOT interpreted as an unpicked-up trip. Private audits never
enter the feature builder. Timestamps are local Asia/Ho_Chi_Minh, timezone-naive.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import kernel as K

EVENTS = ['accepted_ts', 'pickup_ts', 'dropoff_ts', 'cancel_ts']
# Release bound on raw D/S_eff over rows with positive effective supply.
DS_RATIO_MAX = 15.0


def ds_ratio_summary(demand, effective_supply):
    """Raw D/S_eff tail summary; S_eff=0 rows are undefined and reported separately.

    S_eff is rounded to 4 decimals, as in inspect_distribution and refresh_clean,
    so fractional arrival weights do not create spurious tiny denominators.
    """
    demand = np.asarray(demand, dtype=float).ravel()
    seff = np.round(np.asarray(effective_supply, dtype=float).ravel(), 4)
    positive = seff > 0
    ratio = demand[positive] / seff[positive]
    q = np.quantile(ratio, [.5, .9, .99, .999]) if len(ratio) else [np.nan] * 4
    return {
        'ds_eff_p50': float(q[0]), 'ds_eff_p90': float(q[1]),
        'ds_eff_p99': float(q[2]), 'ds_eff_p999': float(q[3]),
        'ds_eff_max': float(ratio.max()) if len(ratio) else 0.0,
        'ds_eff_gt10_share': float((ratio > 10).mean()) if len(ratio) else 0.0,
        'ds_eff_gt_max_count': int((ratio > DS_RATIO_MAX + 1e-9).sum()),
        'ds_eff_finite': bool(np.isfinite(ratio).all()),
        'zero_effective_supply_share': float((~positive).mean()),
        'positive_demand_zero_effective_share': float(((~positive) & (demand > 0)).mean()),
        'ds_eff_definition': f'demand_5m/effective_supply_t over rows with S_eff>0 (rounded 4dp); bound {DS_RATIO_MAX}',
    }


def observed_tables(cfg, geo, exo, state):
    n = int(state.cnt[K.C_ORDERS])
    W, N = exo.W, geo.n
    base = pd.Timestamp(cfg.start_date) - pd.Timedelta(days=cfg.burn_in_days)
    end_min = float(W * 5)
    cutoff = base + pd.Timedelta(minutes=end_min)

    def ts(minutes, censor=True):
        a = np.asarray(minutes, dtype=np.float64).copy()
        if censor:
            a[a > end_min] = np.nan
        ok = np.isfinite(a)
        out = np.full(len(a), np.datetime64('NaT'), dtype='datetime64[us]')
        out[ok] = np.datetime64(base, 'us') + np.rint(a[ok] * 60e6).astype('timedelta64[us]')
        return pd.to_datetime(out)

    cells = np.asarray(geo.cells)
    o = pd.DataFrame({
        'order_id': np.arange(n, dtype=np.int64),
        'origin_hex': cells[state.o_origin[:n]], 'dest_hex': cells[state.o_dest[:n]],
        'created_ts': ts(state.o_created[:n]), 'est_trip_duration_min': state.o_est[:n],
        'accepted_ts': ts(state.o_accept[:n]), 'pickup_ts': ts(state.o_pickup[:n]),
        'dropoff_ts': ts(state.o_dropoff[:n]), 'cancel_ts': ts(state.o_cancel[:n]),
    })
    audit = pd.DataFrame({
        'order_id': o.order_id, 'driver_id': state.o_driver[:n],
        'dispatch_ready_ts': ts(state.o_ready[:n], False),
        'patience_deadline_ts': ts(state.o_deadline[:n], False),
        'driver_available_ts_at_accept': ts(state.o_available_at[:n], False),
    })
    times = ts(np.arange(1, W + 1) * 5.)
    snap = pd.DataFrame({
        'ts': np.repeat(times.values, N), 'hex_id': np.tile(cells, W),
        'demand': state.snap_demand.ravel(), 'supply': state.snap_supply.ravel(),
        'eta_sec': state.snap_eta.ravel(), 'surge_multiplier': state.snap_surge.ravel(),
    })
    stats = pd.DataFrame(state.stats / 5., columns=['online', 'idle', 'pickup', 'in_trip', 'reposition'])
    stats.insert(0, 'ts', times)
    weather = pd.DataFrame({'ts': times, 'rain_intensity': exo.rain[4::5]})
    return {'orders': o, 'snap': snap, 'weather': weather, 'audit': audit, 'stats': stats,
            'start': pd.Timestamp(cfg.start_date), 'end': cutoff}


def censor_orders(orders, cutoff):
    o = orders.loc[orders.created_ts <= cutoff].copy()
    for col in EVENTS:
        o.loc[o[col] > cutoff, col] = pd.NaT
    return o


def validate_raw(tables, geo):
    o, s, a, st = (tables[k] for k in ['orders', 'snap', 'audit', 'stats'])
    keys = set(geo.cells)
    expected = o.groupby([o.created_ts.dt.ceil('5min'), 'origin_hex']).size()
    expected.index.names = ['ts', 'hex_id']
    actual = s.set_index(['ts', 'hex_id']).demand
    joined = pd.concat([actual.rename('actual'), expected.rename('expected')], axis=1).fillna(0)
    accepted = o.accepted_ts.notna()
    acc = o.loc[accepted, ['order_id', 'accepted_ts', 'cancel_ts', 'dropoff_ts']].merge(a, on='order_id', validate='one_to_one')
    intervals = acc.assign(end=acc.cancel_ts.fillna(acc.dropoff_ts).fillna(tables['end'] + pd.Timedelta(days=1)))
    intervals = intervals.sort_values(['driver_id', 'accepted_ts'])
    previous = intervals.groupby('driver_id').end.shift()
    intra = o.origin_hex.eq(o.dest_hex)
    times = pd.DatetimeIndex(s.ts.unique()).sort_values()
    checks = {
        'order_keys_unique': not o.order_id.duplicated().any(),
        'snapshot_keys_unique': not s.duplicated(['ts', 'hex_id']).any(),
        'foreign_keys_valid': set(o.origin_hex).union(o.dest_hex) <= keys and set(s.hex_id) == keys,
        'complete_hex_grid': s.groupby('ts').size().eq(len(keys)).all(),
        'continuous_5minute_grid': np.all(np.diff(times.as_unit('ns').asi8) == 300_000_000_000),
        'finite_nonnegative_snapshot': np.isfinite(s[['supply', 'demand', 'eta_sec', 'surge_multiplier']]).all().all() and (s[['supply', 'demand', 'eta_sec']] >= 0).all().all(),
        'orders_demand_exact': joined.actual.eq(joined.expected).all(),
        'accept_after_created': (o.loc[accepted, 'accepted_ts'] >= o.loc[accepted, 'created_ts']).all(),
        'accept_after_ready': (acc.accepted_ts >= acc.dispatch_ready_ts).all(),
        'accept_before_deadline': (acc.accepted_ts <= acc.patience_deadline_ts).all(),
        'accept_after_driver_available': (acc.accepted_ts >= acc.driver_available_ts_at_accept).all(),
        'accepted_driver_present': (acc.driver_id >= 0).all(),
        'no_overlapping_driver_jobs': not (intervals.accepted_ts < previous).any(),
        'driver_state_accounting': np.allclose(st.online, st[['idle', 'pickup', 'in_trip', 'reposition']].sum(axis=1)),
        'intra_estimate_not_constant': intra.sum() > 10 and o.loc[intra, 'est_trip_duration_min'].nunique() > 1,
        'censored_lifecycle': all((o[c].dropna() <= tables['end']).all() for c in EVENTS),
        'no_pickup_without_accept': not (o.pickup_ts.notna() & o.accepted_ts.isna()).any(),
        'no_dropoff_without_pickup': not (o.dropoff_ts.notna() & o.pickup_ts.isna()).any(),
        'pickup_after_accept': not (o.pickup_ts < o.accepted_ts).any(),
        'positive_trip_duration': not (o.dropoff_ts <= o.pickup_ts).any(),
        'cancel_not_before_created': not (o.cancel_ts < o.created_ts).any(),
        'cancel_disjoint_from_pickup': not (o.cancel_ts.notna() & o.pickup_ts.notna()).any(),
    }
    return {k: bool(v) for k, v in checks.items()}


def demand_supply_frame(tables, geo):
    """Compare one 5-minute request flow with idle and the declared effective supply.

    This uses build_nodes' arrival definition and burn-in as computation context.
    Returned rows cover the main period only.
    City aggregates sum physical counts before comparing; a mean of local ratios
    is not a city ratio. A deficit is a pressure proxy, not a service failure.
    """
    from .feature_v2 import ns, indexed_orders, inbound_counts
    snap = tables['snap']
    times = pd.DatetimeIndex(snap.ts.unique()).sort_values()
    index = pd.MultiIndex.from_product([times, geo.cells], names=['ts', 'hex_id'])
    frame = snap.set_index(['ts', 'hex_id']).reindex(index).reset_index()
    if frame[['demand', 'supply']].isna().any().any():
        raise ValueError('Incomplete grid in demand/supply diagnostics')
    arrivals = inbound_counts(ns(times), indexed_orders(tables['orders'], geo.cells), geo.n)
    frame['effective_supply'] = (frame.supply.to_numpy(dtype=float) +
        arrivals[0].ravel() + .5 * arrivals[1].ravel() + .2 * arrivals[2].ravel())
    frame = frame.loc[frame.ts > tables['start']].copy()
    frame['demand_gt_idle'] = frame.demand > frame.supply
    frame['demand_gt_effective'] = frame.demand > frame.effective_supply + 1e-6
    frame['effective_gt_demand'] = frame.effective_supply > frame.demand + 1e-6
    return frame


def basic_metrics(tables, geo):
    o = tables['orders'].loc[tables['orders'].created_ts > tables['start']].copy()
    s = demand_supply_frame(tables, geo)
    st = tables['stats'].loc[tables['stats'].ts > tables['start']]
    # Exclude the final two hours only for completion calibration, not from export.
    mature = o.created_ts <= tables['end'] - pd.Timedelta(hours=2)
    peak = lambda x: (x.dt.dayofweek < 5) & (x.dt.hour.between(6, 9) | x.dt.hour.between(16, 19))
    pk = peak(o.created_ts)
    done = o.dropoff_ts.notna()
    duration = (o.dropoff_ts - o.pickup_ts).dt.total_seconds() / 60
    pickup = (o.pickup_ts - o.accepted_ts).dt.total_seconds() / 60
    estimate_error = (duration - o.est_trip_duration_min).abs() / o.est_trip_duration_min
    upk = peak(st.ts - pd.Timedelta(minutes=5))
    util = (st.pickup + st.in_trip) / st.online.clip(lower=1)
    intra = o.origin_hex.eq(o.dest_hex)
    zones = geo.static_table().set_index('hex_id').zone
    o['zone'] = o.origin_hex.map(zones)
    s['zone'] = s.hex_id.map(zones)
    s['hour'] = (s.ts - pd.Timedelta(minutes=5)).dt.hour
    g = s.loc[(s.ts - pd.Timedelta(minutes=5)).dt.dayofweek < 5].groupby(['hex_id', 'hour']).demand.agg(['mean', 'var'])
    g = g[g['mean'] >= 1]
    city = s.groupby('ts')[['demand', 'supply', 'effective_supply']].sum()
    city_short = city.demand > city.effective_supply + 1e-6
    city_idle_short = city.demand > city.supply
    ratio = city.demand / city.effective_supply.clip(lower=1e-6)
    metrics = {
        'n_orders': len(o), 'n_snapshot_rows': len(s),
        'completion_rate_mature': float(done[mature].mean()),
        'completion_peak': float(done[mature & pk].mean()),
        'completion_offpeak': float(done[mature & ~pk].mean()),
        'trip_min_median': float(duration.median()), 'pickup_min_median': float(pickup.median()),
        'intra_share': float(intra.mean()), 'intra_estimate_unique': int(o.loc[intra, 'est_trip_duration_min'].nunique()),
        'intra_estimate_p50': float(o.loc[intra, 'est_trip_duration_min'].median()),
        'intra_estimate_floor_share': float(np.isclose(o.loc[intra, 'est_trip_duration_min'], 3.).mean()),
        'util_peak_sampled': float(util[upk].mean()), 'util_offpeak_sampled': float(util[~upk].mean()),
        'surge_gt1_share': float((s.surge_multiplier > 1.001).mean()),
        'surge_ge2_share': float((s.surge_multiplier >= 1.999).mean()),
        'demand_mean': float(s.demand.mean()), 'idle_mean': float(s.supply.mean()),
        'zero_demand_share': float(s.demand.eq(0).mean()),
        'positive_demand_zero_idle_share': float((s.demand.gt(0) & s.supply.eq(0)).mean()),
        'demand_gt_idle_share': float(s.demand_gt_idle.mean()),
        'effective_supply_mean': float(s.effective_supply.mean()),
        'demand_gt_effective_share': float(s.demand_gt_effective.mean()),
        'effective_gt_demand_share': float(s.effective_gt_demand.mean()),
        'city_demand_gt_idle_share': float(city_idle_short.mean()),
        'city_demand_gt_effective_share': float(city_short.mean()),
        'city_shortage_snapshot_count': int(city_short.sum()),
        'city_snapshot_count': len(city),
        'city_ds_ratio_p50': float(ratio.median()),
        'city_ds_ratio_p95': float(ratio.quantile(.95)),
        'city_ds_ratio_max': float(ratio.max()),
        'days_with_city_effective_shortage': int(
            (city.index[city_short] - pd.Timedelta(minutes=5)).normalize().nunique()),
        'supply_comparison_definition': 'D=requests in (t-5m,t]; idle=drivers free at t; effective=idle+arriving_0_5+0.5*arriving_5_10+0.2*arriving_10_15',

        'demand_vmr': float((g['var'] / g['mean']).median()),
        'est_error_median': float(estimate_error.median()),
        'open_at_cutoff': int((o.dropoff_ts.isna() & o.cancel_ts.isna()).sum()),
        'utilization_definition': 'mean of five end-of-minute state samples per window; not exact driver-minutes',
        **ds_ratio_summary(s.demand, s.effective_supply),
    }
    by_zone = s.groupby('zone').agg(demand_mean=('demand', 'mean'), idle_mean=('supply', 'mean'), eta_sec_mean=('eta_sec', 'mean'), surge_mean=('surge_multiplier', 'mean'))
    by_zone['orders'] = o.groupby('zone').size()
    by_zone['effective_supply_mean'] = s.groupby('zone').effective_supply.mean()
    by_zone['demand_gt_effective_share'] = s.groupby('zone').demand_gt_effective.mean()
    by_hour = s.groupby('hour').agg(demand_mean=('demand', 'mean'), idle_mean=('supply', 'mean'), eta_sec_mean=('eta_sec', 'mean'))
    by_hour['effective_supply_mean'] = s.groupby('hour').effective_supply.mean()
    by_hour['demand_gt_effective_share'] = s.groupby('hour').demand_gt_effective.mean()
    city_hour = (city.index - pd.Timedelta(minutes=5)).hour
    by_hour['city_demand_gt_effective_share'] = city_short.groupby(city_hour).mean()
    return metrics, by_zone, by_hour
