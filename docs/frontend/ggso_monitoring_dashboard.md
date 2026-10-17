# GGSO Monitoring Dashboard — Target Contract

Status: target UI design aligned with the current technical report. The existing `frontend_spec.md` and `network_console_implementation.md` describe the legacy/demo console and remain historical implementation evidence.

## Purpose

The GGSO dashboard provides operational visibility into each five-minute pricing cycle. It does not approve, edit or submit pricing actions.

After every cycle, the dashboard updates:

- the H3 network map;
- observed and forecast demand and effective available supply;
- current, recommended and applied surge multipliers;
- decision and independent-validation status;
- validation errors or execution rejection reasons;
- execution status and receipt identity;
- decision and execution history.

## Interaction boundary

Users may inspect cells, filter the network, compare current and recommended prices, view model/decision versions and browse history. The target interface has no Accept Selected, Accept All, per-cell Accept, manual override, approval or price-edit controls.

A VALID policy is applied automatically by the backend after full-network validation and execution checks. An INVALID cycle displays that no write was issued and current effective prices remain unchanged. The dashboard must not imply that a policy is APPLIED/EFFECTIVE until a confirmed execution receipt is available.

## Five-minute refresh

Each dashboard update is keyed by decision ID, cutoff, target time, reference-policy version, forecast version, response version, policy-config version and execution identity. The view must not combine forecasts, recommendations or receipts from different cycles.

The next cycle uses a fresh network snapshot and the latest confirmed effective policy. Pending execution state is displayed separately and is never presented as the new reference price.

## Required states

| State | Display behavior |
|---|---|
| Processing | Show the active cutoff and stage without reusing the prior cycle's status as current |
| VALID, execution pending | Show the complete validated policy and pending execution state |
| APPLIED | Show current/recommended/applied values and receipt identity |
| INVALID | Show reason and validation evidence; state explicitly that no write occurred |
| Execution rejected/unknown | Keep validation and execution states separate; do not label prices effective |

## Implementation boundary

This document does not activate the current frontend or pricing gateway. Migration requires a versioned GGSO consumer contract and targeted UI/API tests. Legacy DEMO/REPLAY controls may remain in their historical implementation until a separately authorized migration removes or isolates them from the GGSO target view.
