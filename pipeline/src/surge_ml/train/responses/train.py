from __future__ import annotations
import hashlib
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from scipy.special import expit
from surge_ml._constant import SEMANTIC_PROFILE
from surge_ml.contracts.response import Calibration, ResponseArtifact, ResponseCell, Support
from surge_ml.datasets.responses import Observation, chronological_split
from surge_ml.errors import require
from ._types import FitConfig
from .bootstrap import paired_scenarios
from .glm import binomial_nll, fit_demand, fit_fulfillment, nb_nll

def fit_artifact(rows: list[Observation], *, required_hex_ids: tuple[str, ...],
                 split_time: datetime, fit_as_of: datetime, dataset_id: str,
                 node_mapping_version: str, artifact_version: str, config: FitConfig) -> ResponseArtifact:
    config = FitConfig.model_validate(config)
    rows = [Observation.model_validate(row) for row in rows]
    require(bool(required_hex_ids) and len(set(required_hex_ids)) == len(required_hex_ids)
            and {r.hex_id for r in rows} == set(required_hex_ids),
            "RESPONSE_INVALID", "Missing/extra required response cell")
    fingerprint_payload = {"rows": [r.model_dump(mode="json") for r in
                           sorted(rows, key=lambda r: (r.hex_id, r.decision_time))],
                           "config": config.model_dump(mode="json"), "split": split_time.isoformat(),
                           "fit_as_of": fit_as_of.isoformat()}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    cells = []
    for hex_id in required_hex_ids:
        train, validation, x, val, td, tf = chronological_split(
            [r for r in rows if r.hex_id == hex_id], split_time, fit_as_of)
        require(len(train) >= config.min_train_rows and len(validation) >= config.min_validation_rows,
                "RESPONSE_INVALID", f"Insufficient train/validation support for {hex_id}")
        require(np.unique(x.surge).size >= config.min_unique_surge and
                (x.demand > 0).sum() >= config.min_positive_trial_rows,
                "RESPONSE_INVALID", f"Insufficient price/positive-trial support for {hex_id}")
        d = fit_demand(x.demand, x.surge, x.demand_context, config)
        f = fit_fulfillment(x.demand, x.completed, x.capacity, x.fulfillment_context, config)
        eta = f.logits(val.demand, val.capacity, val.fulfillment_context, config.epsilon)
        demand_nll = float(nb_nll(val.demand, d.log_mean(val.surge, val.demand_context), d.dispersion).mean())
        fulfillment_nll = float(binomial_nll(val.demand, val.completed, eta).mean())
        positive = float(val.demand.sum())
        require(positive > 0, "RESPONSE_INVALID", "Validation contains no fulfillment trials")
        calibration_error = float(abs(np.sum(val.demand * expit(eta) - val.completed)) / positive)
        reasons = []
        if demand_nll > config.max_demand_mean_nll:
            reasons.append("HELD_OUT_NB_NLL")
        if fulfillment_nll > config.max_fulfillment_mean_nll:
            reasons.append("HELD_OUT_BINOMIAL_NLL")
        if calibration_error > config.max_fulfillment_calibration_error:
            reasons.append("HELD_OUT_CALIBRATION")
        scenarios = paired_scenarios(x, config, hex_id)
        support = Support(train_rows=len(train), validation_rows=len(validation),
                          positive_trial_rows=int((x.demand > 0).sum()), unique_surge_values=int(np.unique(x.surge).size),
                          surge_min=min(r.applied_surge for r in train), surge_max=max(r.applied_surge for r in train),
                          train_start=train[0].decision_time, train_end=train[-1].decision_time,
                          validation_start=validation[0].decision_time, validation_end=validation[-1].target_time)
        calibration = Calibration(status="INELIGIBLE" if reasons else "SYNTHETIC_PASS", rule_version=config.version,
                                  demand_mean_nll=demand_nll, fulfillment_mean_nll=fulfillment_nll,
                                  fulfillment_calibration_error=calibration_error,
                                  evidence_refs=(f"synthetic-fit:{fingerprint}:{hex_id}",), rejection_reasons=tuple(reasons))
        cells.append(ResponseCell(hex_id=hex_id, demand_intercept=d.intercept, demand_coefficients=d.coefficients,
                                  beta=d.beta, nb_dispersion=d.dispersion, fulfillment_intercept=f.intercept,
                                  fulfillment_coefficients=f.coefficients, gamma=f.gamma,
                                  demand_transform=td, fulfillment_transform=tf, fit_status="CONVERGED",
                                  support=support, calibration=calibration, scenarios=scenarios))
    return ResponseArtifact(usage="TEST_ONLY", schema_version="ggso.response.v2", artifact_version=artifact_version,
                            semantic_profile_id=SEMANTIC_PROFILE, node_mapping_version=node_mapping_version,
                            required_hex_ids=required_hex_ids, dataset_id=dataset_id, data_fingerprint=fingerprint,
                            available_at=fit_as_of, nb_parameterization="NB2_mean_size_variance_mu_plus_mu_squared_over_k",
                            estimation_method="scipy_lbfgsb_mle.test.v1", context_representation="tabular_v1",
                            training_objective_demand="negative_binomial_nll", training_objective_fulfillment="binomial_nll",
                            epsilon=config.epsilon, scenario_method="paired_moving_block_bootstrap.test.v1",
                            scenario_seed=config.seed, scenario_block_size=config.bootstrap_block_size,
                            scenario_count=config.bootstrap_replicates, quantile_method="linear_equal_weight",
                            quantile=0.05, cells=tuple(cells))


