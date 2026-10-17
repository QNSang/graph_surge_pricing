import json
from pathlib import Path

from surge_ml.config import load_config
from surge_ml.contracts import TARGET_CONTRACT_ID, W, split_candidates
from surge_ml.features import (EDGE_DIM, N_EDGE_FEATURES, N_NODE_FEATURES, VARIANTS, WINDOW, candidates,
                               split_bounds)


ROOT = Path(__file__).resolve().parents[1]


def test_json_contract_matches_runtime_constants():
    contract = json.loads((ROOT / "configs" / "feature_contract.json").read_text(encoding="utf-8"))
    assert contract["target_contract_id"] == TARGET_CONTRACT_ID
    assert contract["temporal"]["window_steps"] == W == WINDOW == 4
    assert contract["dimensions"]["node"] == N_NODE_FEATURES == 40
    assert contract["dimensions"]["edge_raw"] == N_EDGE_FEATURES == 10
    assert contract["dimensions"]["edge_internal"] == EDGE_DIM == 11
    assert contract["target"]["inverse"] == "exp"
    reference = {"30d_21_4_5": (30, {"train": [1, 21], "val": [22, 25], "test": [26, 30]}),
                 "90d_63_13_14": (90, {"train": [1, 63], "val": [64, 76], "test": [77, 90]})}
    for name, (days, split_days) in reference.items():
        splits = split_bounds(split_days, days)
        counts = {s: len(candidates(s, splits)) for s in splits}
        assert counts == {s: len(split_candidates(*b)) for s, b in splits.items()}
        assert contract["temporal"]["reference_candidate_counts"][name] == counts
        for window in (4, 6):
            assert {s: len(candidates(s, splits, window)) for s in splits} == \
                   {s: len(split_candidates(*b, window)) for s, b in splits.items()}


def test_benchmark_plan_matches_train_config_and_runtime_variants():
    cfg = load_config(ROOT / "configs" / "train.yaml")
    plan = json.loads((ROOT / "configs" / "benchmark_plan.json").read_text(encoding="utf-8"))
    planned = [row["variant_id"] for row in plan["variants"] if row["enabled"]]
    assert plan["base_config_path"] == "train.yaml"
    assert plan["seeds"] == cfg.seeds
    assert planned == cfg.variants
    assert set(planned) <= set(VARIANTS)
    assert plan["controller_evaluation"]["deployment_eligible"] is False
