"""Trích 1 ngày từ hcm_data_2 thành JSON nhỏ cho dashboard prototype."""
import json, sys
import numpy as np, pandas as pd, pyarrow.dataset as ds

ROOT = "data/hcm_data_2"
DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-01-27"

def load(name, day):
    d = ds.dataset(f"{ROOT}/{name}", format="parquet", partitioning="hive")
    return d.to_table(filter=ds.field("date") == day).to_pandas()

hexes = ds.dataset(f"{ROOT}/raw/hexes", format="parquet").to_table().to_pandas()
hexes = hexes.sort_values("hex_id").reset_index(drop=True)
idx = {h: i for i, h in enumerate(hexes.hex_id)}

try:
    import h3
    bound = {h: [[lat, lng] for lat, lng in h3.cell_to_boundary(h)] for h in hexes.hex_id}
except Exception:
    r = 0.0125
    bound = {}
    for h, la, ln in zip(hexes.hex_id, hexes.lat, hexes.lng):
        bound[h] = [[la + r * np.sin(a), ln + r * np.cos(a) * 1.0] for a in np.arange(6) * np.pi / 3 + np.pi / 6]

f = load("features/hex_features", DAY)
f["ts"] = pd.to_datetime(f["ts"])
f = f.sort_values(["ts", "hex_id"])
ts = sorted(f.ts.unique())
T, N = len(ts), len(hexes)
def mat(col):
    m = np.zeros((T, N))
    tix = {t: i for i, t in enumerate(ts)}
    ti = f.ts.map(tix).values
    hi = f.hex_id.map(idx).values
    m[ti, hi] = f[col].values
    return m

D = mat("demand_5m"); S = mat("effective_supply_t"); I = mat("idle_supply_t")
SG = mat("current_surge_t"); NP = mat("neighbor_pressure_mean_t"); ETA = mat("eta_sec_t")

e = load("features/graph_edges", DAY)
e["ts"] = pd.to_datetime(e["ts"])
adj = e[e.edge_is_adjacent == 1][["src_hex", "dst_hex"]].drop_duplicates()
adj = [[idx[a], idx[b]] for a, b in adj.values if a != b and a in idx and b in idx]
od = e[(e.edge_is_od == 1) & (e.src_hex != e.dst_hex)].copy()
od["hour"] = od.ts.dt.hour
od = od.groupby(["hour", "src_hex", "dst_hex"]).od_requests_30m.mean().reset_index()
od_hour = []
for h in range(24):
    x = od[od.hour == h].nlargest(60, "od_requests_30m")
    od_hour.append([[idx[a], idx[b], round(float(w), 2)] for a, b, w in x[["src_hex", "dst_hex", "od_requests_30m"]].values])

r = lambda m, k=2: np.round(m, k).tolist()
out = dict(
    day=DAY,
    ts=[pd.Timestamp(t).strftime("%H:%M") for t in ts],
    hexes=[dict(id=h, zone=z, ring=int(rg), lat=float(la), lng=float(ln), poly=bound[h])
           for h, z, rg, la, ln in zip(hexes.hex_id, hexes.zone, hexes.ring, hexes.lat, hexes.lng)],
    D=r(D, 0), S=r(S, 2), I=r(I, 0), surge=r(SG, 1), npress=r(NP, 3), eta=r(ETA, 0),
    adj=adj, od=od_hour,
)
with open("ui/data.json", "w") as fh:
    json.dump(out, fh, separators=(",", ":"))
print(T, N, len(adj), sum(map(len, od_hour)))

# nhúng data vào template -> dashboard.html (mở trực tiếp bằng trình duyệt, không cần server)
tpl = open("ui/dashboard.template.html", encoding="utf-8").read()
open("ui/dashboard.html", "w", encoding="utf-8").write(tpl.replace("__DATA__", open("ui/data.json", encoding="utf-8").read()))
