"""Flow-STGATv2: local GRU + relation-aware temporal OD message passing.

This is an experimental model. It preserves the report's two independent
supervised forecasts y_L, y_G of the SAME future log(D/S) target, and the
persistence bypass b_t. No controller or pricing reward is backpropagated.

Adjacency edges are geographic proximity. Directed OD edges are *observed*
requests/trips, not hypothetical future driver relocation. Inbound messages
arrive at the physical destination; outbound-context messages return to the
origin through a reversed aggregation view of the SAME observed OD edge.
All edge history ends at the input cutoff. The edge attribute vector is
z-scored using train-only statistics; the observation mask is not z-scored.
"""
from __future__ import annotations

import torch
from torch import nn
from torch_geometric.utils import scatter

from surge_ml.config import ModelConfig
from surge_ml.features import EDGE_DIM, N_EDGE_FEATURES, NEIGHBOR3
from surge_ml.models.dual_gru_gatv2 import GatBlock


def _head(dim: int, hidden: int, dropout: float) -> nn.Module:
    return nn.Sequential(
        nn.Linear(dim, hidden), nn.ELU(), nn.Dropout(dropout), nn.Linear(hidden, 1)
    )


def _per_node(x: torch.Tensor) -> torch.Tensor:
    b, w, n, f = x.shape
    return x.permute(0, 2, 1, 3).reshape(b * n, w, f)


