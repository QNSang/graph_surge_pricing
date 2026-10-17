"""MO-05: HiGHS transport/status decoding. No solver status certifies a policy.

SciPy status convention: 0 solved, 1 limit, 2 infeasible, 3 unbounded, 4 error.
An incumbent from status 0/1 still requires the independent policy validator.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import time
import numpy as np
import scipy
from scipy.optimize import milp
from ..config import PolicyConfig
from ..contracts import SolverInfo
from ..errors import require
from .milp import Problem


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
