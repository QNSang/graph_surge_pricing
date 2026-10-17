from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize
from scipy.special import digamma, expit, gammaln
from ._types import FitConfig
from surge_ml.errors import require

def counts(values, *, name: str) -> np.ndarray:
    raw = np.asarray(values)
    require(raw.dtype.kind in "iuf", "RESPONSE_INVALID", f"{name}: numeric counts required")
    result = np.asarray(values, dtype=float)
    require(result.ndim == 1 and result.size > 0 and np.isfinite(result).all()
            and (result >= 0).all() and np.equal(result, np.floor(result)).all(),
            "RESPONSE_INVALID", f"{name}: nonnegative integer count vector required")
    return result


def nb_nll(demand, log_mu, size: float) -> np.ndarray:
    d = counts(demand, name="D")
    eta = np.asarray(log_mu, dtype=float)
    require(eta.shape == d.shape and np.isfinite(eta).all() and np.isfinite(size) and size > 0,
            "RESPONSE_INVALID", "Invalid NB log mean/dispersion")
    log_k = np.log(size)
    log_sum = np.logaddexp(log_k, eta)
    value = -(gammaln(d + size) - gammaln(size) - gammaln(d + 1)
              + size * (log_k - log_sum) + d * (eta - log_sum))
    require(np.isfinite(value).all(), "RESPONSE_INVALID", "Nonfinite NB likelihood")
    return value


def binomial_nll(demand, completed, logits) -> np.ndarray:
    d, c = counts(demand, name="D"), counts(completed, name="C")
    eta = np.asarray(logits, dtype=float)
    require(d.shape == c.shape == eta.shape and (c <= d).all() and np.isfinite(eta).all(),
            "RESPONSE_INVALID", "Binomial requires 0 <= C <= D and finite logits")
    combinatorial = gammaln(d + 1) - gammaln(c + 1) - gammaln(d - c + 1)
    value = c * np.logaddexp(0.0, -eta) + (d - c) * np.logaddexp(0.0, eta) - combinatorial
    require(np.isfinite(value).all(), "RESPONSE_INVALID", "Nonfinite Binomial likelihood")
    return value


def _matrix(context, n: int) -> np.ndarray:
    x = np.asarray(context, dtype=float)
    require(x.ndim == 2 and x.shape[0] == n and np.isfinite(x).all(),
            "RESPONSE_INVALID", "Invalid tabular design matrix")
    return x


@dataclass(frozen=True)
class DemandFit:
    intercept: float
    coefficients: tuple[float, ...]
    beta: float
    dispersion: float
    iterations: int

    def log_mean(self, surge, context) -> np.ndarray:
        s = np.asarray(surge, dtype=float)
        x = _matrix(context, s.size)
        require(s.ndim == 1 and np.isfinite(s).all() and (s > 0).all()
                and x.shape[1] == len(self.coefficients), "RESPONSE_INVALID", "Invalid demand design")
        result = self.intercept + x @ np.asarray(self.coefficients) - self.beta * np.log(s)
        require(np.isfinite(result).all(), "RESPONSE_INVALID", "Nonfinite NB prediction")
        return result


