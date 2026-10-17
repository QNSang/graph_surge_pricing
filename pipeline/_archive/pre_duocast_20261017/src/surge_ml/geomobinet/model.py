"""GeoMobiNet-SMG: shared GRU, separate graphs, geography, and count heads."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F
from torch_geometric.nn import GATv2Conv

from .config import ModelConfig, NEURAL_VARIANTS, TrainConfig


class GeoMobiNet(nn.Module):
    """Return log1p demand/supply forecasts for a batch of independent graphs.

    Graph messages use the temporal embedding; static geography has its own
    encoder and enters gated residual fusion. There is no log-ratio bypass,
    second temporal encoder, pricing head, or implicit reverse OD edge.
    """

    def __init__(self, n_dynamic: int, n_geo: int, n_spatial: int, n_mobility: int,
                 cfg: ModelConfig, variant: str = "geomobinet_smg") -> None:
        super().__init__()
        if variant not in NEURAL_VARIANTS:
            raise ValueError(f"Not a neural variant: {variant}")
        spatial, mobility, geo, road = NEURAL_VARIANTS[variant]
        if road and n_spatial == 0:
            raise ValueError("geomobinet_smg_road requires configured spatial edge attributes")
        self.variant, self.road = variant, road
        hidden = cfg.hidden
        self.temporal = nn.GRU(n_dynamic, hidden, batch_first=True)
        self.geo_encoder = (nn.Sequential(nn.Linear(n_geo, cfg.geo_hidden), nn.ReLU(),
                                         nn.Linear(cfg.geo_hidden, hidden)) if geo else None)
        self.spatial_gat = (GATv2Conv(hidden, hidden // cfg.heads, heads=cfg.heads,
                                    edge_dim=n_spatial if road else None,
                                    add_self_loops=False, bias=False, dropout=cfg.dropout)
                            if spatial else None)
        self.mobility_gat = (GATv2Conv(hidden, hidden // cfg.heads, heads=cfg.heads,
                                     edge_dim=n_mobility, add_self_loops=False,
                                     bias=False, dropout=cfg.dropout) if mobility else None)
        branches = int(spatial) + int(mobility) + int(geo)
        self.gate = nn.Linear(hidden * (branches + 1), hidden * branches) if branches else None
        self.norm = nn.LayerNorm(hidden)
        self.dropout = nn.Dropout(cfg.dropout)
        self.demand_head = nn.Sequential(nn.Linear(hidden, cfg.head_hidden), nn.ReLU(),
                                         nn.Linear(cfg.head_hidden, 1), nn.Softplus())
        self.supply_head = nn.Sequential(nn.Linear(hidden, cfg.head_hidden), nn.ReLU(),
                                         nn.Linear(cfg.head_hidden, 1), nn.Softplus())

    @staticmethod
    def graph_message(layer, hidden, index, attributes=None):
        if index.shape[1] == 0:
            return torch.zeros_like(hidden)
        message = F.elu(layer(hidden, index, attributes))
        # No incoming physical edge means no message, including isolated nodes.
        has_incoming = torch.zeros(hidden.shape[0], dtype=torch.bool, device=hidden.device)
        has_incoming[index[1]] = True
        return torch.where(has_incoming[:, None], message, torch.zeros_like(message))

    def forward(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        hidden = self.temporal(batch["x_dyn"])[1][-1]
        messages = []
        if self.spatial_gat is not None:
            attributes = batch["spatial_attr"] if self.road else None
            messages.append(self.graph_message(self.spatial_gat, hidden, batch["spatial_index"], attributes))
        if self.mobility_gat is not None:
            messages.append(self.graph_message(self.mobility_gat, hidden, batch["mobility_index"],
                                               batch["mobility_attr"]))
        if self.geo_encoder is not None:
            messages.append(self.geo_encoder(batch["x_geo"]))
        if messages:
            gates = torch.sigmoid(self.gate(torch.cat([hidden, *messages], dim=-1)))
            weighted = [gate * value for gate, value in zip(gates.chunk(len(messages), dim=-1), messages)]
            hidden = hidden + self.dropout(torch.stack(weighted, dim=0).sum(dim=0))
        fused = self.dropout(self.norm(hidden))
        return torch.cat([self.demand_head(fused), self.supply_head(fused)], dim=-1)


def count_predictions(output_log: torch.Tensor) -> torch.Tensor:
    if not bool(torch.isfinite(output_log).all()) or bool((output_log < 0).any()):
        raise FloatingPointError("Model output must be finite, nonnegative log1p counts")
    output = torch.expm1(output_log)
    if not bool(torch.isfinite(output).all()):
        raise FloatingPointError("Count forecast overflow; reject rather than silently clip the prediction")
    return output


def loss_parts(output_log: torch.Tensor, target_counts: torch.Tensor, cfg: TrainConfig):
    if output_log.shape != target_counts.shape or output_log.shape[-1] != 2:
        raise ValueError("Loss expects matching [nodes,2] demand/supply tensors")
    if not bool(torch.isfinite(target_counts).all()) or bool((target_counts < 0).any()):
        raise ValueError("Demand/supply targets must be finite nonnegative counts")
    target = torch.log1p(target_counts)
    demand = F.huber_loss(output_log[:, 0], target[:, 0], delta=cfg.huber_delta)
    supply = F.huber_loss(output_log[:, 1], target[:, 1], delta=cfg.huber_delta)
    total = (demand + supply) / 2
    if not bool(torch.isfinite(total)):
        raise FloatingPointError("Nonfinite training loss")
    return total, demand, supply
