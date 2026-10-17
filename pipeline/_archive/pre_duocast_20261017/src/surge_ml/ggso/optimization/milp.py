"""MO-01..04: exactly-one MILP, hard BR/no-loss, temporal/spatial penalties."""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from scipy.optimize import Bounds, LinearConstraint
from scipy.sparse import csc_matrix
from ..config import PolicyConfig
from ..contracts import CandidateTable, OperationalSnapshot
from ..errors import require


@dataclass(frozen=True)
class Problem:
    c: np.ndarray
    integrality: np.ndarray
    bounds: Bounds
    constraints: LinearConstraint
    candidate_ids: tuple[str, ...]
    candidate_hex_ids: tuple[str, ...]
    node_order: tuple[str, ...]
    n_binary: int
    monetary_scale: float


def build_problem(table: CandidateTable, operational: OperationalSnapshot, policy: PolicyConfig) -> Problem:
    table = CandidateTable.model_validate(table)
    operational = OperationalSnapshot.model_validate(operational)
    policy = PolicyConfig.model_validate(policy)
    require(table.identity == operational.identity and table.policy_config_version == policy.version
            and table.currency == operational.currency == policy.currency,
            "INPUT_INVALID", "MILP snapshot/policy/currency mismatch")
    candidates, edges = table.candidates, operational.pricing_edges
    n, m, scale = len(candidates), len(edges), policy.monetary_scale
    by_hex = {hex_id: [j for j, c in enumerate(candidates) if c.hex_id == hex_id]
              for hex_id in table.identity.required_hex_ids}
    total_quotes = math.fsum(row.quote_opportunities for row in operational.rows)
    require(total_quotes > 0 and math.isfinite(total_quotes), "INPUT_INVALID", "Undefined quote denominator")
    cost = np.array([-(c.conservative_utility - policy.lambda_temporal * float(abs(c.action))) / scale
                     for c in candidates] + [policy.lambda_spatial * e.weight / scale for e in edges])
    rows, columns, values, low, high = [], [], [], [], []

    def add(coefficients: dict[int, float], lower: float, upper: float) -> None:
        row_index = len(low)
        for column, value in coefficients.items():
            if value != 0:
                rows.append(row_index)
                columns.append(column)
                values.append(value)
        low.append(lower)
        high.append(upper)

    for hex_id in table.identity.required_hex_ids:
        require(bool(by_hex[hex_id]), "NO_CANDIDATES", f"Missing required cell {hex_id}")
        add({j: 1.0 for j in by_hex[hex_id]}, 1.0, 1.0)
    add({j: c.outcome.expected_demand for j, c in enumerate(candidates)},
        policy.br_min * total_quotes, policy.br_max * total_quotes)
    # Nominal modeled incremental GMV, NOT the conservative objective.
    add({j: c.incremental_gmv / scale for j, c in enumerate(candidates)}, 0.0, np.inf)
    for edge_index, edge in enumerate(edges):
        coefficients = {j: float(candidates[j].proposed_surge) for j in by_hex[edge.source]}
        coefficients.update({j: -float(candidates[j].proposed_surge) for j in by_hex[edge.target]})
        add({**coefficients, n + edge_index: -1.0}, -np.inf, 0.0)
        add({**{j: -value for j, value in coefficients.items()}, n + edge_index: -1.0}, -np.inf, 0.0)
    matrix = csc_matrix((values, (rows, columns)), shape=(len(low), n + m), dtype=float)
    require(np.isfinite(cost).all() and np.isfinite(matrix.data).all(),
            "INPUT_INVALID", "Nonfinite MILP coefficients")
    span = float(policy.surge_max - policy.surge_min)
    return Problem(c=cost, integrality=np.r_[np.ones(n, dtype=int), np.zeros(m, dtype=int)],
                   bounds=Bounds(np.zeros(n + m), np.r_[np.ones(n), np.full(m, span)]),
                   constraints=LinearConstraint(matrix, np.asarray(low), np.asarray(high)),
                   candidate_ids=tuple(c.candidate_id for c in candidates),
                   candidate_hex_ids=tuple(c.hex_id for c in candidates),
                   node_order=table.identity.required_hex_ids, n_binary=n, monetary_scale=scale)
