# Model Evaluation — Forecast and Response

Status: evaluation protocol. Synthetic tests exist; official-data results are not yet available.

## 1. Forecast evaluation

Report demand and supply separately on decoded count targets:

- MAE and RMSE;
- WAPE when its denominator is valid;
- log-Huber selection loss;
- optional log demand/supply diagnostic metrics; and
- slices by time, demand level, supply level, and missing-data condition.

The active study catalog contains `lgbm_local`, `gru`, `gru_spatial`, `gru_mobility`, and `duocast`. Every comparison uses the same required cells, chronological windows, target semantics, availability rules, and frozen split definitions.

Undefined metric denominators produce null plus a reason; they do not receive a perfect score.

## 2. Split and selection

Preprocessing is fitted on training data only. Model and hyperparameter selection use validation loss. The selected configuration and artifact hashes are frozen before final test evaluation. Test results cannot change the selected variant.

Future movement, late-arriving events, target-period outcomes, and test statistics must not enter training or validation features.

## 3. Response evaluation

| Area | Required evidence |
|---|---|
| Demand model | Held-out Negative Binomial NLL, count deviance, MAE, and distribution checks |
| Fulfillment model | Held-out Binomial NLL/deviance, Brier score, and calibration |
| Parameters | Bounds, convergence, fraction at bounds, temporal stability, and cell support |
| Support | Training/validation counts and coverage across price and context ranges |
| Uncertainty | Bootstrap provenance, failed-fit counts, paired scenarios, and sensitivity |

Good predictive fit does not establish causal elasticity. Synthetic parameter recovery verifies estimator plumbing only.

## 4. Promotion boundary

Forecast and response artifacts are promoted independently. Each artifact records dataset, time, feature, semantic, model, and configuration identities. Full required-cell coverage is mandatory; invalid cells are not removed to improve reported eligibility.

Unit tests and synthetic demonstrations do not make an artifact production eligible.

## 5. Results table

Tables may be prepared before experiments, but numerical cells remain empty until backed by immutable artifacts. Report exact run paths, split definitions, seeds, aggregation rules, and confidence intervals with every result.

Forecast accuracy, modeled utility, and realized business impact are separate evaluations. Realized GMV requires the prospective switchback experiment.
