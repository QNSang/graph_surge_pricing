# Architecture — GGSO

## End-to-end flow

```text
Complete network snapshot
  → DuoCast forecast
  → Response evaluation
  → Candidate construction
  → Joint MILP optimization
  → Independent validation
  → Automatic full-policy execution
  → Monitoring dashboard
```

The cycle runs every five minutes. A failed forecast, response, optimization, validation, or execution precondition produces no new write and leaves current effective prices unchanged.

## DuoCast

DuoCast contains a shared Temporal GRU, Spatial GATv2 over H3 adjacency, directed Mobility GATv2 over observed driver movement, gated fusion, and independent demand and supply heads.

Demand is confirmed valid booking requests during the next five-minute interval. Supply is the online, idle, dispatch-eligible driver stock at the target timestamp. Supply stock is distinct from service capacity `K`.

## Response and candidates

The response layer combines the forecast with fitted Negative Binomial demand and Binomial fulfillment parameters. Candidate construction evaluates only eligible pricing actions and produces versioned per-cell outcomes for optimization.

Operational `Q`, fare, capacity, current pricing, support status, and response artifacts come from validated sources. They are not forecast outputs.

## Optimization and validation

The MILP selects one candidate per required cell as a coordinated network policy. Hard constraints and the objective are defined in [milp_optimization.md](../model/milp_optimization.md).

An independent validator recomputes network coverage, selected values, hard constraints, and objective components without trusting the solver matrices. Only a complete valid policy may proceed to execution.

## Dashboard boundary

The dashboard presents network status, forecast and policy summaries, validation results, execution state, and business monitoring. It does not contain Accept Selected, manual price editing, or operator approval controls.

## Evidence boundary

Synthetic and test-only paths demonstrate implementation behavior. Official-data validity, causal business impact, and production authorization remain separate gates.