def save_artifact(artifact: ResponseArtifact, path: Path) -> None:
    artifact = ResponseArtifact.model_validate(artifact)
    # Exclusive creation protects prior fitted artifacts and experiment evidence.
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(artifact.model_dump_json(indent=2))
        handle.write("\n")


def load_artifact(path: Path) -> ResponseArtifact:
    return ResponseArtifact.model_validate_json(Path(path).read_text(encoding="utf-8"))



def fit_from_config(path: Path) -> dict:
    """Offline TEST_ONLY fit, with optional held-out diagnostics and no gate changes."""
    import yaml
    from surge_ml._utils.io import write_json, digest_file
    from surge_ml.reports.responses import build_response_report
    from ._types import ResponseFitJob
    path = Path(path).resolve()
    job = ResponseFitJob.model_validate(yaml.safe_load(path.read_text(encoding='utf-8')))
    input_path = (path.parent / job.input).resolve()
    output_path = (path.parent / job.output).resolve()
    report_path = None if job.report is None else (path.parent / job.report).resolve()
    destinations = [output_path] + ([] if report_path is None else [report_path])
    if len(set(destinations)) != len(destinations) or any(p in (path, input_path) for p in destinations):
        raise ValueError('Response artifact/report paths must be distinct and must not replace input or config')
    for destination in destinations:
        if destination.exists():
            raise FileExistsError(f'Refusing to overwrite {destination}')
    source_hash = digest_file(input_path)
    raw = json.loads(input_path.read_text(encoding='utf-8'))
    if not isinstance(raw, list):
        raise ValueError('Response input must be an array of versioned Observation objects')
    artifact = fit_artifact(raw, required_hex_ids=job.required_hex_ids,
        split_time=job.split_time, fit_as_of=job.fit_as_of, dataset_id=job.dataset_id,
        node_mapping_version=job.node_mapping_version, artifact_version=job.artifact_version, config=job.fit)
    diagnostics = None
    if report_path is not None:
        diagnostics = build_response_report(artifact, raw, split_time=job.split_time, fit_as_of=job.fit_as_of)
        diagnostics['input_sha256'] = source_hash
    if digest_file(input_path) != source_hash:
        raise ValueError('Response observations changed while fitting; refusing to publish artifacts')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_artifact(artifact, output_path)
    if diagnostics is not None:
        diagnostics['artifact_sha256'] = digest_file(output_path)
        write_json(report_path, diagnostics)
    return dict(path=str(output_path), report_path=None if report_path is None else str(report_path),
                cells=len(artifact.cells), production_eligible=False,
                eligible_cells=sum(c.calibration.status == 'SYNTHETIC_PASS' for c in artifact.cells))
