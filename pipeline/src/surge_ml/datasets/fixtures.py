"""Explicit synthetic fixtures. These are not a historical-data fallback."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import json
import numpy as np
import pandas as pd
import yaml
from scipy.special import expit
from surge_ml._constant import SEMANTIC_PROFILE, CONTRACT_VERSION, DEMAND_DEFINITION, SUPPLY_DEFINITION
from surge_ml.contracts import *
from surge_ml.train.responses._types import FitConfig
from surge_ml.inferences.schemas import PolicyConfig, prepare_network
from surge_ml.inferences.duocast import DuoCastMockAdapter, MockCheckpoint
from surge_ml.datasets.responses import Observation
FIXTURE_VERSION = 'ggso.synthetic-fixture.v2'

@dataclass(frozen=True)
class Fixture:
    identity: Identity
    policy: PolicyConfig
    operational: OperationalSnapshot
    response: ResponseArtifact
    forecast: Forecast

    def network(self):
        return prepare_network(self.forecast, self.operational, self.response, self.policy)

    def adapter(self, *, on_inference=None):
        checkpoint = MockCheckpoint(usage="TEST_ONLY", contract_version="duocast_ds_h5_v1",
            model_id=self.forecast.forecast_model_id, checkpoint_version=self.forecast.checkpoint_version,
            dataset_id=self.identity.dataset_id, dataset_fingerprint=self.identity.dataset_fingerprint,
            feature_version=self.identity.feature_version,
            node_mapping_version=self.identity.node_mapping_version, required_hex_ids=self.identity.required_hex_ids,
            history_steps=12, demand_definition="confirmed_valid_bookings_per_5min",
            supply_definition="online_idle_dispatch_eligible_stock_at_target",
            parity_status="TEST_ONLY_MOCK_VERIFIED", evidence_refs=("fixture:declared-synthetic-label-semantics",),
            features_available_at=self.identity.cutoff_time)

        def infer(identity):
            if on_inference is not None:
                on_inference(identity)
            return [dict(cutoff_time=self.identity.cutoff_time, target_time=self.identity.target_time,
                         hex_id=r.hex_id, pred_demand=r.forecast_demand, pred_idle_supply=r.forecast_supply,
                         ds_proxy=r.forecast_demand / (r.forecast_supply + 1.0)) for r in self.forecast.rows]
        return DuoCastMockAdapter(infer, checkpoint=checkpoint, forecast_run_id=self.forecast.forecast_run_id,
                                  generated_at=self.forecast.generated_at)

    def run(self, **overrides):
        from surge_ml.inferences.service import run_decision
        arguments = dict(identity=self.identity, policy=self.policy, operational=self.operational,
                         response=self.response, forecast_provider=self.adapter(),
                         generated_at=self.forecast.generated_at)
        arguments.update(overrides)
        return run_decision(**arguments)

    def payload(self) -> dict:
        return {name: getattr(self, name).model_dump(mode="json")
                for name in ("identity", "policy", "operational", "response", "forecast")}


def make_fixture(*, hex_count: int = 2, beta: float = 0.0, gamma: float = 0.0) -> Fixture:
    if not 1 <= hex_count <= 50:
        raise ValueError("TEST_ONLY fixture supports 1..50 symbolic cells")
    cutoff = datetime(2026, 1, 10, 0, 0, tzinfo=timezone.utc)
    target, generated = cutoff + timedelta(minutes=5), cutoff + timedelta(seconds=1)
    nodes = tuple(f"test-hex-{i:02d}" for i in range(hex_count))
    identity = Identity(usage="TEST_ONLY", snapshot_id="test-snapshot-001", decision_id="test-decision-001",
        dataset_id=FIXTURE_VERSION, dataset_fingerprint="declared-synthetic-fingerprint-v1",
        node_mapping_version="test-node-order-v1", feature_version="test-feature-order-v1",
        reference_policy_version="test-effective-price-v1", semantic_profile_id=SEMANTIC_PROFILE,
        cutoff_time=cutoff, target_time=target, required_hex_ids=nodes, horizon_minutes=5)
    policy = PolicyConfig(usage="TEST_ONLY", schema_version="ggso.policy.test.v2", version="test-policy-v1",
        currency="TEST_UNITS", surge_min="1.0", surge_max="2.0", delta_max="0.3", br_min=0.1, br_max=0.9,
        lambda_temporal=5.0, lambda_spatial=2.0, epsilon=1e-6, quantile=0.05, quantile_method="linear_equal_weight",
        solver_time_limit_seconds=10.0, solver_mip_rel_gap=0.0, integrality_tolerance=1e-7,
        feasibility_tolerance=1e-7, money_tolerance=1e-6, monetary_scale=100.0)
    empty = Vector(names=(), values=(), schema_version="test-empty-context-v1")
    transform = Transform(version="standardize_train.v1", names=(), schema_version=empty.schema_version,
                          mean=(), scale=(), support_min=(), support_max=())
    operational_rows, forecast_rows, cells = [], [], []
    for i, hex_id in enumerate(nodes):
        capacity = CapacitySource(method="DIRECT", source_version="test-capacity-v1", available_at=cutoff,
            horizon_minutes=5, units="rides_per_horizon", direct_capacity=float(20 + 4 * i),
            rides_per_driver_hour=None, eta=None, eta_unit=None, calibration_version="test-capacity-calibration-v1")
        operational_rows.append(OperationalRow(hex_id=hex_id, current_surge="1.2", reference_fare=100.0,
            fare_definition_version="test-presurge-fare-v1", available_at=cutoff, price_state="SIMULATED_EFFECTIVE",
            price_source_version=identity.reference_policy_version, quote_opportunities=float(40 + 4 * i),
            quote_source_kind="FORECAST_AS_OF", quote_source_version="test-asof-quotes-v1",
            quote_cohort_profile="confirmed_bookings_over_compatible_quotes.h5.test.v1",
            quote_window_start=cutoff, quote_window_end=target, quote_available_at=cutoff,
            capacity=capacity, demand_context=empty, fulfillment_context=empty))
        forecast_rows.append(ForecastRow(hex_id=hex_id, forecast_demand=float(10 + 2 * i), forecast_supply=float(30 + 10 * i)))
        support = Support(train_rows=100, validation_rows=20, positive_trial_rows=100, unique_surge_values=9,
            surge_min="0.5", surge_max="2.5", train_start=cutoff - timedelta(days=9),
            train_end=cutoff - timedelta(days=7), validation_start=cutoff - timedelta(days=6),
            validation_end=cutoff - timedelta(days=5))
        calibration = Calibration(status="SYNTHETIC_PASS", rule_version="test-fixture-gate-v1",
            demand_mean_nll=2.0, fulfillment_mean_nll=1.0, fulfillment_calibration_error=0.01,
            evidence_refs=("fixture:synthetic-gate-values-not-measured-calibration",), rejection_reasons=())
        cells.append(ResponseCell(hex_id=hex_id, demand_intercept=2.0, demand_coefficients=(), beta=float(beta),
            nb_dispersion=10.0, fulfillment_intercept=0.0, fulfillment_coefficients=(), gamma=float(gamma),
            demand_transform=transform, fulfillment_transform=transform, fit_status="CONVERGED",
            support=support, calibration=calibration,
            scenarios=tuple(Scenario(scenario_id=f"test-scenario-{j}", beta=float(beta), gamma=float(gamma), weight=1 / 3)
                            for j in range(3))))
    operational = OperationalSnapshot(usage="TEST_ONLY", schema_version="ggso.operational.v2", identity=identity,
        currency=policy.currency, rows=tuple(operational_rows),
        pricing_edges=tuple(Edge(source=nodes[i], target=nodes[i + 1], weight=1.0) for i in range(hex_count - 1)),
        pricing_graph_version="test-undirected-pricing-graph-v1", pricing_graph_available_at=cutoff)
    response = ResponseArtifact(usage="TEST_ONLY", schema_version="ggso.response.v2", artifact_version="test-response-v1",
        semantic_profile_id=SEMANTIC_PROFILE, node_mapping_version=identity.node_mapping_version, required_hex_ids=nodes,
        dataset_id="test-response-cohorts-v1", data_fingerprint="declared-response-fixture-not-real-data",
        available_at=cutoff - timedelta(days=4), nb_parameterization="NB2_mean_size_variance_mu_plus_mu_squared_over_k",
        estimation_method="scipy_lbfgsb_mle.test.v1", context_representation="tabular_v1",
        training_objective_demand="negative_binomial_nll", training_objective_fulfillment="binomial_nll",
        epsilon=policy.epsilon, scenario_method="declared_synthetic_parameters.test.v1", scenario_seed=42,
        scenario_block_size=1, scenario_count=3, quantile_method="linear_equal_weight", quantile=0.05, cells=tuple(cells))
    forecast = Forecast(usage="TEST_ONLY", schema_version="ggso.forecast.v2", identity=identity,
        forecast_run_id="test-forecast-run-v1", forecast_model_id="duocast.mock", checkpoint_version="test-checkpoint-v1",
        checkpoint_contract="duocast_ds_h5_v1", history_steps=12,
        demand_definition="confirmed_valid_bookings_per_5min", supply_definition="online_idle_dispatch_eligible_stock_at_target",
        parity_status="TEST_ONLY_MOCK_VERIFIED", parity_evidence=("fixture:synthetic-parity-only",),
        features_available_at=cutoff, generated_at=generated, rows=tuple(forecast_rows))
    return Fixture(identity, policy, operational, response, forecast)


def fit_config(*, replicas: int = 4) -> FitConfig:
    return FitConfig(usage="TEST_ONLY", version="test-fit-config-v1", epsilon=1e-6, max_iterations=1000,
        log_dispersion_min=-5.0, log_dispersion_max=10.0, min_train_rows=30, min_validation_rows=10,
        min_positive_trial_rows=20, min_unique_surge=3, max_demand_mean_nll=20.0,
        max_fulfillment_mean_nll=20.0, max_fulfillment_calibration_error=0.15,
        bootstrap_replicates=replicas, bootstrap_block_size=12, seed=42)


def synthetic_observations(*, n: int = 900, seed: int = 123, hex_id: str = "test-hex-00") -> list[Observation]:
    """Known synthetic NB/Binomial coefficients; never a historical-data substitute."""
    if n < 60:
        raise ValueError("Synthetic recovery fixture requires at least 60 observations")
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    surge = rng.choice(np.arange(8, 21) / 10.0, size=n)
    context = rng.normal(size=n)
    capacity = rng.uniform(5.0, 40.0, size=n)
    mu = np.exp(3.0 + 0.25 * context - 1.2 * np.log(surge))
    demand = rng.negative_binomial(8.0, 8.0 / (8.0 + mu))
    logits = 0.2 - 0.1 * context + 0.55 * (np.log(capacity + 1e-6) - np.log(demand + 1e-6))
    completed = rng.binomial(demand, expit(logits))
    rows = []
    for i in range(n):
        decision = start + timedelta(minutes=5 * i)
        vector = Vector(names=("predecision_context",), values=(float(context[i]),), schema_version="test-context-v1")
        rows.append(Observation(usage="TEST_ONLY", hex_id=hex_id, decision_time=decision,
            target_time=decision + timedelta(minutes=5), feature_available_at=decision,
            outcome_matured_at=decision + timedelta(minutes=5), cohort_id=f"{hex_id}:synthetic-cohort-{i}",
            cohort_profile="confirmed_bookings_and_matured_completions.h5.test.v1",
            capacity_definition="rides_per_horizon.h5.test.v1", applied_surge=Decimal(str(surge[i])),
            booking_demand=int(demand[i]), completed_bookings=int(completed[i]), effective_capacity=float(capacity[i]),
            demand_context=vector, fulfillment_context=vector))
    return rows


def make_fitted_fixture(*, hex_count: int = 2) -> Fixture:
    """Complete synthetic fit -> scenarios -> forecast -> optimizer test input."""
    from surge_ml.train.responses.train import fit_artifact
    fixture = make_fixture(hex_count=hex_count)
    rows = []
    for i, hex_id in enumerate(fixture.identity.required_hex_ids):
        rows.extend(synthetic_observations(n=360, seed=123 + i, hex_id=hex_id))
    first_cell = [row for row in rows if row.hex_id == fixture.identity.required_hex_ids[0]]
    response = fit_artifact(rows, required_hex_ids=fixture.identity.required_hex_ids,
        split_time=first_cell[270].decision_time, fit_as_of=first_cell[-1].outcome_matured_at,
        dataset_id="test-generated-response-cohorts-v1", node_mapping_version=fixture.identity.node_mapping_version,
        artifact_version="test-fitted-response-v1", config=fit_config(replicas=3))
    vector = Vector(names=("predecision_context",), values=(0.0,), schema_version="test-context-v1")
    operational = OperationalSnapshot.model_validate({**fixture.operational.model_dump(),
        "rows": [{**row.model_dump(), "demand_context": vector, "fulfillment_context": vector}
                 for row in fixture.operational.rows]})
    return Fixture(fixture.identity, fixture.policy, operational, response, fixture.forecast)




def write_demo(folder: Path, *, steps: int = 160, nodes: int = 7, seed: int = 42) -> Path:
    """Small, deterministic no-geo fixture for every stage. Never overwrites data."""
    from surge_ml.train.duocast._constant import MAIN_VARIANTS
    if steps < 100 or nodes < 2:
        raise ValueError('Demo needs at least 100 snapshots and 2 nodes')
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    hexes = [f'test-hex-{i:02d}' for i in range(nodes)]
    times = pd.date_range('2026-01-05', periods=steps, freq='5min', tz='Asia/Ho_Chi_Minh')
    spatial = [{'source_hex': hexes[a], 'target_hex': hexes[b], 'available_at': times[0]}
               for i in range(nodes - 1) for a, b in ((i, i + 1), (i + 1, i))]
    market, mobility = [], []
    demand, supply = np.full(nodes, 12.0), np.full(nodes, 10.0)
    for k, ts in enumerate(times):
        demand = np.maximum(0, np.rint(.8*demand + .2*(12+4*np.sin(k/12)) + rng.normal(0,1,nodes)))
        supply = np.maximum(0, np.rint(.85*supply + .15*(11+2*np.cos(k/16)) + rng.normal(0,1,nodes)))
        for i, node in enumerate(hexes):
            market.append(dict(timestamp=ts, hex_id=node, demand_5m=int(demand[i]), idle_supply_t=int(supply[i]),
                backlog_t=max(0, demand[i]-supply[i]), eta_sec_t=120+10*max(0,demand[i]-supply[i]),
                base_surge=1.2, available_at=ts, event_time=ts))
        if k % 11:
            for i in range(nodes-1):
                a,b = (i,i+1) if k%2 else (i+1,i)
                mobility.append(dict(timestamp=ts, origin_hex=hexes[a], dest_hex=hexes[b],
                    flow_5m=int(rng.integers(1,4)), eta_min=2.0, available_at=ts))
    pd.DataFrame(market).to_csv(folder/'market.csv', index=False)
    pd.DataFrame(spatial).to_csv(folder/'spatial_edges.csv', index=False)
    pd.DataFrame(mobility).to_csv(folder/'od.csv', index=False)
    pd.DataFrame({'timestamp':times, 'available_at':times, 'complete':True}).to_csv(folder/'mobility_snapshots.csv', index=False)
    meta = dict(dataset_id=f'duocast_fixture_{steps}_{nodes}_{seed}', contract_version=CONTRACT_VERSION,
        synthetic=True, node_order=hexes, feature_definition_version='duocast_minimal_v1',
        node_mapping_version='test-node-order-v1', spatial_graph_version='synthetic-ring-v1',
        demand_definition=DEMAND_DEFINITION, supply_definition=SUPPLY_DEFINITION,
        mobility_semantics='physical_driver_transitions', static_as_of=str(times[0]),
        warning='Synthetic software verification only; not evidence of forecast accuracy or business uplift')
    (folder/'meta.json').write_text(json.dumps(meta,indent=2), encoding='utf-8')
    config = dict(contract_version=CONTRACT_VERSION, study_id='duocast-synthetic', seeds=[seed],
        variants=list(MAIN_VARIANTS), output_dir='runs',
        data=dict(market='market.csv', spatial='spatial_edges.csv', mobility='od.csv',
            mobility_snapshots='mobility_snapshots.csv', metadata='meta.json', validate_h3=False),
        model=dict(hidden=16,heads=2,head_hidden=8),
        train=dict(epochs=2,batch_size=8,eval_batch_size=16,num_threads=2,lgbm_rounds=10))
    path = folder/'config.yaml'
    path.write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf-8')
    return path
