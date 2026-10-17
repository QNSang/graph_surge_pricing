# DuoCast — Temporal, Spatial, and Directed Mobility Forecasting

Status: implemented for synthetic and test-only workflows. Eligibility for official data and production checkpoints remains unverified.

## 1. Role

DuoCast forecasts demand and effective available supply for every required H3 cell at the next five-minute horizon. It runs once for the complete network snapshot at each decision cutoff. Pricing candidates, marketplace response, GMV estimation, and policy optimization belong to downstream GGSO components.

## 2. Inputs and outputs

Inputs:

- A dynamic history tensor covering `T` five-minute snapshots for every required cell.
- A spatial adjacency graph connecting neighboring H3 cells.
- A directed mobility graph representing observed driver movement between origin and destination cells.
- Versioned feature order, node order, timestamps, dataset identity, and checkpoint metadata.

Outputs for each cell `i`:

- `forecast_demand[i]`: expected confirmed valid booking requests during `(t, t+5]`.
- `forecast_supply[i]`: expected online, idle, dispatch-eligible driver stock at `t+5`.

Both outputs are finite, nonnegative real values. Capacity `K` is computed separately and is not a forecasting head.

## 3. Architecture

| Component | Responsibility |
|---|---|
| Temporal GRU | Encodes the recent demand and supply history of each H3 cell |
| Spatial GATv2 | Aggregates information from neighboring H3 cells |
| Mobility GATv2 | Aggregates directed origin–destination driver movements |
| Gated fusion | Combines local temporal, spatial, and mobility representations |
| Dual prediction heads | Predict demand and effective available supply independently |

The spatial and mobility branches use separate parameters because neighborhood proximity and directed driver movement represent different relationships.

Let $\mathcal V$ be the required H3-cell set, $N=|\mathcal V|$, and
$X_i=[x_{i,t-T+1},\ldots,x_{i,t}]$ be the cutoff-safe history for cell
$i\in\mathcal V$.

### 3.1. Temporal encoder

The shared GRU converts the history of each cell into a local representation:

$$
h_{i,k}=\operatorname{GRU}(x_{i,k},h_{i,k-1}),\qquad
\ell_i=\operatorname{LayerNorm}(h_{i,T}).
$$

The input is the ordered feature sequence $X_i$; the output $\ell_i$ is the
temporal state used by both graph branches.

### 3.2. Spatial and mobility encoders

For relation $r\in\{\mathrm{sp},\mathrm{od}\}$, let
$\mathcal N_r(i)$ be the observed incoming neighbors of cell $i$, and let
$q_{ji}^{(r)}$ be the available edge attributes. Each relation has separate
parameters:

$$
e_{ji}^{(r)}=
a_r^\top\operatorname{LeakyReLU}\!\left(
W_s^{(r)}\ell_j+W_t^{(r)}\ell_i+W_e^{(r)}q_{ji}^{(r)}
\right),
$$

$$
\alpha_{ji}^{(r)}=
\frac{\exp(e_{ji}^{(r)})}
{\sum_{k\in\mathcal N_r(i)}\exp(e_{ki}^{(r)})},\qquad
m_i^{(r)}=
\sum_{j\in\mathcal N_r(i)}\alpha_{ji}^{(r)}W_v^{(r)}\ell_j.
$$

Here $e_{ji}^{(r)}$ is an attention logit,
$\alpha_{ji}^{(r)}$ is its normalized coefficient, and $m_i^{(r)}$ is
the relation-specific message. The spatial branch receives H3 adjacency; the
mobility branch receives directed observed driver movements. Their outputs are
separate network-context representations for the same cell.

### 3.3. Gated fusion and prediction heads

The report reference combines the two graph messages before adding them to the
temporal state:

$$
c_i^{\mathrm{net}}=
W_c[m_i^{(\mathrm{sp})}\Vert m_i^{(\mathrm{od})}],\qquad
\omega_i=\sigma\!\left(
W_g[\ell_i\Vert m_i^{(\mathrm{sp})}\Vert m_i^{(\mathrm{od})}]
\right),
$$

$$
z_i=\operatorname{LayerNorm}\!\left(
\ell_i+\omega_i\odot c_i^{\mathrm{net}}
\right).
$$

Two independent heads predict demand and supply in log space:

$$
\widehat\ell_i^D=f_D(z_i),\qquad
\widehat\ell_i^S=f_S(z_i).
$$

The decoded forecasts are

$$
\widehat D_i=\max\{\exp(\widehat\ell_i^D)-1,0\},\qquad
\widehat S_i=\max\{\exp(\widehat\ell_i^S)-1,0\}.
$$

The active code implements the same component-level design but currently uses
separate gates for the spatial and mobility messages and sums the gated
messages. It is therefore not algebraically identical to the report's
$W_c$-based fusion equation. This parity gap is tracked in
[GD-09](../implementation/DECISION_LOG.md) and must be resolved before an
official checkpoint is approved.

## 4. Forward flow

1. The Temporal GRU produces one local representation for each cell from its historical observations.
2. Spatial GATv2 exchanges information across the H3 adjacency graph.
3. Mobility GATv2 exchanges information across the directed driver-movement graph.
4. Gated fusion controls how much each representation contributes to the final cell embedding.
5. Two independent heads decode next-interval demand and supply.

An empty observed mobility graph is valid when it accurately represents the snapshot. Missing mobility data is an input failure and must not be converted into an empty graph.

## 5. Training objective

Demand and supply targets are transformed into log space:

$$
\widetilde D_i=\log(1+D_i),\qquad
\widetilde S_i=\log(1+S_i).
$$

For log-space error $e$, the Huber penalty is

$$
\rho_\delta(e)=
\begin{cases}
\frac{1}{2}e^2, & |e|\le\delta,\\
\delta\left(|e|-\frac{1}{2}\delta\right), & |e|>\delta.
\end{cases}
$$

The core two-target loss is

$$
\mathcal L_{\mathrm{fc}}=
\frac{1}{2N}\sum_{i\in\mathcal V}
\left[
\rho_\delta(\widehat\ell_i^D-\widetilde D_i)
+\rho_\delta(\widehat\ell_i^S-\widetilde S_i)
\right].
$$

The factor $1/(2N)$ gives demand and supply equal weight and averages over
all required cells. Validation selection uses validation loss only; the test
split remains frozen until final evaluation.

Optional auxiliary losses require their own versioned definition and acceptance criteria. GMV is not part of the forecasting loss.

## 6. Inference contract

At a five-minute cutoff, inference consumes one frozen, complete network snapshot. Feature ordering, node ordering, history length, graph versions, preprocessing state, and checkpoint identity must match training. One batched forward pass produces forecasts for all required cells.

The forecast adapter rejects:

- incompatible checkpoint contracts;
- missing, duplicate, or reordered cells without an explicit mapping;
- features unavailable at the cutoff;
- invalid graph endpoints;
- nonfinite or negative outputs; and
- source or target semantics that do not match the declared contract.

On failure, GGSO receives a technical invalid result and does not create a new recommendation or execution request.

## 7. Evaluation

Forecast evaluation reports demand and supply metrics separately. Recommended primary metrics are MAE, RMSE, WAPE, and log-Huber loss, with operational slices by time and demand level. Model selection and final test reporting must use frozen, reproducible splits.

Predictive accuracy does not establish business uplift. Realized GMV impact requires the prospective business experiment defined in the technical report.

## 8. Current evidence boundary

The repository contains synthetic training, checkpoint, inference, and decision-path tests for DuoCast. These tests verify contracts and execution behavior but do not prove official-data accuracy, calibration, causal uplift, or production readiness.
