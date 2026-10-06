"""Exogenous drivers of the simulation, all precomputed on the minute / 5-minute axis.

Independent of the dynamics (matching, pricing), so they are built once per dataset:
  - mu            [T, H]  expected ride intents per minute per hex (spec 4.1), without the Gamma mixing
  - intents       [T, H]  Poisson(mu * G) counts; identical for every g (origin demand is not scaled by g)
  - rain, vpeak, online target per minute
  - dest inputs per 5-minute window, which depend on g (spec 5.1)
  - signal_truth flags (spec 1.4)
"""
import numpy as np

from .config import khung_bounds
from .geo import ZID, ZONES

SNAP = 5


def hour_curves(cfg):
    """Per-zone, per-minute demand profile p_z for each day of week -> [7, Z, 1440] (spec 4.1).

    Linear interpolation between khung centres (periodic over 24h), normalised so the weekday
    mean is 1. Weekend office/residential use the flat khung 10-15 value (same normaliser as weekday).
    """
    keys = list(cfg.hour_profile_p.keys())
    centers, vals = [], []
    for k in keys:
        a, b = khung_bounds(k)
        centers.append((a + b + 1) / 2 * 60)
        vals.append(cfg.hour_profile_p[k])
    vals = np.array(vals, dtype=float)             # [5, Z]
    x = np.arange(1440, dtype=float)
    weekday = np.stack([np.interp(x, centers, vals[:, z], period=1440) for z in range(len(ZONES))])
    norm = 1.0 / weekday.mean(axis=1, keepdims=True)
    weekday = weekday * norm
    i_mid = keys.index("10-15")
    pt = np.empty((7, len(ZONES), 1440))
    night = x >= 18 * 60
    fsn = cfg.demand["fri_sat_night_mult"]
    for dow in range(7):
        p = weekday.copy()
        if dow >= 5:
            for z in ("office", "residential"):
                zi = ZID[z]
                p[zi] = vals[i_mid, zi] * norm[zi, 0]
        if dow in (4, 5):
            for z in ("cbd", "venue"):
                p[ZID[z], night] *= fsn
        pt[dow] = p
    return pt


def attract_table(cfg):
    """A_z per khung -> [5, Z], NaN where S2a overwrites (office 16-19)."""
    keys = list(cfg.attract_A.keys())
    tab = np.array([[np.nan if v is None else v for v in cfg.attract_A[k]] for k in keys], dtype=float)
    return keys, tab


