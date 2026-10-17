"""Held-out response diagnostics. Reports do not change artifact eligibility gates."""
from __future__ import annotations

from datetime import datetime
import math
from collections import defaultdict

import numpy as np
from scipy.special import expit

from surge_ml.contracts.response import ResponseArtifact
from surge_ml.datasets.responses import Observation, chronological_split, to_arrays
from surge_ml.train.responses.glm import (
    DemandFit, FulfillmentFit, binomial_nll, counts, nb_nll,
)


def fulfillment_diagnostics(demand, completed, probabilities, *, bins: int = 10) -> dict:
    """Booking-weighted calibration and Bernoulli Brier from aggregate cohorts.

    Bin edges are fixed reporting conventions, not operational acceptance thresholds.
    D=0 contributes no Bernoulli trials. Undefined rates are null, never perfect scores.
    """
    d, c = counts(demand, name="D"), counts(completed, name="C")
    p = np.asarray(probabilities, dtype=float)
    if (p.shape != d.shape or c.shape != d.shape or (c > d).any()
            or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any()
            or type(bins) is not int or not 1 <= bins <= 100):
        raise ValueError("Invalid cohort/probability vector or calibration bin count")
    total = float(d.sum())
    groups = []
    bin_index = np.minimum((p * bins).astype(int), bins - 1)
    for index in range(bins):
        mask = bin_index == index
        trials = float(d[mask].sum())
        predicted = float(np.sum(d[mask] * p[mask]))
        observed = float(c[mask].sum())
        groups.append({
            "lower": index / bins, "upper": (index + 1) / bins,
            "upper_inclusive": index == bins - 1, "cohorts": int(mask.sum()),
            "booking_trials": int(trials),
            "predicted_rate": predicted / trials if trials else None,
            "observed_rate": observed / trials if trials else None,
            "absolute_gap": abs(predicted - observed) / trials if trials else None,
        })
    global_error = abs(float(np.sum(d * p - c))) / total if total else None
    brier = float(np.sum(c * (1 - p) ** 2 + (d - c) * p ** 2) / total) if total else None
    ece = math.fsum(g["booking_trials"] * g["absolute_gap"] for g in groups if g["booking_trials"]) / total if total else None
    return {
        "booking_trials": int(total), "calibration_in_the_large": global_error,
        "booking_weighted_brier": brier, "booking_weighted_ece": ece,
        "probability_bins": groups,
    }


def build_response_report(artifact: ResponseArtifact, rows: list[Observation], *,
                          split_time: datetime, fit_as_of: datetime) -> dict:
    """Evaluate the frozen coefficients on the held-out cohorts, without refitting."""
    artifact = ResponseArtifact.model_validate(artifact)
    rows = [Observation.model_validate(row) for row in rows]
    if {row.hex_id for row in rows} != set(artifact.required_hex_ids):
        raise ValueError("Response diagnostic data must cover the exact artifact node set")
    cells = []
    for cell in artifact.cells:
        train, validation, _, _, td, tf = chronological_split(
            [row for row in rows if row.hex_id == cell.hex_id], split_time, fit_as_of)
        if (td != cell.demand_transform or tf != cell.fulfillment_transform
                or len(train) != cell.support.train_rows or len(validation) != cell.support.validation_rows
                or train[0].decision_time != cell.support.train_start
                or train[-1].decision_time != cell.support.train_end
                or validation[0].decision_time != cell.support.validation_start
                or validation[-1].target_time != cell.support.validation_end):
            raise ValueError("Diagnostic cohort/preprocessing window differs from the fitted artifact")
        data = to_arrays(validation, cell.demand_transform, cell.fulfillment_transform)
        demand_fit = DemandFit(cell.demand_intercept, cell.demand_coefficients, cell.beta, cell.nb_dispersion, 0)
        fulfillment_fit = FulfillmentFit(cell.fulfillment_intercept, cell.fulfillment_coefficients, cell.gamma, 0)
        log_mu = demand_fit.log_mean(data.surge, data.demand_context)
        with np.errstate(over="raise", invalid="raise"):
            expected_demand = np.exp(log_mu)
        logits = fulfillment_fit.logits(data.demand, data.capacity, data.fulfillment_context, artifact.epsilon)
        probability = expit(logits)
        pre_cap = data.demand * probability
        post_cap = np.minimum(pre_cap, data.capacity)
        metrics = fulfillment_diagnostics(data.demand, data.completed, probability)
        metrics.update({
            "demand_mae": float(np.abs(expected_demand - data.demand).mean()),
            "demand_mean_nll": float(nb_nll(data.demand, log_mu, cell.nb_dispersion).mean()),
            "fulfillment_mean_nll": float(binomial_nll(data.demand, data.completed, logits).mean()),
            "completed_mae_pre_capacity_cap": float(np.abs(pre_cap - data.completed).mean()),
            "completed_mae_post_capacity_cap": float(np.abs(post_cap - data.completed).mean()),
        })
        by_price = defaultdict(list)
        support_count = 0
        for index, row in enumerate(validation):
            by_price[format(row.applied_surge.normalize(), "f")].append(index)
            within_price = cell.support.surge_min <= row.applied_surge <= cell.support.surge_max
            within_context = all(
                all(lo <= value <= hi for value, lo, hi in zip(vector.values, transform.support_min, transform.support_max))
                for vector, transform in ((row.demand_context, cell.demand_transform),
                                          (row.fulfillment_context, cell.fulfillment_transform)))
            support_count += int(within_price and within_context)
        by_surge = []
        for surge, indices in sorted(by_price.items(), key=lambda item: float(item[0])):
            indices = np.asarray(indices, dtype=int)
            d, c, p = data.demand[indices], data.completed[indices], probability[indices]
            trials = float(d.sum())
            by_surge.append({
                "surge": surge, "cohorts": len(indices), "booking_trials": int(trials),
                "predicted_rate": float(np.sum(d * p) / trials) if trials else None,
                "observed_rate": float(c.sum() / trials) if trials else None,
                "demand_mae": float(np.abs(expected_demand[indices] - d).mean()),
            })
        cells.append({
            "hex_id": cell.hex_id, "calibration_status": cell.calibration.status,
            "rejection_reasons": list(cell.calibration.rejection_reasons),
            "validation_cohorts": len(validation), "within_training_support": support_count,
            "outside_training_support": len(validation) - support_count,
            "beta": cell.beta, "gamma": cell.gamma,
            "beta_at_bound": cell.beta in (0.0, 4.0), "gamma_at_bound": cell.gamma in (0.0, 1.0),
            "scenario_count": len(cell.scenarios),
            "beta_scenario_range": [min(s.beta for s in cell.scenarios), max(s.beta for s in cell.scenarios)],
            "gamma_scenario_range": [min(s.gamma for s in cell.scenarios), max(s.gamma for s in cell.scenarios)],
            "held_out": metrics, "by_surge": by_surge,
        })
    return {
        "schema_version": "ggso.response.diagnostics.v1", "usage": "TEST_ONLY",
        "artifact_version": artifact.artifact_version, "data_fingerprint": artifact.data_fingerprint,
        "split_time": split_time.isoformat(), "fit_as_of": fit_as_of.isoformat(),
        "production_eligible": False, "diagnostics_only": True,
        "eligibility_gate_changed": False, "temporal_parameter_stability_verified": False,
        "note": "Bin calibration can expose cancelling errors. This report does not establish causal elasticity or approve production thresholds.",
        "cells": cells,
    }
