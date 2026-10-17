"""MO-06/07: validation independent of MILP matrices, solver status and auxiliaries.

Reconstruct the canonical candidate table from the original frozen inputs, then
recompute all hard constraints/objective components from selected discrete IDs.
"""
from __future__ import annotations
import math
from ..contracts import Candidate, CandidateTable, ConstraintChecks, Metrics
from ..errors import require
from ..integration.operational_context import PreparedNetwork, prepare_network
from ..simulation.candidates import build_candidates, outcome


def validate_selection(network: PreparedNetwork, table: CandidateTable,
                       selected_ids: tuple[str, ...]) -> tuple[tuple[Candidate, ...], Metrics, ConstraintChecks]:
    network = prepare_network(network.forecast, network.operational, network.response, network.policy)
    table = CandidateTable.model_validate(table)
    canonical = build_candidates(network)
    require(table.identity == canonical.identity and table.forecast_run_id == canonical.forecast_run_id
            and table.response_version == canonical.response_version
            and table.policy_config_version == canonical.policy_config_version and table.currency == canonical.currency,
            "POST_VALIDATION_FAILED", "Candidate table provenance mismatch")
    expected = {candidate.candidate_id: candidate for candidate in canonical.candidates}
    actual = {candidate.candidate_id: candidate for candidate in table.candidates}
    require(set(actual) == set(expected), "POST_VALIDATION_FAILED", "Candidate grid is incomplete or contains unknown IDs")
    # No display rounding is authorized in the numerical candidate transport.
    require(all(actual[key] == expected[key] for key in expected),
            "POST_VALIDATION_FAILED", "Candidate coefficients differ from original input recomputation")
    require(len(selected_ids) == len(network.identity.required_hex_ids)
            and len(set(selected_ids)) == len(selected_ids) and all(key in expected for key in selected_ids),
            "POST_VALIDATION_FAILED", "Missing, duplicate or unknown selected candidate")
    selected = tuple(expected[key] for key in selected_ids)
    require(tuple(c.hex_id for c in selected) == network.identity.required_hex_ids,
            "POST_VALIDATION_FAILED", "Selected network is incomplete or incorrectly ordered")
    policy = network.policy
    total_quotes = math.fsum(row.quote_opportunities for row in network.operational.rows)
    total_demand = math.fsum(c.outcome.expected_demand for c in selected)
    booking_rate = total_demand / total_quotes
    nominal_delta = math.fsum(c.incremental_gmv for c in selected)
    require(policy.br_min - policy.feasibility_tolerance <= booking_rate
            <= policy.br_max + policy.feasibility_tolerance,
            "POST_VALIDATION_FAILED", f"Booking rate hard constraint failed: {booking_rate}")
    require(nominal_delta >= -policy.money_tolerance, "POST_VALIDATION_FAILED",
            f"Nominal modeled network GMV no-loss failed: {nominal_delta}")
    conservative = math.fsum(c.conservative_utility for c in selected)
    temporal = policy.lambda_temporal * math.fsum(float(abs(c.action)) for c in selected)
    surges = {c.hex_id: c.proposed_surge for c in selected}
    # Actual selected surge differences, never the solver's d variables (which
    # need not be tight when the spatial penalty is zero).
    spatial = policy.lambda_spatial * math.fsum(
        edge.weight * float(abs(surges[edge.source] - surges[edge.target]))
        for edge in network.operational.pricing_edges)
    reference_gmv = math.fsum(outcome(network, i, row.current_surge, cell.beta, cell.gamma).expected_gmv
                              for i, (row, cell) in enumerate(zip(network.operational.rows, network.response.cells)))
    metrics = Metrics(booking_rate=booking_rate, expected_demand=total_demand,
                      quote_opportunities=total_quotes,
                      expected_gmv=math.fsum(c.outcome.expected_gmv for c in selected),
                      reference_gmv=reference_gmv, nominal_incremental_gmv=nominal_delta,
                      conservative_utility=conservative, temporal_penalty=temporal,
                      spatial_penalty=spatial, objective=conservative - temporal - spatial)
    checks = ConstraintChecks(validator_version="ggso.independent.v1", coverage=True, identity=True,
                              grid_and_bounds=True, candidate_recomputed=True, booking_rate=True,
                              nominal_no_loss=True, integrality=True)
    return selected, metrics, checks
