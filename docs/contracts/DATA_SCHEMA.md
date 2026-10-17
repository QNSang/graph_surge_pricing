# Data Schema — DuoCast and GGSO

Status: active synthetic/test contract. Official source ownership, lineage, and production eligibility remain pending.

## 1. Forecast inputs

| Dataset | Required identity | Core content |
|---|---|---|
| Market observations | dataset, feature, cell, and timestamp versions | Demand, supply, and cutoff-safe dynamic features per H3 cell and five-minute snapshot |
| Spatial edges | graph version and required-cell mapping | Neighboring H3-cell connections |
| Mobility edges | snapshot, source cell, and destination cell | Directed observed driver movements and configured edge attributes |
| Mobility snapshot manifest | expected snapshot range and coverage state | Distinguishes observed empty graphs from missing data |
| Metadata | dataset fingerprint, feature version, node mapping, timezone | Train–serve identity and chronological boundaries |

The active configuration is `pipeline/configs/duocast.yaml`. Concrete paths resolve through the configuration and selected dataset metadata; documentation must not hardcode a local release path.

## 2. Forecast targets

Demand is the integer count of confirmed valid booking requests created during the target five-minute interval. Supply is the integer stock of online, idle, dispatch-eligible drivers at the target timestamp.

Both labels are nonnegative. Demand is a flow and supply is a stock. Supply is not service capacity `K`.

## 3. Response data

Response fitting requires matured, cutoff-safe observations per cell and interval:

- demand cohort and completed or fulfilled outcome;
- effective price applied during the interval;
- pre-decision context features;
- capacity and opportunity fields required by the approved profile;
- source and maturity timestamps; and
- dataset and semantic identities.

Rows with incomplete maturity, ambiguous pricing, unknown cohort semantics, or post-decision leakage are rejected.

## 4. Decision snapshot

Each five-minute decision uses one complete network snapshot containing:

- required cell order;
- forecast inputs and graph snapshots;
- current effective prices and reference-policy version;
- operational `Q`, fare, capacity, and bounds;
- response-artifact identity; and
- all availability timestamps required to prove cutoff safety.

Missing required cells or identities makes the decision technically invalid. Missing observations are not converted into zeros.

## 5. Validation rules

- Timestamps are timezone-aware and aligned to five-minute cutoffs.
- Required cell IDs are unique and match the node mapping.
- Counts are nonnegative integers at observation time.
- Model inputs and operational context are available no later than the cutoff.
- Mobility endpoints belong to the required network.
- Empty observed snapshots and missing snapshots remain distinct.
- Dataset, feature, graph, checkpoint, and policy identities are versioned.

Validation failure returns no new recommendation, policy, or execution write.
