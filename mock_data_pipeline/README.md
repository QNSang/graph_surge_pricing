# Mock data pipeline (HCMC, spec v3)

Generates the synthetic ride-hailing data described in `docs/data/mock_data_spec_hcmc.md`: 61 H3 res-7 hexes around
District 1, a minute-level driver/order simulation, and the raw tables the surge-pricing model trains on.
Everything is seeded and reproducible.

## Usage

```bash
pip install -r requirements.txt

# full 61-day g1.0 dataset, written flat into ../data/hcmc_g1.0
python -m scripts.generate --profile full --out ../data/hcmc_g1.0

# optional spec ablations: g0.5, g0.0 and the shuffled control (then --out has one subfolder per dataset)
python -m scripts.generate --profile full --out output_ablation --g 1.0 0.5 0.0 --shuffled

# 35-day development set, handy for calibration
python -m scripts.generate --profile dev --out output_dev

# override any config value (dotted key)
python -m scripts.generate --profile dev --out output_dev --set demand.scale=1.5 drivers.online_scale=0.6

# check section 8 of the spec; writes validation_report.md and validation_metrics.json into the output folder
python -m scripts.validate --out ../data/hcmc_g1.0

python -m pytest tests
```

The first run compiles the Numba kernel (about 20 s, cached afterwards). A full 61-day set takes a few minutes;
validation is the slower part (about 35 s per dataset).

## Layout

```
data/hcmc_g1.0/
  config.yaml            resolved config used for the run
  hexes.parquet          static hex table: hex_id, lat, lng, zone, ring, s6_sparse, s7_boundary, ...
  calendar.json          rain episodes, venue events, drain events, airport hexes (minutes on the simulation axis)
  validation_report.md   section 8 metrics
  orders/                raw orders (spec 1.2), partitioned by date=YYYY-MM-DD of created_ts
  hex_snapshot_5min/     demand, supply, eta_sec, surge_multiplier per hex and 5-minute window
  weather_5min/          rain_intensity
  signal_truth/          ground-truth flags s1..s7 per hex and window (never a model input)
  _debug/                driver stats and waiting counts, only needed by validate; not part of the data contract
```

With `--g` listing several strengths or `--shuffled`, each dataset gets its own subfolder (`g1.0/`, `g0.5/`,
`g0.0/`, `g1.0_shuffled/`) next to the shared files.

Conventions:

- `ts` of a snapshot row is the **end** of its window. The first row is 00:05 on 2026-01-05 and the last is 24:00 of
  the last day. Window tables are partitioned by the date of `ts - 5 min`, so the 24:00 row sits in the last day.
- `orders` are partitioned by the date of `created_ts`; orders still open at the end of the horizon are kept.
- One burn-in day is simulated before 2026-01-05 so drivers and queues are warm. It is never exported.
- `g0.0`, `g0.5`, `g1.0` (optional ablations) differ only in how strongly origin-destination structure (destination attractiveness and the
  gravity length) is used. Origin demand and exogenous events are identical across them, so the sets are comparable.
- `g1.0_shuffled` (optional) is `g1.0` with `dest_hex` permuted within (origin zone, calendar hour). It is a table-level control;
  every other table is a copy of `g1.0`.

## Code map

| Module | Role |
|---|---|
| `surge_mock/config.py`, `config.yaml` | config, profiles (`full`, `dev`), overrides |
| `surge_mock/geo.py` | hex grid, zones, distances, adjacency, S6/S7 flags |
| `surge_mock/calendar_gen.py` | day factors, rain, venue events, drain events, airport waves, ramps |
| `surge_mock/exogenous.py` | demand intensity per minute and hex, intents, online-driver target, destination inputs |
| `surge_mock/kernel.py` | Numba kernel: shifts, matching, cancellation, repositioning, base surge, snapshots |
| `surge_mock/simulate.py` | runs the kernel for one `g`, builds the raw tables, shuffled control |
| `surge_mock/writers.py`, `pipeline.py` | partitioned parquet, end-to-end orchestration |
| `surge_mock/validate.py` | spec section 8 metrics and the 8.1 signal checks |

## Calibration notes

The spec lets the parameters be assumptions as long as the section 8 metrics hold. The values in `config.yaml` that
differ from spec section 9 are:

| Parameter | Spec | Here | Why |
|---|---|---|---|
| `demand.scale` | (none) | 1.6 | global multiplier on `base_per_min`; sets order volume against driver supply |
| `drivers.online_scale` | (none) | 0.55 | global multiplier on `online_target` |
| `drivers.online_target` | 250 / 1800 / 1400 / 1900 / 1100 | 800 / 1650 / 2000 / 1700 / 1700 | the spec shape gives off-peak utilisation above 55% once demand is scaled to peak |
| `drivers.reposition` | prob 0.10, power 2, idle 5 min | prob 0.7, power 8, idle 2 min | with the spec values idle drivers pile up in suburb hexes (suburb demand + supply stays above 6) |
| `demand.patience_mean_min` | 6 | 4 | slightly more no-driver cancellations at peak |
| `base_surge.gain` | 0.6 | 0.5 | keeps the share of snapshot rows with surge above 1 inside 15-30% |
| `base_surge.step` | 0.1 | 0.05 | finer surge resolution; surge stays in [1.0, 3.0] |
| `base_surge.deadzone` | none | 0.15 | log demand/supply ratio below this gives no surge; keeps the share of rows above 1 under 30% at step 0.05 |
| `demand.base_per_min.airport` | 0.1 | 0.06 | airport trip share inside 3-6% |
| `signals.s3.wave_per_min` | 1.5 | 1.0 | same |

Repositioning weights follow the spec: the destination hex is chosen with probability proportional to the neighbour's
surge multiplier to the power `power`, not to its idle driver count.

## Known gap against section 8

Overall completion rate stays around 0.94-0.96 against the 0.75-0.90 target. At peak it is about 0.92-0.94 and it is
lower in rain, as the spec asks, but off-peak it is about 0.97. Bringing the overall rate under 0.90 would need
off-peak utilisation above 55%, because the matching rule (same hex, then an adjacent hex) rarely leaves an order
unserved while idle drivers are around. See `validation_report.md` for the exact figures of the shipped set.

## Known gap against section 8.1

- S3 and S4 behave as intended: inbound orders to the airport/venue in flagged windows are about 1.9x / 2.8x the same
  time of day on unflagged days at `g1.0`, about 1.5x / 1.9x at `g0.5`, and no different at `g0.0`.
- The S2 check (`s2_corr_outflow_y15` against `s2_corr_dsratio_y15`) is only a proxy here: it uses the in-trip outbound
  count of the hex, which carries no destination information. It does not change with `g` and does not vanish at
  `g0.0`, so it cannot confirm S2. Use a model-level check (a GNN against a GRU-only baseline, spec 8.2) for that.
- `g1.0_shuffled` keeps the hourly inbound spike at the venue, because the permutation is within (origin zone, hour).
  It removes the origin-destination pairing, not the aggregate in-flow. Its trip distance and intra-hex share fall
  outside the section 8 ranges by construction.
