# Model I/O Contract — DuoCast

Active checkpoint contract: `duocast_ds_h5_v1`. Runtime forecasts use the versioned GGSO forecast envelope.

## 1. Model inputs

| Input | Logical shape | Contract |
|---|---|---|
| Dynamic history | `[B,T,N,F]` | Features for all required cells across `T` cutoff-safe snapshots |
| Spatial edges | `[2,E_sp]` | Directed representation of neighboring H3-cell connections |
| Mobility edges | `[2,E_od]` | Directed observed driver movements between cells |
| Mobility attributes | `[E_od,F_edge]` when configured | Cutoff-safe edge observations with versioned ordering |
| Node identity | ordered `N` cell IDs | Unique, complete, and identical to checkpoint order |
| Targets | `[B,N,2]` | Demand flow for the next interval and supply stock at the target timestamp |

Every input carries or resolves to dataset, feature, node-mapping, time, and checkpoint identities. Features unavailable at the cutoff are rejected.

## 2. Forecast outputs

Each required cell produces:

| Field | Type | Meaning |
|---|---|---|
| `hex_id` | string | H3 cell identifier |
| `cutoff_time` | aware datetime | Information boundary for the decision |
| `target_time` | aware datetime | Five minutes after the cutoff |
| `forecast_demand` | finite real ≥ 0 | Expected confirmed valid booking requests in `(cutoff,target]` |
| `forecast_supply` | finite real ≥ 0 | Expected eligible idle driver stock at `target_time` |

Forecast values remain real-valued. Rounding, candidate pricing, response estimation, capacity `K`, and GMV calculations occur downstream.

## 3. Forecast envelope

The network envelope contains:

- `schema_version` and semantic profile identifiers;
- model and checkpoint identity;
- dataset, feature, and node-mapping versions;
- cutoff, target, and generation timestamps;
- ordered required-cell IDs;
- history and horizon settings;
- demand and supply definitions;
- one row per required cell; and
- structured validity and reason codes.

Missing or invalid data is distinct from a valid zero forecast.

## 4. Train–serve parity

Inference must match the checkpoint's feature order, node order, preprocessing parameters, history length, model configuration, and target definitions. Unknown fields, silent remapping, future observations, and incompatible target transforms are rejected.

A provider binds to the exact checkpoint bytes used to create the model identity. Replacing a file on disk does not change an already constructed provider.

## 5. Runtime rules

- MI-01: Serialization round trips preserve types, precision, and timestamps.
- MI-02: Contract mismatches fail before candidate simulation.
- MI-03: Every required cell appears exactly once in stable order.
- MI-04: Forecast inference does not depend on future labels or pricing candidates.
- MI-05: One batched inference covers the complete required network.
- MI-06: Demand uses flow semantics and supply uses target-time stock semantics.
- MI-07: Operational fields are not model prediction heads.
- MI-08: A source, target, or identity mismatch returns technical invalid with no policy or execution request.

## 6. Minimal typed representation

```python
class DuoCastForecast:
    hex_id: str
    cutoff_time: datetime
    target_time: datetime
    forecast_demand: float
    forecast_supply: float
    model_version: str
    semantic_profile_version: str
```

The full network envelope additionally includes snapshot, run, checkpoint, dataset, feature, node-mapping, and reference-policy identities.

## 7. Evidence boundary

Executable schemas and synthetic tests verify the current transport and validation rules. Official data semantics, real checkpoint eligibility, calibration, and production authorization require separate evidence.
