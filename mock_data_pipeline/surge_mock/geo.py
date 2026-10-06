"""Spatial layer: 61 H3 res-7 hexes, zones (spec 2.1), distances, adjacency, per-hex factors (spec 2.2)."""
import math

import h3
import numpy as np

ZONES = ["cbd", "office", "venue", "residential", "suburb", "airport"]
ZID = {z: i for i, z in enumerate(ZONES)}
HEX_AREA_KM2 = 5.16


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lng2) - np.radians(lng1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


class Geo:
    def __init__(self, cfg, rng):
        center = h3.latlng_to_cell(cfg.center_lat, cfg.center_lng, cfg.h3_res)
        R = cfg.ring_radius
        cells = list(h3.grid_disk(center, R))
        ring = {c: h3.grid_distance(center, c) for c in cells}
        clat, clng = h3.cell_to_latlng(center)

        def ang(c):
            la, ln = h3.cell_to_latlng(c)
            return math.atan2(la - clat, ln - clng)

        # deterministic order: ring, then angle
        cells.sort(key=lambda c: (ring[c], ang(c)))
        self.cells = cells
        self.n = len(cells)
        self.index = {c: i for i, c in enumerate(cells)}
        self.ring = np.array([ring[c] for c in cells], dtype=np.int32)
        self.center_idx = self.index[center]

        zone = np.full(self.n, -1, dtype=np.int32)
        for i, c in enumerate(cells):
            r = ring[c]
            if r <= 1:
                zone[i] = ZID["cbd"]
            elif r == 2:
                zone[i] = ZID["office"]
            elif r == 3:
                zone[i] = ZID["residential"]
            else:
                zone[i] = ZID["suburb"]
        ring2 = [i for i in range(self.n) if self.ring[i] == 2]
        self.venue_idx = int(rng.choice(ring2))
        zone[self.venue_idx] = ZID["venue"]
        ring4 = [i for i in range(self.n) if self.ring[i] == R]  # already angle-ordered
        k = int(rng.integers(len(ring4)))
        airport = [ring4[(k + j) % len(ring4)] for j in range(3)]
        for i in airport:
            zone[i] = ZID["airport"]
        self.airport_idx = sorted(airport)
        self.zone = zone

        lat = np.empty(self.n)
        lng = np.empty(self.n)
        for i, c in enumerate(cells):
            lat[i], lng[i] = h3.cell_to_latlng(c)
        self.lat, self.lng = lat, lng
        self.dist_km = haversine_km(lat[:, None], lng[:, None], lat[None, :], lng[None, :])
        self.hex_dist = np.array(
            [[h3.grid_distance(a, b) for b in cells] for a in cells], dtype=np.int32)

        adj = np.full((self.n, 6), -1, dtype=np.int32)
        adj_n = np.zeros(self.n, dtype=np.int32)
        for i, c in enumerate(cells):
            for nb in h3.grid_ring(c, 1):
                j = self.index.get(nb)
                if j is not None:
                    adj[i, adj_n[i]] = j
                    adj_n[i] += 1
        self.adj, self.adj_n = adj, adj_n
        self.intra_radius_km = math.sqrt(HEX_AREA_KM2 / math.pi)

        het = cfg.heterogeneity
        self.eta_D = rng.lognormal(0.0, het["hex_demand_sigma"], self.n)
        self.eta_A = rng.lognormal(0.0, het["hex_attract_sigma"], self.n)

        # S7: airport hexes and the suburb hexes touching them
        s7 = np.zeros(self.n, dtype=bool)
        for i in self.airport_idx:
            s7[i] = True
            for j in adj[i, :adj_n[i]]:
                if zone[j] == ZID["suburb"]:
                    s7[j] = True
        self.s7_boundary = s7
        self.s6_sparse = zone == ZID["suburb"]

    def hexes_of(self, zone_name):
        return np.where(self.zone == ZID[zone_name])[0]

    def static_table(self):
        import pandas as pd
        return pd.DataFrame({
            "hex_id": self.cells, "zone": [ZONES[z] for z in self.zone], "ring": self.ring,
            "lat": self.lat, "lng": self.lng,
        })