class Exogenous:
    def __init__(self, cfg, geo, cal, rng):
        self.cfg, self.geo, self.cal = cfg, geo, cal
        T, H = cal.n_minutes, geo.n
        self.T, self.H, self.W = T, H, T // SNAP
        W = self.W
        tm = np.arange(T)
        self.day_idx = tm // 1440
        self.mod = tm % 1440
        dow_t = cal.dow[self.day_idx]
        rc = cfg.rain

        rain = np.zeros(T)
        for s, e, inten in cal.rain_episodes:
            i0, i1 = int(max(0, round(s))), int(min(T, round(e)))
            rain[i0:i1] = np.maximum(rain[i0:i1], inten)
        self.rain = rain
        hour = self.mod // 60
        self.vpeak = (dow_t < 5) & (((hour >= 6) & (hour < 10)) | ((hour >= 16) & (hour < 20)))

        # --- origin demand mu
        pt = hour_curves(cfg)
        B = np.array([cfg.demand["base_per_min"][z] for z in ZONES]) * cfg.demand["scale"]
        base_h = B[geo.zone] * geo.eta_D
        P = pt[dow_t[:, None], geo.zone[None, :], self.mod[:, None]]
        day_f = (cal.dow_factor * cal.delta)[self.day_idx]
        mu = base_h[None, :] * P * (day_f * (1.0 + rc["demand_per_intensity"] * rain))[:, None]

        # S1 ramp: triangle 1 -> m over lead minutes before the peak, back to 1 over decay minutes
        s1 = cfg.signals["s1_ramp"]
        ramp = np.ones((T, H))
        lead, decay = s1["lead_min"], s1["decay_min"]
        for r in cal.ramps:
            hexes = np.where(np.isin(geo.zone, r["zones"]))[0]
            x = np.arange(int(round(r["peak"] - lead)), int(round(r["peak"] + decay)))
            x = x[(x >= 0) & (x < T)]
            dt = x - r["peak"]
            f = np.where(dt < 0, 1 + (r["m"] - 1) * (1 + dt / lead), 1 + (r["m"] - 1) * (1 - dt / decay))
            f = np.clip(f, 1.0, None)
            ix = np.ix_(x, hexes)
            ramp[ix] = np.maximum(ramp[ix], f[:, None])
        mu *= ramp
        self.ramp = ramp.astype(np.float32)

        # S2b origin boost, S4 post-event boost
        s2b, s4 = cfg.signals["s2b"], cfg.signals["s4"]
        for ev in cal.drain_events:
            i0, i1 = int(round(ev["start"])), int(min(T, round(ev["end"])))
            mu[i0:i1, ev["hex"]] *= s2b["demand_mult"]
        for ev in cal.venue_events:
            i0, i1 = int(round(ev["end"])), int(min(T, round(ev["end"] + s4["post_min"])))
            mu[i0:i1, geo.venue_idx] *= ev["size"]
        # S3 airport waves (additive)
        s3 = cfg.signals["s3"]
        for wv in cal.airport_waves:
            i0, i1 = int(round(wv["start"])), int(min(T, round(wv["start"] + s3["wave_min"])))
            if i0 >= T or i1 <= 0:
                continue
            for a in geo.airport_idx:
                mu[max(0, i0):i1, a] += s3["wave_per_min"] * wv["load"]
        self.mu = mu

        # --- Poisson-Gamma intents (spec 4.1): Gamma(k, 1/k) independent per 5-minute window and hex
        k = cfg.demand["gamma_k"]
        G = rng.gamma(k, 1.0 / k, size=(W, H))
        self.intents = rng.poisson(mu * np.repeat(G, SNAP, axis=0)).astype(np.int32)

        # --- online driver target per minute (spec 4.5)
        dc = cfg.drivers
        keys = list(dc["online_target"].keys())
        centers = [(khung_bounds(k_)[0] + khung_bounds(k_)[1] + 1) / 2 * 60 for k_ in keys]
        tvals = [dc["online_target"][k_] for k_ in keys]
        tgt = np.interp(self.mod, centers, tvals, period=1440)
        tgt = tgt * (cal.delta[self.day_idx] ** dc["day_elasticity"]) * dc["online_scale"]
        tgt = tgt * np.where(rain > 0, rc["driver_factor"], 1.0)
        self.target = np.round(tgt).astype(np.int64)

        self._build_windows()

    # ------------------------------------------------------------------
    def _active(self, start, end):
        """Boolean over windows: window midpoint in [start, end)."""
        mid = np.arange(self.W) * SNAP + SNAP / 2
        return (mid >= start) & (mid < end)

    def _build_windows(self):
        cfg, geo, cal, W, H = self.cfg, self.geo, self.cal, self.W, self.H
        mid = np.arange(W) * SNAP + SNAP / 2
        d = (mid // 1440).astype(int)
        mod = mid % 1440
        wk = cal.dow[d] >= 5
        jit = cal.drain_jitter[d]
        # khung index; the 16:00 boundary moves by the daily jitter (S2a)
        kh = np.where(mod < 360, 0, np.where(mod < 600, 1, np.where(mod < 960 + jit, 2,
                      np.where(mod < 1200, 3, 4))))
        _, tab = attract_table(cfg)
        Az = tab[kh].copy()                                   # [W, Z]
        oi = ZID["office"]
        Az[:, oi] = np.where(kh == 3, cal.a_drain[d], Az[:, oi])
        for z in ("office", "residential"):                    # weekend: flat khung 10-15
            zi = ZID[z]
            Az[wk, zi] = tab[2, zi]
        self.A_zone = Az
        s2a = (kh == 3) & ~wk & (cal.real_day[d] >= 1)

        # signal_truth flags
        s2 = np.zeros((W, H), dtype=bool)
        s2[np.ix_(s2a, geo.hexes_of("office"))] = True
        s3 = np.zeros((W, H), dtype=bool)
        s4 = np.zeros((W, H), dtype=bool)
        sg = cfg.signals
        for ev in cal.drain_events:
            s2[self._active(ev["start"], ev["end"]), ev["hex"]] = True
        for wv in cal.airport_waves:
            a = self._active(wv["start"] - sg["s3"]["pre_inbound_min"], wv["start"] + sg["s3"]["wave_min"])
            for ai in geo.airport_idx:
                s3[a, ai] = True
        for ev in cal.venue_events:
            a = self._active(ev["end"] - ev["pre_min"], ev["end"] + sg["s4"]["post_min"])
            s4[a, geo.venue_idx] = True
        self.truth = dict(
            s1_ramp=self.ramp[SNAP - 1::SNAP][:W], s2_drain=s2, s3_airport=s3, s4_venue=s4,
            s5_rain=self.rain[SNAP - 1::SNAP][:W].astype(np.float32))

    def dest_inputs(self, g):
        """Per-window destination attractiveness [W, H] and gravity length [W, H] for strength g (spec 5.1)."""
        cfg, geo, cal, W, H = self.cfg, self.geo, self.cal, self.W, self.H
        sg = cfg.signals
        Ag = (1.0 - g) + g * self.A_zone                      # [W, Z]
        A = Ag[:, geo.zone] * geo.eta_A[None, :]
        L0 = cfg.demand["gravity_L_km"]
        L = np.full((W, H), L0)
        for ev in cal.drain_events:
            a = self._active(ev["start"], ev["end"])
            A[a, ev["hex"]] *= 1.0 + g * (sg["s2b"]["self_attract_mult"] - 1.0)
            L[a, ev["hex"]] = L0 + g * (sg["s2b"]["dest_L_km"] - L0)
        for wv in cal.airport_waves:
            a = self._active(wv["start"] - sg["s3"]["pre_inbound_min"], wv["start"])
            for ai in geo.airport_idx:
                A[a, ai] *= 1.0 + g * sg["s3"]["pre_inbound_mult"] * wv["load"]
        for ev in cal.venue_events:
            a = self._active(ev["end"] - ev["pre_min"], ev["end"])
            A[a, geo.venue_idx] *= 1.0 + g * (sg["s4"]["pre_attract_mult"] - 1.0)
        return A, L
