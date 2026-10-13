from __future__ import annotations

from pathlib import Path

from app.core.config import Policy
from app.providers.base import RecommendationProvider
from app.providers.mock_provider import MockProvider
from app.providers.precomputed_provider import PrecomputedProvider


def build_provider(name: str, policy: Policy, source: Path | None = None) -> RecommendationProvider:
    if name == "mock":
        return MockProvider(policy.mock_controller, policy.limits.precision)
    if name == "precomputed":
        if source is None:
            raise ValueError("--source is required for the precomputed provider")
        return PrecomputedProvider(source, policy.limits.precision)
    if name == "gnn":
        from app.providers.gnn_adapter import GNNProvider

        return GNNProvider()
    raise ValueError(f"unknown provider '{name}'")
