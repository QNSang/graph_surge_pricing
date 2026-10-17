# Forecasting Contract — DuoCast

Status: active implementation contract for synthetic and test-only workflows. Official source, calibration, and checkpoint approval remain pending.

## 1. Purpose

DuoCast forecasts demand and effective available supply for every required H3 cell at the next five-minute horizon. It does not output surge multipliers, pricing actions, GMV, booking-rate effects, or causal estimates. One complete network inference is performed per decision cutoff.

## 2. Target semantics

Demand is the number of confirmed valid booking requests created during the target five-minute interval, before driver fulfillment. The forecast is a finite, nonnegative expected count measured in booking requests per five minutes.

Supply is the online, idle, dispatch-eligible driver stock at the target timestamp. The forecast is a finite, nonnegative expected driver count. This stock is distinct from effective service capacity `K`, which is supplied or calculated downstream.

## 3. Model structure

DuoCast consists of:

- a shared Temporal GRU;
- a Spatial GATv2 over H3 adjacency;
- a directed Mobility GATv2 over observed driver movement;
- gated fusion of the temporal, spatial, and mobility representations; and
- independent demand and supply prediction heads.

The history length `T` is configuration-controlled. The forecast horizon is five minutes.

## 4. Inputs and outputs

Detailed schemas are defined in [MODEL_IO_CONTRACT](../contracts/MODEL_IO_CONTRACT.md) and [DATA_SCHEMA](../contracts/DATA_SCHEMA.md).

The model consumes a dynamic history tensor, a spatial edge index, a directed mobility edge index, optional mobility edge attributes, node identity, and versioned preprocessing metadata. It outputs one demand forecast and one supply forecast per required cell.

## 5. Invariants

- FC-01: Required cells are complete, unique, and deterministically ordered.
- FC-02: Labels cover the next interval and all model inputs are available at the decision cutoff.
- FC-03: The mobility graph represents observed physical driver movement, not passenger-request OD.
- FC-04: An observed empty mobility graph is valid; missing mobility data is invalid.
- FC-05: Outputs are finite and nonnegative and remain real-valued for downstream calculations.
- FC-06: Feature order, node order, preprocessing state, and schema versions match the checkpoint.
- FC-07: Forecasting has exactly two targets and does not depend on response-model or solver artifacts.
- FC-08: A semantic or contract mismatch fails closed with no recommendation or execution request.
- FC-09: Inference runs once for the full network, never once per pricing candidate.

## 6. Training and evaluation boundary

For each required cell $i$, the target and decoding contract is

$$
\widetilde D_i=\log(1+D_i),\qquad
\widetilde S_i=\log(1+S_i),
$$

$$
\widehat D_i=\max\{\exp(\widehat\ell_i^D)-1,0\},\qquad
\widehat S_i=\max\{\exp(\widehat\ell_i^S)-1,0\}.
$$

With $N$ required cells, the core objective is

$$
\mathcal L_{\mathrm{fc}}=
\frac{1}{2N}\sum_{i=1}^{N}
\left[
\rho_\delta(\widehat\ell_i^D-\widetilde D_i)
+\rho_\delta(\widehat\ell_i^S-\widetilde S_i)
\right],
$$

where $\rho_\delta$ is the Huber penalty defined in the
[DuoCast model specification](duocast_model.md#5-training-objective). Any
auxiliary objective requires a separate definition and validation gate. Model
selection uses validation data only; final test metrics are reported after the
choice is frozen.

Forecast quality is evaluated independently for demand and supply. It does not establish pricing-policy improvement or realized business impact.

## 7. Failure handling

Reject incompatible checkpoints, unavailable features, invalid timestamps, incomplete network coverage, unknown graph nodes, duplicate keys, or nonfinite outputs. Do not replace invalid forecasts with zeros. A technical failure leaves the current effective prices unchanged because no new policy is produced.

## 8. Acceptance evidence

Acceptance requires contract tests, preprocessing parity, empty-mobility coverage, node-order rejection, checkpoint identity checks, and one batched network inference per cutoff. Synthetic test evidence does not substitute for official source validation, real-data calibration, or production authorization.
