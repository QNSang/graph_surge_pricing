from __future__ import annotations
from dataclasses import dataclass
import math
import time
import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix
from surge_ml.contracts.decision import CandidateTable, OperationalSnapshot, SolverInfo
from surge_ml.errors import require
from .schemas import PolicyConfig

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


@dataclass(frozen=True)
class SolveAttempt:
    info: SolverInfo
    x: np.ndarray | None


def _finite_optional(value, *, scale: float = 1.0):
    if value is None:
        return None
    number = float(value) * scale
    return number if math.isfinite(number) else None


def solve(problem: Problem, policy: PolicyConfig) -> SolveAttempt:
    started = time.perf_counter()
    try:
        result = milp(c=problem.c, integrality=problem.integrality, bounds=problem.bounds,
                      constraints=problem.constraints,
                      options={"time_limit": policy.solver_time_limit_seconds,
                               "mip_rel_gap": policy.solver_mip_rel_gap})
        raw_status = int(result.status)
        message = str(result.message)
        x = None if result.x is None else np.asarray(result.x, dtype=float).copy()
        objective = _finite_optional(getattr(result, "fun", None), scale=-problem.monetary_scale)
        bound = _finite_optional(getattr(result, "mip_dual_bound", None), scale=-problem.monetary_scale)
        gap = _finite_optional(getattr(result, "mip_gap", None))
        if gap is not None and gap < 0:
            gap = None
    except Exception as exc:
        # Keep a typed technical failure; never invent an incumbent or fallback.
        raw_status, message, x = None, f"{type(exc).__name__}: {exc}", None
        objective = bound = gap = None
    info = SolverInfo(engine="scipy.optimize.milp/HiGHS", scipy_version=scipy.__version__,
                      raw_status=raw_status, message=message, accepted_status="REJECTED",
                      runtime_seconds=time.perf_counter() - started, raw_objective=objective,
                      dual_bound=bound, mip_gap=gap)
    return SolveAttempt(info=info, x=x)


def decode_incumbent(problem: Problem, attempt: SolveAttempt, policy: PolicyConfig) -> tuple[str, ...]:
    require(attempt.info.raw_status in (0, 1) and attempt.x is not None,
            "SOLVER_NO_ACCEPTABLE_SOLUTION", attempt.info.message)
    x = np.asarray(attempt.x, dtype=float)
    require(x.shape == problem.c.shape and np.isfinite(x).all(),
            "POST_VALIDATION_FAILED", "Wrong-sized/nonfinite incumbent")
    tolerance = policy.integrality_tolerance
    binary = x[:problem.n_binary]
    rounded = np.rint(binary)
    require(np.all(np.abs(binary - rounded) <= tolerance) and np.isin(rounded, [0, 1]).all(),
            "POST_VALIDATION_FAILED", "Fractional/out-of-range candidate selection")
    require(np.all(x >= problem.bounds.lb - policy.feasibility_tolerance)
            and np.all(x <= problem.bounds.ub + policy.feasibility_tolerance),
            "POST_VALIDATION_FAILED", "Incumbent variable bound violation")
    selected = {}
    for index in np.flatnonzero(rounded == 1):
        hex_id = problem.candidate_hex_ids[index]
        require(hex_id not in selected, "POST_VALIDATION_FAILED", "Multiple selected candidates for a cell")
        selected[hex_id] = problem.candidate_ids[index]
    require(set(selected) == set(problem.node_order), "POST_VALIDATION_FAILED", "Incomplete incumbent network")
    return tuple(selected[hex_id] for hex_id in problem.node_order)


def accepted_info(attempt: SolveAttempt) -> SolverInfo:
    """Call ONLY after independent validation; preserve nullable raw gap/bound."""
    require(attempt.info.raw_status in (0, 1), "POST_VALIDATION_FAILED", "Non-acceptable solver status")
    if attempt.info.raw_status == 1:
        status = "FEASIBLE_LIMIT"
    elif attempt.info.mip_gap == 0.0:
        status = "OPTIMAL"
    else:
        status = "FEASIBLE_GAP"
    return SolverInfo.model_validate({**attempt.info.model_dump(), "accepted_status": status})
