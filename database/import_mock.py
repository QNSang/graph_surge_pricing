"""Import the current mock dataset into the schema defined in database/schema.sql.

Loads reference rows (region, hexes, node mapping, metric), one dataset_releases row,
one snapshot per 5-minute cutoff and one hex_market_states row per (snapshot, hex).
Burn-in tables are skipped: they are history only and are not part of the main period.

The dataset is resolved from data/CURRENT.json, never hardcoded. The import runs in a
single transaction and is skipped when the dataset fingerprint is already present
(dataset rows are immutable, so a re-import needs a fresh database).

Usage (pyarrow, psycopg and pyyaml are available in backend/.venv):
    docker compose up -d --wait            (repo root compose.yaml, project graph_surge_pricing)
    backend/.venv/Scripts/python database/import_mock.py
    backend/.venv/Scripts/python database/import_mock.py --dsn postgresql://user:pw@host:port/db
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.dataset as ds
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = REPO_ROOT / "database" / "schema.sql"
DEFAULT_DSN = "postgresql://surge:surge@localhost:5434/surge_erd"

REGION_ID = "hcmc"
REGION_LABEL = "Ho Chi Minh City"
METRIC_ID = "ds_eff_observed.v1"
ZERO_SUPPLY_REASON = "ZERO_EFFECTIVE_SUPPLY"
COPY_CHUNK_ROWS = 200_000

RAW_COLUMNS = ["ts", "hex_id", "demand", "supply", "eta_sec", "surge_multiplier"]
FEATURE_COLUMNS = ["ts", "hex_id", "demand_5m", "idle_supply_t", "effective_supply_t"]


def load_release() -> dict:
    current = json.loads((REPO_ROOT / "data" / "CURRENT.json").read_text(encoding="utf-8"))
    root = REPO_ROOT / current["path"]
    manifest = json.loads((REPO_ROOT / current["manifest"]).read_text(encoding="utf-8"))
    schema = yaml.safe_load((REPO_ROOT / current["schema"]).read_text(encoding="utf-8"))
    contract = json.loads((root / manifest["feature_contract"]).read_text(encoding="utf-8"))
    if manifest["data_fingerprint"] != current["data_fingerprint"]:
        sys.exit("CURRENT.json and manifest.json disagree on data_fingerprint")
    return {"current": current, "root": root, "manifest": manifest, "schema": schema, "contract": contract}


def apply_schema_if_missing(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('public.hex_market_states')").fetchone()[0]
        if exists is None:
            print("applying database/schema.sql")
            conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))


def read_table(root: Path, rel: str, columns: list[str]) -> pa.Table:
    table = ds.dataset(root / rel, format="parquet", partitioning="hive").to_table(columns=columns)
    # Source timestamps are naive local time; microseconds keep the CSV parseable by PostgreSQL.
    return table.set_column(0, "ts", table.column("ts").cast(pa.timestamp("us")))


def copy_table(cur: psycopg.Cursor, target: str, table: pa.Table) -> None:
    options = pacsv.WriteOptions(include_header=False)
    with cur.copy(f"COPY {target} FROM STDIN (FORMAT csv)") as copy:
        for batch in table.to_batches(max_chunksize=COPY_CHUNK_ROWS):
            buf = io.BytesIO()
            pacsv.write_csv(pa.Table.from_batches([batch]), buf, options)
            copy.write(buf.getvalue())


def import_dataset(dsn: str, rel: dict) -> None:
    current, manifest, schema, contract = rel["current"], rel["manifest"], rel["schema"], rel["contract"]
    dataset = schema["dataset"]
    tz = manifest["timezone"]
    hex_ids = contract["hex_ids"]
    expected_rows = manifest["hex_count"] * manifest["days"] * 24 * 60 // manifest["snapshot_minutes"]

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT dataset_id FROM dataset_releases WHERE fingerprint = %s", (current["data_fingerprint"],))
        if cur.fetchone():
            print(f"dataset {current['dataset_id']} already imported; nothing to do")
            return

        t0 = time.perf_counter()
        hexes = ds.dataset(rel["root"] / "raw" / "hexes", format="parquet").to_table().to_pylist()
        if sorted(h["hex_id"] for h in hexes) != sorted(hex_ids):
            sys.exit("raw/hexes and feature_contract.hex_ids differ")

        cur.execute(
            "INSERT INTO regions (region_id, label, timezone, h3_resolution) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (region_id) DO NOTHING",
            (REGION_ID, REGION_LABEL, tz, dataset["h3_resolution"]),
        )
        cur.executemany(
            "INSERT INTO hexes (hex_id, region_id, zone, ring, lat, lng) VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (hex_id) DO NOTHING",
            [(h["hex_id"], REGION_ID, h["zone"], h["ring"], h["lat"], h["lng"]) for h in hexes],
        )

        # Node order is the feature contract's hex_ids order, the same order the pipeline uses.
        cur.execute(
            "INSERT INTO node_mappings (region_id, version) VALUES (%s, %s)"
            " ON CONFLICT (region_id, version) DO NOTHING",
            (REGION_ID, manifest["feature_version"]),
        )
        cur.execute(
            "SELECT node_mapping_id FROM node_mappings WHERE region_id = %s AND version = %s",
            (REGION_ID, manifest["feature_version"]),
        )
        node_mapping_id = cur.fetchone()[0]
        cur.executemany(
            "INSERT INTO node_mapping_hexes (node_mapping_id, hex_id, node_index) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            [(node_mapping_id, hex_id, i) for i, hex_id in enumerate(hex_ids)],
        )

        cur.execute(
            "INSERT INTO metric_definitions (metric_id, display_name, equation, units, zero_supply_policy, description)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (metric_id) DO NOTHING",
            (
                METRIC_ID,
                "Observed D/S (effective supply)",
                "demand_5m / effective_supply_t, rounded to 4 decimals",
                "ratio",
                "NULL_WITH_REASON",
                manifest.get("eda_metrics", {}).get("ds_eff_definition"),
            ),
        )

        release_meta = {
            k: manifest[k]
            for k in (
                "days", "hex_count", "start_date", "end_exclusive", "timezone", "snapshot_minutes", "seed",
                "case", "feature_version", "row_counts", "limitations", "readiness_scope",
                "realism_validation_complete", "deployment_ready", "data_fingerprint_rule", "prepared_at_utc",
            )
            if k in manifest
        }
        cur.execute(
            "INSERT INTO dataset_releases (dataset_key, fingerprint, layout_version, schema_version, source_path,"
            " data_kind, observation_metric_id, metadata) VALUES (%s, %s, %s, %s, %s, 'SYNTHETIC', %s, %s)"
            " RETURNING dataset_id",
            (
                current["dataset_id"],
                current["data_fingerprint"],
                current["layout_version"],
                dataset["feature_contract"],
                current["path"],
                METRIC_ID,
                json.dumps(release_meta),
            ),
        )
        dataset_id = cur.fetchone()[0]

        cur.execute(
            "CREATE TEMP TABLE stg_raw (ts timestamp, hex_id text, demand int, supply int,"
            " eta_sec float8, surge_multiplier float8) ON COMMIT DROP"
        )
        cur.execute(
            "CREATE TEMP TABLE stg_feat (ts timestamp, hex_id text, demand_5m real, idle_supply_t real,"
            " effective_supply_t real) ON COMMIT DROP"
        )
        copy_table(cur, "stg_raw", read_table(rel["root"], "raw/hex_snapshot", RAW_COLUMNS))
        copy_table(cur, "stg_feat", read_table(rel["root"], "features/hex_features", FEATURE_COLUMNS))
        cur.execute("ANALYZE stg_raw; ANALYZE stg_feat")
        print(f"staged parquet in {time.perf_counter() - t0:.1f}s")

        cur.execute(
            "SELECT (SELECT count(*) FROM stg_raw), (SELECT count(*) FROM stg_feat),"
            " (SELECT count(*) FROM stg_raw r JOIN stg_feat f USING (ts, hex_id)),"
            " (SELECT count(*) FROM stg_raw r JOIN stg_feat f USING (ts, hex_id)"
            "   WHERE r.demand <> f.demand_5m OR r.supply <> f.idle_supply_t)"
        )
        raw_n, feat_n, joined_n, mismatch_n = cur.fetchone()
        if not (raw_n == feat_n == joined_n == expected_rows) or mismatch_n:
            sys.exit(
                f"staging check failed: raw={raw_n} features={feat_n} joined={joined_n}"
                f" expected={expected_rows} demand/supply mismatches={mismatch_n}"
            )

        cur.execute(
            "INSERT INTO snapshots (dataset_id, region_id, node_mapping_id, cutoff_ts)"
            " SELECT %s, %s, %s, ts AT TIME ZONE %s FROM (SELECT DISTINCT ts FROM stg_raw) t ORDER BY ts",
            (dataset_id, REGION_ID, node_mapping_id, tz),
        )
        snapshot_n = cur.rowcount

        cur.execute(
            """
            INSERT INTO hex_market_states (snapshot_id, hex_id, demand, idle_supply, effective_supply,
                observed_ds, observed_ds_null_reason, eta_sec, surge_base, bidding_source_version)
            SELECT s.snapshot_id, r.hex_id, r.demand, r.supply,
                   round(f.effective_supply_t::numeric, 4)::float8,
                   CASE WHEN f.effective_supply_t > 0
                        THEN round(r.demand::numeric / f.effective_supply_t::numeric, 4)::float8 END,
                   CASE WHEN f.effective_supply_t > 0 THEN NULL ELSE %s END,
                   r.eta_sec,
                   round(r.surge_multiplier::numeric, 4),
                   %s
            FROM stg_raw r
            JOIN stg_feat f USING (ts, hex_id)
            JOIN snapshots s ON s.dataset_id = %s AND s.region_id = %s
                            AND s.node_mapping_id = %s AND s.cutoff_ts = r.ts AT TIME ZONE %s
            """,
            (
                ZERO_SUPPLY_REASON,
                f"{current['layout_version']}:raw/hex_snapshot.surge_multiplier",
                dataset_id,
                REGION_ID,
                node_mapping_id,
                tz,
            ),
        )
        market_n = cur.rowcount
        if market_n != expected_rows:
            sys.exit(f"hex_market_states inserted {market_n}, expected {expected_rows}")
        conn.commit()
        print(f"imported dataset_id={dataset_id}: {snapshot_n} snapshots, {market_n} market states"
              f" in {time.perf_counter() - t0:.1f}s")

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("ANALYZE snapshots; ANALYZE hex_market_states")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=os.environ.get("SURGE_ERD_DSN", DEFAULT_DSN))
    args = parser.parse_args()
    rel = load_release()
    apply_schema_if_missing(args.dsn)
    import_dataset(args.dsn, rel)


if __name__ == "__main__":
    main()
