"""Placeholder for online GNN inference.

TD-04 is decided as precomputed for the MVP: `surge-ml surge --split test` writes proposal files offline and
`scripts/import_dataset.py --provider precomputed` loads them through PrecomputedProvider.
"""

from __future__ import annotations

from app.providers.base import ProviderInfo, RecommendationBatch, SnapshotInput


class GNNProvider:
    info = ProviderInfo(id="gnn_provider", version="0.0.0", kind="GNN", description="Not implemented (Phase 6).")

    def generate(self, snapshot: SnapshotInput) -> RecommendationBatch:
        raise NotImplementedError(
            "online GNN inference is out of MVP scope; run `surge-ml surge --split test` and import with "
            "--provider precomputed --source <dir>"
        )
