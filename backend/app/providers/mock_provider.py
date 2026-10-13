"""Mock provider: persistence forecast + Pressure/Revision controller.

The controller math mirrors pipeline/src/surge_ml/controller.py::apply_surge_controller, re-implemented
here because the backend must not import training code (spec §2.4). Forecasts are heuristics, not a model:
q_local = observed D/S at the cutoff, q_graph = mean observed D/S over the hex and its ring-1 neighbours.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

from app.domain.policies import fmt, quantize
from app.providers.base import OUTPUT_SCHEMA_VERSION, ProviderInfo, RecommendationBatch, SnapshotInput


def _dead_zone(value: float, threshold: float) -> float:
    return math.copysign(max(abs(value) - threshold, 0.0), value)


class MockProvider:
    info = ProviderInfo(
        id="mock_provider",
        version="0.1.0",
        kind="MOCK",
        description="Persistence/neighbour D/S heuristic + Pressure/Revision controller (demo only).",
    )

    def __init__(self, controller: dict, precision: int):
        self.cfg = {
            "reference_q": 1.2,
            "q_min": 1e-6,
            "pressure_dead_zone": 0.10,
            "revision_dead_zone": 0.05,
            "pressure_gain": 0.60,
            "revision_gain": 0.40,
            "max_requested_delta": 0.40,
            "surge_min": 1.0,
            "surge_max": 3.0,
            **controller,
        }
        self.precision = precision

    def _forecast(self, snapshot: SnapshotInput) -> dict[str, tuple[float | None, float | None]]:
        ds = {h.hex_id: h.observed_ds for h in snapshot.hexes}
        out: dict[str, tuple[float | None, float | None]] = {}
        for h in snapshot.hexes:
            local = h.observed_ds
            pool = [v for v in [local, *(ds.get(n) for n in h.neighbors)] if v is not None]
            graph = sum(pool) / len(pool) if pool and local is not None else None
            out[h.hex_id] = (local, graph)
        return out

    def _control(self, q_local: float | None, q_graph: float | None, bid: Decimal | None) -> dict:
        c = self.cfg
        valid_bid = bid is not None and Decimal(str(c["surge_min"])) <= bid <= Decimal(str(c["surge_max"]))
        if not valid_bid:
            return {"action": "REVIEW", "reason": "INVALID_BIDDING"}
        if q_local is None or q_graph is None or not (math.isfinite(q_local) and math.isfinite(q_graph)):
            return {"action": "REVIEW", "reason": "NONFINITE_FORECAST"}
        if q_local < c["q_min"]:
            return {"action": "REVIEW", "reason": "LOCAL_BELOW_Q_MIN"}
        if not q_graph > 0:
            return {"action": "REVIEW", "reason": "INVALID_GRAPH_FORECAST"}

        pressure = (q_graph - c["reference_q"]) / c["reference_q"]
        revision = math.expm1(math.log(q_graph) - math.log(q_local))
        p_comp = c["pressure_gain"] * _dead_zone(pressure, c["pressure_dead_zone"])
        r_comp = c["revision_gain"] * _dead_zone(revision, c["revision_dead_zone"])
        score = p_comp + r_comp
        cap = c["max_requested_delta"]
        requested = 0.0
        if pressure > c["pressure_dead_zone"]:
            requested = min(max(score, 0.0), cap)
        elif pressure < -c["pressure_dead_zone"]:
            requested = min(max(score, -cap), 0.0)
        active = abs(pressure) > c["pressure_dead_zone"]

        # Round to policy precision before choosing the action so action/price stay consistent.
        lo, hi = Decimal(str(c["surge_min"])), Decimal(str(c["surge_max"]))
        proposed = quantize(bid + Decimal(repr(requested)), self.precision)
        proposed = min(max(proposed, lo), hi)
        delta = proposed - bid
        if delta > 0:
            action = "INCREASE"
        elif delta < 0:
            action = "DECREASE"
        else:
            action = "HOLD"
        if not active:
            reason = "PRESSURE_DEAD_ZONE"
        elif requested == 0:
            reason = "DIRECTION_BLOCKED"
        elif abs(score) > cap and math.copysign(1, score) == math.copysign(1, pressure):
            reason = "REQUEST_CAP"
        else:
            reason = "PRESSURE_REVISION"
        if active and requested != 0 and quantize(bid + Decimal(repr(requested)), self.precision) != proposed:
            reason = "GLOBAL_CAP"
        return {
            "action": action,
            "reason": reason,
            "surge_delta": fmt(delta),
            "surge_proposed": fmt(proposed),
            "trace": {
                "q_local": q_local,
                "q_graph": q_graph,
                "pressure": pressure,
                "revision": revision,
                "pressure_component": p_comp,
                "revision_component": r_comp,
                "score": score,
                "delta_requested": requested,
            },
        }

    def generate(self, snapshot: SnapshotInput) -> RecommendationBatch:
        forecasts = self._forecast(snapshot)
        recs = []
        for h in snapshot.hexes:
            bid = None if h.surge_base is None else quantize(Decimal(h.surge_base), self.precision)
            q_local, q_graph = forecasts[h.hex_id]
            out = self._control(q_local, q_graph, bid)
            explanation = {
                "INCREASE": "Neighbourhood D/S pressure above reference; propose raising surge.",
                "DECREASE": "Neighbourhood D/S pressure below reference; propose lowering surge.",
                "HOLD": "Pressure within dead zone or direction blocked; keep base surge.",
                "REVIEW": "Inputs invalid for the controller; manual review required.",
            }[out["action"]]
            recs.append(
                {
                    "proposal_id": f"{snapshot.snapshot_id}:{h.hex_id}",
                    "hex_id": h.hex_id,
                    "action": out["action"],
                    "surge_base": fmt(bid),
                    "surge_delta": out.get("surge_delta"),
                    "surge_proposed": out.get("surge_proposed"),
                    "explanation": explanation,
                    "reason_codes": [out["reason"]],
                    "evidence": {
                        "demand": h.demand,
                        "idle_supply": h.idle_supply,
                        "effective_supply": h.effective_supply,
                        "observed_ds": h.observed_ds,
                        "forecast_method": "persistence_neighbor_mean.v0",
                        **({"controller": out["trace"]} if "trace" in out else {}),
                    },
                }
            )
        return RecommendationBatch(
            schema_version=OUTPUT_SCHEMA_VERSION,
            snapshot_id=snapshot.snapshot_id,
            provider=self.info,
            policy_version=snapshot.policy_version,
            generated_at=datetime.now(UTC),
            recommendations=recs,
            dataset_fingerprint=snapshot.dataset_fingerprint,
            model_metadata={"controller": self.cfg, "calibrated": False},
        )