def fit_demand(demand, surge, context, config: FitConfig) -> DemandFit:
    config = FitConfig.model_validate(config)
    d = counts(demand, name="D")
    s, x = np.asarray(surge, dtype=float), _matrix(context, d.size)
    require(s.shape == d.shape and np.isfinite(s).all() and (s > 0).all(),
            "RESPONSE_INVALID", "Invalid historical surge")
    require(np.unique(s).size >= config.min_unique_surge and d.sum() > 0,
            "RESPONSE_INVALID", "Insufficient surge variation/positive demand")
    design = np.column_stack((np.ones(d.size), x, -np.log(s)))
    mean, variance = float(d.mean()), float(d.var())
    size0 = mean * mean / max(variance - mean, mean)
    log_k0 = float(np.clip(np.log(size0), config.log_dispersion_min, config.log_dispersion_max))
    initial = np.r_[np.log(mean) + np.log(s).mean(), np.zeros(x.shape[1]), 1.0, log_k0]

    def objective(theta):
        eta, log_k = design @ theta[:-1], theta[-1]
        k = np.exp(log_k)
        loss = nb_nll(d, eta, k).mean()
        ratio = expit(eta - log_k)
        grad_eta = (d + k) * ratio - d
        log_sum = np.logaddexp(log_k, eta)
        grad_k = -k * (digamma(d + k) - digamma(k) + log_k + 1 - log_sum)
        grad_k += (d + k) * expit(log_k - eta)
        gradient = np.r_[design.T @ grad_eta / d.size, grad_k.mean()]
        return float(loss), gradient

    bounds = [(None, None)] * (x.shape[1] + 1) + [(0.0, 4.0),
              (config.log_dispersion_min, config.log_dispersion_max)]
    result = minimize(objective, initial, method="L-BFGS-B", jac=True, bounds=bounds,
                      options={"maxiter": config.max_iterations})
    require(bool(result.success) and np.isfinite(result.x).all() and np.isfinite(result.fun),
            "RESPONSE_FIT_FAILED", f"Demand optimizer did not converge: {result.message}")
    return DemandFit(float(result.x[0]), tuple(result.x[1:-2].tolist()), float(result.x[-2]),
                     float(np.exp(result.x[-1])), int(result.nit))


@dataclass(frozen=True)
class FulfillmentFit:
    intercept: float
    coefficients: tuple[float, ...]
    gamma: float
    iterations: int

    def logits(self, demand, capacity, context, epsilon: float) -> np.ndarray:
        d, k = np.asarray(demand, dtype=float), np.asarray(capacity, dtype=float)
        x = _matrix(context, d.size)
        require(d.ndim == 1 and d.shape == k.shape and np.isfinite(d).all() and np.isfinite(k).all()
                and (d >= 0).all() and (k >= 0).all() and np.isfinite(epsilon) and epsilon > 0
                and x.shape[1] == len(self.coefficients), "RESPONSE_INVALID", "Invalid fulfillment inputs")
        value = self.intercept + x @ np.asarray(self.coefficients)
        value += self.gamma * (np.log(k + epsilon) - np.log(d + epsilon))
        require(np.isfinite(value).all(), "RESPONSE_INVALID", "Nonfinite fulfillment logit")
        return value


def fit_fulfillment(demand, completed, capacity, context, config: FitConfig) -> FulfillmentFit:
    config = FitConfig.model_validate(config)
    d, c = counts(demand, name="D"), counts(completed, name="C")
    k, x = np.asarray(capacity, dtype=float), _matrix(context, d.size)
    require(d.shape == c.shape == k.shape and (c <= d).all() and np.isfinite(k).all() and (k >= 0).all(),
            "RESPONSE_INVALID", "Invalid Binomial cohort/capacity")
    require((d > 0).sum() >= config.min_positive_trial_rows and 0 < c.sum() < d.sum(),
            "RESPONSE_INVALID", "No positive trials or degenerate all-success/all-failure evidence")
    ratio = np.log(k + config.epsilon) - np.log(d + config.epsilon)
    design = np.column_stack((np.ones(d.size), x, ratio))
    initial_rate = c.sum() / d.sum()
    initial = np.r_[np.log(initial_rate / (1 - initial_rate)), np.zeros(x.shape[1]), 0.5]

    def objective(theta):
        eta = design @ theta
        loss = binomial_nll(d, c, eta).mean()
        gradient = design.T @ (d * expit(eta) - c) / d.size
        return float(loss), gradient

    result = minimize(objective, initial, method="L-BFGS-B", jac=True,
                      bounds=[(None, None)] * (x.shape[1] + 1) + [(0.0, 1.0)],
                      options={"maxiter": config.max_iterations})
    require(bool(result.success) and np.isfinite(result.x).all() and np.isfinite(result.fun),
            "RESPONSE_FIT_FAILED", f"Fulfillment optimizer did not converge: {result.message}")
    return FulfillmentFit(float(result.x[0]), tuple(result.x[1:-1].tolist()),
                          float(result.x[-1]), int(result.nit))
