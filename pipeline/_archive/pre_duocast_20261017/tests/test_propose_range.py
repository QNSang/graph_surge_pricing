import json
from datetime import datetime, timedelta

import numpy as np
import pytest
import torch

from surge_ml.errors import SurgeError
from surge_ml.features import IDX_CURRENT_SURGE, VARIANTS
from surge_ml.models.dual_gru_gatv2 import build_model
from surge_ml.orchestration.propose import (
    ProposalContext,
    _forecast,
    build_report,
    resolve_cutoffs,
    write_proposal_range,
)
from surge_ml.training.trainer import resolve_device

from conftest import N_SNAPSHOTS, synthetic_data

FIRST_TS = "2026-01-01T00:00:00"


def _context(cfg, tmp_path) -> ProposalContext:
    data = synthetic_data()
    n = data.x.shape[1]
    data.manifest = {"first_ts": FIRST_TS, "hex_ids": [f"h{i}" for i in range(n)], "dataset_id": "x"}
    torch.manual_seed(0)
    variant = VARIANTS["gru_gatv2_40"]
    raw_x = np.random.default_rng(1).uniform(1.0, 1.5, size=(N_SNAPSHOTS, n, 40))
    return ProposalContext(
        cfg=cfg, variant_name="gru_gatv2_40", variant=variant, seed=1,
        checkpoint_path=tmp_path / "best.pt", config_sha="sha", data=data,
        model=build_model(variant, cfg.model), device=resolve_device("cpu"), raw_x=raw_x,
        derived_dir=tmp_path, source_manifest={"data_fingerprint": "fp", "timezone": "Asia/Ho_Chi_Minh"},
    )


def test_resolve_cutoffs_split_range_and_stride(cfg, tmp_path):
    data = _context(cfg, tmp_path).data
    test_ks = data.candidates("test")
    np.testing.assert_array_equal(resolve_cutoffs(data, split="test"), test_ks)
    np.testing.assert_array_equal(resolve_cutoffs(data, split="test", stride=12), test_ks[::12])
    k0 = int(test_ks[0])
    np.testing.assert_array_equal(resolve_cutoffs(data, from_cutoff=k0, to_cutoff=k0 + 3), np.arange(k0, k0 + 4))
    with pytest.raises(SurgeError):
        resolve_cutoffs(data, from_cutoff=0, to_cutoff=3)  # inside warmup, not an eligible sample
    with pytest.raises(SurgeError):
        resolve_cutoffs(data, split="test", stride=0)


def test_range_matches_single_cutoff_reports(cfg, tmp_path):
    ctx = _context(cfg, tmp_path)
    k0 = int(ctx.data.candidates("test")[0])
    ks = np.arange(k0, k0 + 5, dtype=np.int64)
    index_path = write_proposal_range(ctx, ks, tmp_path / "surge")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == "surge_proposal_index_v1"
    assert index["count"] == 5 and [e["cutoff_index"] for e in index["cutoffs"]] == ks.tolist()
    first = datetime.fromisoformat(FIRST_TS)
    for entry in index["cutoffs"]:
        report = json.loads((tmp_path / "surge" / entry["file"]).read_text(encoding="utf-8"))
        k = entry["cutoff_index"]
        assert report["schema_version"] == "surge_proposal_v1"
        assert report["split"] == "test" and report["cutoff_index"] == k
        assert datetime.fromisoformat(report["cutoff_ts_local"]) == first + timedelta(minutes=5 * k)
        assert report["data_fingerprint"] == "fp" and report["deployment_eligible"] is False
        assert [r["hex_id"] for r in report["proposals"]] == ctx.data.manifest["hex_ids"]
        np.testing.assert_allclose([r["bidding"] for r in report["proposals"]], ctx.raw_x[k, :, IDX_CURRENT_SURGE])

        # Batched forecasting must give the same proposals as a one-cutoff run.
        single = _forecast(ctx, np.array([k], dtype=np.int64))
        expected = build_report(ctx, k, single["local"][0], single["graph"][0])
        for got, want in zip(report["proposals"], expected["proposals"]):
            assert got["status"] == want["status"]
            assert got["final_surge"] == pytest.approx(want["final_surge"], abs=1e-6)
