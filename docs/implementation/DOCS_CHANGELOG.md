# Docs Changelog

## 2026-10-18 — DuoCast documentation consolidation

- Replaced the obsolete forecasting handoff with the current DuoCast architecture.
- Rewrote forecasting and model I/O contracts around `duocast_ds_h5_v1`.
- Updated context, architecture, codebase map, data schema, evaluation, implementation plan, tasks, and source register.
- Removed obsolete model names and stale pre-refactor paths from current documentation.
- Kept demand, supply, capacity, failure, automatic execution, monitoring, and business-evaluation semantics aligned with the technical report.

## 2026-10-18 — Automatic pricing and monitoring

- Exact independently validated full-network policy is applied automatically every five minutes.
- Validation failure produces no new write; current effective prices remain unchanged.
- Dashboard scope is monitoring-only, without manual pricing actions or operator approval.

## 2026-10-17 — Forecast architecture

- Defined DuoCast as Temporal GRU, Spatial GATv2, directed Mobility GATv2, gated fusion, and independent demand/supply heads.
- Fixed demand semantics to confirmed valid booking requests.
- Fixed supply semantics to online, idle, dispatch-eligible driver stock, distinct from capacity `K`.

## 2026-10-16 — GGSO contracts

- Added response, candidate, MILP, decision, validation, and evaluation documentation.
- Recorded that modeled utility is not realized business uplift.
