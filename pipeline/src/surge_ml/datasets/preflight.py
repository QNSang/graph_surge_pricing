"""Read-only DuoCast input preflight. Structural validation is not business-semantic approval.

Run from the repository root:
  uv run --offline --no-sync --project pipeline python -m surge_ml.datasets.preflight --config pipeline/configs/duocast.yaml
An optional --output writes one new JSON file and refuses to overwrite an existing report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from surge_ml._constant import CONTRACT_VERSION
from surge_ml._utils.io import digest_file
from surge_ml.datasets.duocast import load_panel, make_splits, split_manifest
from surge_ml.train.duocast._types import load_config


def inspect_dataset(config_path: str | Path) -> dict:
    """Validate all available input tables and chronological samples without training.

    The loader checks timestamp availability, H3 mapping, observed physical-driver
    mobility, integer targets, and complete coverage. Metadata field names assert
    source semantics; they cannot independently prove the upstream event taxonomy.
    """
    cfg = load_config(config_path)
    panel = load_panel(cfg.data)
    splits = make_splits(len(panel.timestamps), cfg.data)
    paths = {
        kind: getattr(cfg.data, kind)
        for kind in ("market", "spatial", "mobility", "mobility_snapshots", "metadata")
    }
    return {
        "status": "INPUT_STRUCTURE_VALIDATED",
        "contract_version": CONTRACT_VERSION,
        "dataset_id": panel.metadata["dataset_id"],
        "data_fingerprint": panel.fingerprint,
        "synthetic": panel.metadata.get("synthetic") is True,
        "production_eligible": False,
        "source_semantics_verified": False,
        "semantic_verification_note": "Metadata asserts booking/driver-OD meaning; independent source-event/driver-state parity has not been verified.",
        "node_mapping_version": panel.metadata["node_mapping_version"],
        "feature_definition_version": panel.metadata["feature_definition_version"],
        "spatial_graph_version": panel.metadata["spatial_graph_version"],
        "nodes": panel.n_nodes,
        "snapshots": len(panel.timestamps),
        "first_timestamp": panel.timestamps[0].isoformat(),
        "last_timestamp": panel.timestamps[-1].isoformat(),
        "history_steps": cfg.data.history,
        "horizon_steps": cfg.data.horizon,
        "spatial_directed_edges": int(panel.spatial_index.shape[1]),
        "observed_mobility_edges": int(panel.mobility_index.shape[1]),
        "observed_empty_mobility_snapshots": int(np.count_nonzero(np.diff(panel.mobility_ptr) == 0)),
        "split_manifest": split_manifest(panel, splits, cfg.data),
        "input_sha256": {name: digest_file(path) for name, path in paths.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate DuoCast data before training; no fitting or promotion.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Optional new JSON file; existing files are not overwritten")
    args = parser.parse_args(argv)
    try:
        report = inspect_dataset(args.config)
        serialized = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        print(serialized, end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"DuoCast preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
