"""Precomputed provider: reads `surge_proposal_v1` JSON written by `surge-ml` (pipeline/.../propose.py).

Normalisation only: field renames and quantising surge to policy precision (raw floats kept in evidence).
Action is taken from the file as-is; validation decides whether it is consistent with the rounded prices.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain.policies import fmt, quantize
from app.providers.base import OUTPUT_SCHEMA_VERSION, ProviderInfo, RecommendationBatch, SnapshotInput

SOURCE_SCHEMA = "surge_proposal_v1"
_EVIDENCE_KEYS = (
    "q_local",
    "q_graph",
    "pressure",
    "revision",
    "pressure_after_dead_zone",
    "revision_after_dead_zone",
    "pressure_component",
    "revision_component",
    "score",
    "delta_requested",
    "requested_capped",
    "global_capped",
    "valid",
)


class PrecomputedProviderError(ValueError):
    pass


def _dec(value, precision: int) -> str | None:
    if value is None:
        return None
    d = Decimal(repr(float(value)))
    if not d.is_finite():
        return "NaN"  # surfaced as *_NOT_FINITE by validation, never silently dropped
    return fmt(quantize(d, precision))


class PrecomputedProvider:
    def __init__(self, source_dir: Path, precision: int, timezone: str = "Asia/Ho_Chi_Minh"):
        self.source_dir = Path(source_dir)
        self.precision = precision
        self.tz = ZoneInfo(timezone)
        self._by_cutoff: dict[datetime, Path] = {}
        self.fingerprints: set[str | None] = set()
        self.info = ProviderInfo(id="precomputed_gnn", version="unknown", kind="PRECOMPUTED")
        for path in sorted(self.source_dir.glob("proposals_k*.json")):
            head = json.loads(path.read_text(encoding="utf-8"))
            if head.get("schema_version") != SOURCE_SCHEMA:
                continue
            self.fingerprints.add(head.get("data_fingerprint"))
            cutoff = datetime.fromisoformat(head["cutoff_ts_local"])
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=ZoneInfo(head.get("source_timezone", timezone)))
            self._by_cutoff[cutoff.astimezone(UTC)] = path
            self.info = ProviderInfo(
                id="precomputed_gnn",
                version=f"{head.get('study_id')}/{head.get('variant')}/seed_{head.get('seed')}",
                kind="PRECOMPUTED",
                description="Offline GNN forecasts + controller from surge-ml propose.",
            )

    def available_cutoffs(self) -> list[datetime]:
        return sorted(self._by_cutoff)

    def date_range(self, timezone: str) -> tuple[date, date]:
        """First and last local dates covered by the proposal files."""
        cutoffs = self.available_cutoffs()
        if not cutoffs:
            raise PrecomputedProviderError(f"no supported proposal files in {self.source_dir}")
        tz = ZoneInfo(timezone)
        return cutoffs[0].astimezone(tz).date(), cutoffs[-1].astimezone(tz).date()

    def check_fingerprint(self, dataset_fingerprint: str) -> None:
        """Refuse proposal files generated from a different dataset release than the one being imported."""
        stale = sorted(str(f) for f in self.fingerprints if f != dataset_fingerprint)
        if stale:
            raise PrecomputedProviderError(
                f"proposal files were generated from dataset fingerprint(s) {stale}, "
                f"active dataset is {dataset_fingerprint}"
            )

    def generate(self, snapshot: SnapshotInput) -> RecommendationBatch:
        path = self._by_cutoff.get(snapshot.cutoff_ts.astimezone(UTC))
        if path is None:
            raise PrecomputedProviderError(f"no precomputed proposals for cutoff {snapshot.cutoff_ts.isoformat()}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        recs = []
        for i, row in enumerate(doc.get("proposals", [])):
            status = row.get("status")
            evidence = {k: row.get(k) for k in _EVIDENCE_KEYS if k in row}
            evidence["raw_bidding"] = row.get("bidding")
            evidence["raw_final_surge"] = row.get("final_surge")
            evidence["raw_delta_applied"] = row.get("delta_applied")
            recs.append(
                {
                    "proposal_id": f"{path.stem}:{i}",
                    "hex_id": row.get("hex_id"),
                    "action": status,
                    "surge_base": _dec(row.get("bidding"), self.precision),
                    "surge_delta": None,
                    "surge_proposed": None if status == "REVIEW" else _dec(row.get("final_surge"), self.precision),
                    "explanation": f"GNN forecast + controller ({row.get('reason')}).",
                    "reason_codes": [row["reason"]] if row.get("reason") else [],
                    "evidence": evidence,
                }
            )
        return RecommendationBatch(
            schema_version=OUTPUT_SCHEMA_VERSION,
            snapshot_id=snapshot.snapshot_id,
            provider=self.info,
            policy_version=doc.get("policy_version", ""),
            generated_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
            recommendations=recs,
            dataset_fingerprint=doc.get("data_fingerprint"),
            model_metadata={
                k: doc.get(k)
                for k in (
                    "study_id",
                    "variant",
                    "seed",
                    "checkpoint",
                    "config_sha256",
                    "target_contract",
                    "reference_version",
                    "controller_calibrated",
                    "forecast_horizon_minutes",
                    "policy",
                )
            },
        )
