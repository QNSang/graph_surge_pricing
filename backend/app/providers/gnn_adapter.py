"""Phase 6 placeholder: online GNN inference adapter.

Until model serving is decided (TD-04), GNN output reaches the backend through PrecomputedProvider.
"""

from __future__ import annotations

from app.providers.base import ProviderInfo, RecommendationBatch, SnapshotInput


class GNNProvider:
    info = ProviderInfo(id="gnn_provider", version="0.0.0", kind="GNN", description="Not implemented (Phase 6).")

    def generate(self, snapshot: SnapshotInput) -> RecommendationBatch:
        raise NotImplementedError("GNN online inference is not wired yet; use PrecomputedProvider.")