class DirectedODMessages(nn.Module):
    """Separate source->destination supply context and destination->source context.

    OD values and edge history influence message *content*, not just its
    attention coefficient. Sum is degree-normalized to control fan-in scaling.
    """

    def __init__(self, hidden: int, edge_hidden: int):
        super().__init__()
        value_in = hidden + edge_hidden
        gate_in = hidden * 2 + edge_hidden
        self.in_value = nn.Sequential(
            nn.Linear(value_in, hidden), nn.ELU(), nn.Linear(hidden, hidden))
        self.out_value = nn.Sequential(
            nn.Linear(value_in, hidden), nn.ELU(), nn.Linear(hidden, hidden))
        self.in_gate = nn.Linear(gate_in, 1)
        self.out_gate = nn.Linear(gate_in, 1)

    @staticmethod
    def _aggregate(values: torch.Tensor, targets: torch.Tensor, count: int) -> torch.Tensor:
        total = scatter(values, targets, dim=0, dim_size=count, reduce="sum")
        degree = scatter(values.new_ones((len(targets), 1)), targets,
                         dim=0, dim_size=count, reduce="sum")
        return total / degree.clamp(min=1).sqrt()

    def forward(self, h: torch.Tensor, edge_index: torch.Tensor,
                edge_repr: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        src, dst = edge_index
        forward_value = self.in_value(torch.cat((h[src], edge_repr), dim=-1))
        forward_gate = torch.sigmoid(self.in_gate(
            torch.cat((h[dst], h[src], edge_repr), dim=-1)))
        inbound = self._aggregate(forward_value * forward_gate, dst, h.shape[0])

        # Same physical src->dst OD edge, aggregated back at src: this is
        # outbound context, NOT another observed/reverse passenger trip.
        reverse_value = self.out_value(torch.cat((h[dst], edge_repr), dim=-1))
        reverse_gate = torch.sigmoid(self.out_gate(
            torch.cat((h[src], h[dst], edge_repr), dim=-1)))
        outbound = self._aggregate(reverse_value * reverse_gate, src, h.shape[0])
        return inbound, outbound


class FlowSTGATv2(nn.Module):
    """Shared local forecast plus graph branch with three learned relation channels.

    edge_relation: 0 geographic adjacency, 1 physical directed OD, 2 synthetic
    self-loop. Edge history [E,W,10] and observed mask [E,W] include only input
    snapshots <= cutoff (never future). Spatial channel includes self-loops;
    OD channels exclude synthetic self-loops. All variants use the same
    parameters, enabling capacity-matched relation ablations.
    """

    def __init__(self, n_local: int, cfg: ModelConfig):
        super().__init__()
        d, edge_hidden = cfg.gru_hidden, cfg.neighbor_hidden
        self.encoder = nn.GRU(n_local, d, batch_first=True)
        self.head_local = _head(d, cfg.head_hidden, cfg.dropout)
        self.neighbor = nn.GRU(len(NEIGHBOR3), edge_hidden, batch_first=True)
        self.fuse = nn.Sequential(nn.Linear(d + edge_hidden, d), nn.LayerNorm(d))
        self.spatial = nn.ModuleList(
            GatBlock(d, cfg.gat_heads, cfg.dropout) for _ in range(cfg.gat_layers)
        )
        # Last channel is explicit observation mask for missing temporal OD edges.
        self.edge_temporal = nn.GRU(N_EDGE_FEATURES + 1, edge_hidden, batch_first=True)
        self.od_messages = DirectedODMessages(d, edge_hidden)
        self.relation_gate = nn.Sequential(
            nn.Linear(d * 4, d), nn.ELU(), nn.Linear(d, 3), nn.Sigmoid()
        )
        self.relation_fuse = nn.Linear(d * 3, d)
        self.graph_norm = nn.LayerNorm(d)
        self.graph_drop = nn.Dropout(cfg.dropout)
        self.head_graph = _head(d, cfg.head_hidden, cfg.dropout)

    def forward(
        self, x_local: torch.Tensor, b: torch.Tensor,
        x_neighbor: torch.Tensor | None = None,
        edge_index: torch.Tensor | None = None,
        edge_attr: torch.Tensor | None = None,
        edge_history: torch.Tensor | None = None,
        edge_history_mask: torch.Tensor | None = None,
        edge_relation: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        if (x_neighbor is None or edge_index is None or edge_attr is None
                or edge_history is None or edge_history_mask is None
                or edge_relation is None):
            raise ValueError("Flow-STGATv2 requires temporal edges, relations and neighbor inputs")
        if edge_attr.shape[1] != EDGE_DIM or edge_history.shape[2] != N_EDGE_FEATURES:
            raise ValueError("Wrong edge contract: expect 11 internal/current and 10 historical features")
        if (edge_history.shape[:2] != edge_history_mask.shape or
                edge_history.shape[1] != x_local.shape[1] or
                edge_history.shape[0] != edge_index.shape[1] or
                edge_relation.shape[0] != edge_index.shape[1]):
            raise ValueError("Temporal edge history, relation IDs and input window must align")

        h = self.encoder(_per_node(x_local))[1][-1]
        local = b + self.head_local(h).reshape(b.shape)
        neighbors = self.neighbor(_per_node(x_neighbor))[1][-1]
        z = self.fuse(torch.cat((h, neighbors), dim=-1))

        # Only H3 adjacency and synthetic self-loops enter geographic attention.
        # Keeping self-loops in every variant makes the OD-only/self-only
        # baselines capacity-matched to the full architecture.
        spatial_edges = (edge_relation == 0) | (edge_relation == 2)
        spatial_z = z
        for block in self.spatial:
            spatial_z = block(spatial_z, edge_index[:, spatial_edges],
                              edge_attr[spatial_edges])
        spatial_delta = spatial_z - z

        od_edges = edge_relation == 1
        if bool(od_edges.any()):
            observed = edge_history_mask[od_edges].to(edge_history.dtype)
            history_input = torch.cat(
                (edge_history[od_edges], observed.unsqueeze(-1)), dim=-1
            )
            edge_state = self.edge_temporal(history_input)[1][-1]
            inbound, outbound = self.od_messages(
                z, edge_index[:, od_edges], edge_state
            )
        else:
            inbound = torch.zeros_like(z)
            outbound = torch.zeros_like(z)

        context = torch.cat((z, spatial_delta, inbound, outbound), dim=-1)
        gates = self.relation_gate(context)
        correction = self.relation_fuse(torch.cat((
            spatial_delta * gates[:, 0:1],
            inbound * gates[:, 1:2],
            outbound * gates[:, 2:3],
        ), dim=-1))
        graph_z = self.graph_norm(z + self.graph_drop(correction))
        graph = b + self.head_graph(graph_z).reshape(b.shape)
        return {"local": local, "graph": graph}
