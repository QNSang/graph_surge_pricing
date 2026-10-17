"""CS-01..07: deterministic additive grid and paired counterfactual arithmetic.

The only truncation is the specified completed-ride capacity ceiling. Prices,
forecast counts, scenario samples and utility values are never rounded/clipped.
"""
from __future__ import annotations
import hashlib
import json
import math
from decimal import Decimal
import numpy as np
from scipy.special import expit
from ..contracts import Candidate, CandidateTable, Outcome, RejectedCandidate
from ..errors import GGSOError, require
from ..integration.operational_context import PreparedNetwork, prepare_network
from .capacity import capacity_value

GRID = tuple(Decimal(i) / Decimal(10) for i in range(-3, 4))


def canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def rejection_reasons(network: PreparedNetwork, index: int, action: Decimal) -> tuple[str, ...]:
    row, cell, policy = network.operational.rows[index], network.response.cells[index], network.policy
    surge = row.current_surge + action
    reasons = []
    if action not in GRID or abs(action) > policy.delta_max:
        reasons.append("ACTION_OUTSIDE_GRID")
    if not policy.surge_min <= surge <= policy.surge_max:
        reasons.append("SURGE_OUTSIDE_BOUNDS")
    if surge <= 0:
        reasons.append("NONPOSITIVE_SURGE")
    if not cell.support.surge_min <= surge <= cell.support.surge_max:
        reasons.append("SURGE_OUTSIDE_RESPONSE_SUPPORT")
    return tuple(reasons)


def outcome(network: PreparedNetwork, index: int, surge: Decimal, beta: float, gamma: float) -> Outcome:
    forecast = network.forecast.rows[index]
    row, cell = network.operational.rows[index], network.response.cells[index]
    s, base, epsilon = float(surge), float(row.current_surge), network.policy.epsilon
    require(math.isfinite(s) and math.isfinite(base) and s > 0 and base > 0,
            "INPUT_INVALID", "Price is outside the numerical domain")
    require(math.isfinite(beta) and 0 <= beta <= 4 and math.isfinite(gamma) and 0 <= gamma <= 1,
            "RESPONSE_INVALID", "Invalid response coefficient")
    capacity = capacity_value(forecast.forecast_supply, row.capacity)
    demand = forecast.forecast_demand
    if demand and surge != row.current_surge:
        demand *= math.exp(-beta * (math.log(s) - math.log(base)))
    context = cell.fulfillment_transform.apply(row.fulfillment_context, check_support=True)
    intercept = cell.fulfillment_intercept + math.fsum(v * c for v, c in
                                                       zip(cell.fulfillment_coefficients, context))
    # Algebraically equivalent to baseline-logit + demand-ratio update; avoids
    # a numerically unstable logit(sigmoid(baseline_logit)) round trip.
    logit = intercept + gamma * (math.log(capacity + epsilon) - math.log(demand + epsilon))
    require(all(math.isfinite(x) for x in (capacity, demand, logit)),
            "INPUT_INVALID", "Nonfinite candidate calculation")
    fulfillment = float(expit(logit))
    completed = min(demand * fulfillment, capacity)
    gmv = completed * row.reference_fare * s
    require(0 <= completed <= demand and completed <= capacity,
            "INPUT_INVALID", "Completed-ride ceiling violated")
    return Outcome(expected_demand=float(demand), fulfillment_rate=fulfillment,
                   expected_completed=float(completed), expected_gmv=float(gmv))


def evaluate_candidate(network: PreparedNetwork, index: int, action: Decimal) -> Candidate:
    reasons = rejection_reasons(network, index, action)
    require(not reasons, "CANDIDATE_REJECTED", ";".join(reasons))
    row, cell = network.operational.rows[index], network.response.cells[index]
    surge = row.current_surge + action
    nominal = outcome(network, index, surge, cell.beta, cell.gamma)
    require(nominal.expected_demand <= row.quote_opportunities, "CANDIDATE_REJECTED",
            "DEMAND_EXCEEDS_QUOTES")
    baseline = outcome(network, index, row.current_surge, cell.beta, cell.gamma)
    increments = []
    for scenario in cell.scenarios:
        # Baseline is recomputed WITH THIS gamma, not borrowed from nominal.
        candidate_scenario = outcome(network, index, surge, scenario.beta, scenario.gamma)
        baseline_scenario = outcome(network, index, row.current_surge, scenario.beta, scenario.gamma)
        increments.append(candidate_scenario.expected_gmv - baseline_scenario.expected_gmv)
    identity = network.identity
    key = [identity.model_dump(mode="json"), network.forecast.forecast_run_id,
           network.response.artifact_version, network.policy.version, row.hex_id,
           canonical_decimal(action), canonical_decimal(surge)]
    candidate_id = hashlib.sha256(json.dumps(key, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return Candidate(candidate_id=candidate_id, decision_id=identity.decision_id,
                     snapshot_id=identity.snapshot_id, hex_id=row.hex_id,
                     action=action, proposed_surge=surge, outcome=nominal,
                     incremental_gmv=float(nominal.expected_gmv - baseline.expected_gmv),
                     conservative_utility=float(np.quantile(increments, network.policy.quantile, method="linear")),
                     scenario_ids=tuple(s.scenario_id for s in cell.scenarios),
                     scenario_increments=tuple(float(x) for x in increments))


def build_candidates(network: PreparedNetwork) -> CandidateTable:
    network = prepare_network(network.forecast, network.operational, network.response, network.policy)
    candidates, rejected = [], []
    for index, row in enumerate(network.operational.rows):
        cell_count = 0
        for action in GRID:
            reasons = rejection_reasons(network, index, action)
            if not reasons:
                try:
                    candidates.append(evaluate_candidate(network, index, action))
                    cell_count += 1
                except GGSOError as exc:
                    if exc.code != "CANDIDATE_REJECTED":
                        raise
                    reasons = (str(exc),)
            if reasons:
                rejected.append(RejectedCandidate(hex_id=row.hex_id, action=action,
                                                   proposed_surge=row.current_surge + action, reasons=reasons))
        require(cell_count > 0, "NO_CANDIDATES", f"No eligible candidate for required cell {row.hex_id}")
    return CandidateTable(usage="TEST_ONLY", schema_version="ggso.candidates.v1", identity=network.identity,
                          forecast_run_id=network.forecast.forecast_run_id,
                          response_version=network.response.artifact_version,
                          policy_config_version=network.policy.version, currency=network.policy.currency,
                          candidates=tuple(candidates), rejected=tuple(rejected))
