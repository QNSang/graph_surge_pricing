from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timezone
from surge_ml.contracts import DecisionResult, Forecast, Identity, OperationalSnapshot, Recommendation, ResponseArtifact
from surge_ml.errors import GGSOError, require
from .schemas import PolicyConfig, prepare_network
from .network_optimizer import accepted_info, decode_incumbent, solve, build_problem
from .validator import validate_selection
from .candidate_utility import build_candidates, canonical_decimal

def run_decision(*, identity, operational, response, policy, forecast_provider: Callable[[Identity], Forecast],
                 generated_at: datetime | None = None, solve_fn=solve) -> DecisionResult:
    timestamp = datetime.now(timezone.utc)
    parsed_identity = parsed_policy = parsed_response = forecast = solver_info = None
    trace = []
    stage = "INPUT_INVALID"
    try:
        if generated_at is not None:
            require(isinstance(generated_at, datetime) and generated_at.tzinfo is not None
                    and generated_at.utcoffset() is not None, "INPUT_INVALID", "Aware generation timestamp required")
            timestamp = generated_at
        parsed_identity = Identity.model_validate(identity)
        parsed_policy = PolicyConfig.model_validate(policy)
        operational = OperationalSnapshot.model_validate(operational)
        require(timestamp >= parsed_identity.cutoff_time, "INPUT_INVALID", "Result predates information cutoff")
        require(parsed_identity == operational.identity, "SEMANTIC_MISMATCH", "Operational snapshot identity mismatch")
        trace.append("INPUT_FROZEN")
        stage = "RESPONSE_INVALID"
        parsed_response = ResponseArtifact.model_validate(response)
        trace.append("RESPONSE_LOADED")
        stage = "FORECAST_INVALID"
        forecast = Forecast.model_validate(forecast_provider(parsed_identity))
        if generated_at is None:
            timestamp = datetime.now(timezone.utc)
        require(forecast.identity == parsed_identity and forecast.generated_at <= timestamp,
                "FORECAST_INVALID", "Forecast identity or generation timestamp mismatch")
        trace.append("NETWORK_FORECAST_ONCE")
        stage = "INPUT_INVALID"
        network = prepare_network(forecast, operational, parsed_response, parsed_policy)
        trace.append("SEMANTICS_VALIDATED")
        stage = "CANDIDATE_INVALID"
        table = build_candidates(network)
        trace.append("CANDIDATES_BUILT")
        stage = "SOLVER_NO_ACCEPTABLE_SOLUTION"
        problem = build_problem(table, operational, parsed_policy)
        attempt = solve_fn(problem, parsed_policy)
        solver_info = attempt.info
        selected_ids = decode_incumbent(problem, attempt, parsed_policy)
        trace.append("INCUMBENT_DECODED")
        stage = "POST_VALIDATION_FAILED"
        selected, metrics, checks = validate_selection(network, table, selected_ids)
        solver_info = accepted_info(attempt)
        trace.append("INDEPENDENT_VALIDATION_PASS")
        recommendations = tuple(Recommendation(candidate_id=c.candidate_id, hex_id=c.hex_id,
                                 action="INCREASE" if c.action > 0 else "DECREASE" if c.action < 0 else "HOLD",
                                 surge_base=row.current_surge, surge_delta=c.action, surge_proposed=c.proposed_surge)
                                for c, row in zip(selected, operational.rows))
        if generated_at is None:
            timestamp = datetime.now(timezone.utc)
        return DecisionResult(usage="TEST_ONLY", schema_version="ggso.decision.v2", result_status="VALID",
                              identity=parsed_identity, generated_at=timestamp,
                              forecast_version=f"{forecast.forecast_model_id}:{forecast.checkpoint_version}",
                              response_version=parsed_response.artifact_version,
                              policy_config_version=parsed_policy.version, currency=parsed_policy.currency,
                              error_code=None, diagnostics=(), trace=tuple(trace), selected_candidates=selected,
                              recommendations=recommendations,
                              optimized_policy={c.hex_id: canonical_decimal(c.proposed_surge) for c in selected},
                              estimated_metrics=metrics, constraint_checks=checks, solver=solver_info)
    except Exception as exc:
        code = exc.code if isinstance(exc, GGSOError) else stage
        if not isinstance(exc, (ValueError, ArithmeticError, TypeError)):
            code = "INTERNAL_ERROR"
        trace.append(f"FAILED:{stage}")
        return DecisionResult(usage="TEST_ONLY", schema_version="ggso.decision.v2", result_status="INVALID",
                              identity=parsed_identity, generated_at=timestamp,
                              forecast_version=None if forecast is None else
                              f"{forecast.forecast_model_id}:{forecast.checkpoint_version}",
                              response_version=None if parsed_response is None else parsed_response.artifact_version,
                              policy_config_version=None if parsed_policy is None else parsed_policy.version,
                              currency=None if parsed_policy is None else parsed_policy.currency,
                              error_code=code, diagnostics=(f"{type(exc).__name__}: {str(exc)[:1500]}",),
                              trace=tuple(trace), selected_candidates=(), recommendations=(), optimized_policy=None,
                              estimated_metrics=None, constraint_checks=None, solver=solver_info)


def replay_payload(payload: dict) -> DecisionResult:
    if not isinstance(payload, dict) or set(payload) != {"identity", "policy", "operational", "response", "forecast"}:
        raise ValueError("Replay requires exactly identity, policy, operational, response and forecast")
    forecast = payload["forecast"]
    # Parsing errors are handled inside the same fail-closed decision boundary.
    try:
        generated_at = Forecast.model_validate(forecast).generated_at
    except ValueError:
        generated_at = None
    return run_decision(identity=payload["identity"], policy=payload["policy"], operational=payload["operational"],
                        response=payload["response"], forecast_provider=lambda _: forecast, generated_at=generated_at)
