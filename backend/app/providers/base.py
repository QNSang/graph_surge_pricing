"""Recommendation Provider contract (spec §4). Providers never touch the DB; backend validates their output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

OUTPUT_SCHEMA_VERSION = "recommendation.v1"


@dataclass(frozen=True)
class HexInput:
    hex_id: str
    neighbors: tuple[str, ...]
    demand: float | None
    idle_supply: float | None
    effective_supply: float | None
    observed_ds: float | None
    surge_base: str | None  # decimal string


@dataclass(frozen=True)
class SnapshotInput:
    snapshot_id: str
    dataset_id: str
    dataset_fingerprint: str
    region_id: str
    cutoff_ts: datetime
    policy_version: str
    hexes: tuple[HexInput, ...]


@dataclass
class ProviderInfo:
    id: str
    version: str
    kind: str
    description: str = ""


@dataclass
class RecommendationBatch:
    """Normalised provider output, mirroring the JSON contract in spec §4.4 (surge values as decimal strings)."""

    schema_version: str
    snapshot_id: str
    provider: ProviderInfo
    policy_version: str
    generated_at: datetime
    recommendations: list[dict[str, Any]]
    dataset_fingerprint: str | None = None
    model_metadata: dict[str, Any] = field(default_factory=dict)


class RecommendationProvider(Protocol):
    info: ProviderInfo

    def generate(self, snapshot: SnapshotInput) -> RecommendationBatch: ...
