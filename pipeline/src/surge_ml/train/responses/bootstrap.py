from __future__ import annotations
import hashlib
import math
import numpy as np
from ._types import FitConfig
from .glm import fit_demand, fit_fulfillment
from surge_ml.contracts.response import Scenario
from surge_ml.datasets.responses import Arrays
from surge_ml.errors import GGSOError, require

def paired_scenarios(data: Arrays, config: FitConfig, hex_id: str) -> tuple[Scenario, ...]:
    n, block = len(data.demand), config.bootstrap_block_size
    require(1 <= block <= n, "RESPONSE_INVALID", "Bootstrap block exceeds training window")
    stable_cell_seed = int.from_bytes(hashlib.sha256(hex_id.encode()).digest()[:4], "little")
    rng = np.random.default_rng(np.random.SeedSequence([config.seed, stable_cell_seed]))
    scenarios = []
    for replicate in range(config.bootstrap_replicates):
        starts = rng.integers(0, n - block + 1, size=math.ceil(n / block))
        indices = np.concatenate([np.arange(start, start + block) for start in starts])[:n]
        sample = data.take(indices)  # D, C, K, price, contexts share exactly the same sampled rows.
        try:
            demand = fit_demand(sample.demand, sample.surge, sample.demand_context, config)
            fulfillment = fit_fulfillment(sample.demand, sample.completed, sample.capacity,
                                          sample.fulfillment_context, config)
        except (ValueError, FloatingPointError) as exc:
            raise GGSOError("BOOTSTRAP_FAILED", f"Cell {hex_id}, replicate {replicate}: {exc}") from exc
        scenarios.append(Scenario(scenario_id=f"block-bootstrap-{replicate:04d}", beta=demand.beta,
                                  gamma=fulfillment.gamma, weight=1.0 / config.bootstrap_replicates))
    return tuple(scenarios)
