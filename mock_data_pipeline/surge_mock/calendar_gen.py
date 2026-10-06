"""Exogenous schedule: day factors, rain, venue events, drain events, airport waves, ramps (spec 3, 4.10, 5).

All times are minutes on the simulation axis, where 0 = 00:00 of the first burn-in day.
Everything here is independent of the graph-signal strength g.
"""
from dataclasses import dataclass, field

import numpy as np

from .config import parse_hhmm
from .geo import ZID


@dataclass
class Calendar:
    n_days: int
    burn: int
    n_total_days: int
    real_day: np.ndarray            # [D] 1-based real day index (<=0 for burn-in)
    dow: np.ndarray                 # [D] 0=Mon
    dow_factor: np.ndarray          # [D]
    delta: np.ndarray               # [D] LogNormal day factor
    a_drain: np.ndarray             # [D] S2a attractiveness of office at 16-19
    drain_jitter: np.ndarray        # [D] minutes shift of the 16:00 boundary
    rain_days: list = field(default_factory=list)       # 1-based real days
    rain_episodes: list = field(default_factory=list)   # (start, end, intensity)
    venue_events: list = field(default_factory=list)    # dict(end, size, pre_min, day)
    drain_events: list = field(default_factory=list)    # dict(start, end, hex)
    airport_waves: list = field(default_factory=list)   # dict(start, load)
    ramps: list = field(default_factory=list)           # dict(day, peak_min, m, zones)

    @property
    def n_minutes(self):
        return self.n_total_days * 1440


def _pick_with_constraints(rng, n, ranges, universe):
    """Pick n distinct days; at least one inside each given (lo, hi) range."""
    chosen = []
    for lo, hi in ranges:
        pool = [d for d in range(lo, hi + 1) if d not in chosen]
        chosen.append(int(rng.choice(pool)))
    rest = [d for d in universe if d not in chosen]
    k = min(max(0, n - len(chosen)), len(rest))
    if k:
        chosen += [int(x) for x in rng.choice(rest, size=k, replace=False)]
    return sorted(chosen)


def build_calendar(cfg, geo, rng):
    N, b = cfg.n_days, cfg.burn_in_days
    D = N + b
    real_day = np.arange(D) - b + 1
    dow = (real_day - 1) % 7
    het = cfg.heterogeneity
    dow_map = [het["dow"][k] for k in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
    dow_factor = np.array([dow_map[x] for x in dow])
    delta = rng.lognormal(0.0, het["day_sigma"], D)
    delta[:b] = 1.0
    sg = cfg.signals
    a_drain = rng.uniform(*sg["s2a"]["attract_range"], D)
    jitter = rng.uniform(-sg["s2a"]["start_jitter_min"], sg["s2a"]["start_jitter_min"], D)

    cal = Calendar(N, b, D, real_day, dow, dow_factor, delta, a_drain, jitter)
    split = cfg.split
    val, test, train = split["val"], split["test"], split["train"]
    all_days = list(range(1, N + 1))

    def abs_min(day, minute):
        return (day - 1 + b) * 1440 + minute

    # --- rain (spec 4.10)
    rc = cfg.rain
    cal.rain_days = _pick_with_constraints(rng, rc["days"], [tuple(train), tuple(val), tuple(test)], all_days)
    a0, a1 = parse_hhmm(rc["afternoon_window"][0]), parse_hhmm(rc["afternoon_window"][1])
    for day in cal.rain_days:
        for _ in range(int(rng.integers(rc["episodes_per_day"][0], rc["episodes_per_day"][1] + 1))):
            if rng.random() < rc["afternoon_share"]:
                st = rng.uniform(a0, a1)
            else:
                st = rng.uniform(0, 1440)
            dur = rng.uniform(*rc["episode_min"])
            inten = rng.uniform(*rc["intensity_range"])
            s = abs_min(day, st)
            cal.rain_episodes.append((s, s + dur, inten))

    # --- S4 venue events
    s4 = sg["s4"]
    days = _pick_with_constraints(rng, s4["events"], [tuple(val), tuple(test)], all_days)
    e0, e1 = parse_hhmm(s4["end_range"][0]), parse_hhmm(s4["end_range"][1])
    for day in days:
        cal.venue_events.append(dict(
            day=day, end=abs_min(day, rng.uniform(e0, e1)),
            size=float(rng.uniform(*s4["size_range"])),
            pre_min=float(rng.uniform(*s4["pre_hours"]) * 60)))

    # --- S2b irregular drain events
    s2b = sg["s2b"]
    n_drain = int(round(s2b["per_week"] * N / 7))
    cand = np.concatenate([geo.hexes_of(z) for z in s2b["zones"]])
    h0, h1 = parse_hhmm(s2b["hours"][0]), parse_hhmm(s2b["hours"][1])
    for _ in range(n_drain):
        day = int(rng.integers(1, N + 1))
        st = abs_min(day, rng.uniform(h0, h1))
        dur = rng.uniform(*s2b["duration_min"])
        cal.drain_events.append(dict(start=st, end=st + dur, hex=int(rng.choice(cand))))
    cal.drain_events.sort(key=lambda e: e["start"])

    # --- S3 airport arrival banks (every day, burn-in included)
    s3 = sg["s3"]
    for d in range(D):
        for bank in s3["banks"]:
            st = d * 1440 + parse_hhmm(bank) + rng.normal(0, s3["delay_sd_min"])
            cal.airport_waves.append(dict(start=st, load=float(rng.lognormal(0, s3["load_sigma"]))))

    # --- S1 ramps (weekdays only)
    s1 = sg["s1_ramp"]
    for d in range(b, D):
        if dow[d] >= 5:
            continue
        for pk in s1["peaks"]:
            t = d * 1440 + parse_hhmm(pk["time"]) + rng.uniform(-s1["peak_jitter_min"], s1["peak_jitter_min"])
            cal.ramps.append(dict(day=d, peak=t, m=float(rng.uniform(*s1["range"])),
                                  zones=[ZID[z] for z in pk["zones"]]))
    return cal
