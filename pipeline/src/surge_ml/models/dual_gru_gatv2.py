"""SurgeNet (V1.2, `gru_gatv2_40`): GRU local dùng chung + head local dạng residual; tuỳ chọn thêm encoder hàng xóm,
Fuse, GATv2 và head graph. Cả hai head dự báo cùng target log((D+1)/(S_eff+1)) tại t+h: y_hat = b + g(.)."""

import torch
from torch import nn
from torch_geometric.nn import GATv2Conv

from surge_ml.config import ModelConfig
from surge_ml.features import COLUMNS, EDGE_DIM, NEIGHBOR3, Variant


def _head(d_in: int, hidden: int, dropout: float) -> nn.Module:
    return nn.Sequential(nn.Linear(d_in, hidden), nn.ELU(), nn.Dropout(dropout), nn.Linear(hidden, 1))


class GatBlock(nn.Module):
    """LayerNorm(h + Dropout(ELU(W_o GATv2(h)))); thuộc tính cạnh chỉ vào điểm attention."""

    def __init__(self, d: int, heads: int, dropout: float):
        super().__init__()
        if d % heads:
            raise ValueError(f"gru_hidden {d} must be divisible by gat_heads {heads}")
        self.conv = GATv2Conv(d, d // heads, heads=heads, concat=True, edge_dim=EDGE_DIM, add_self_loops=False)
        self.out = nn.Linear(d, d)
        self.drop = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(d)

    def forward(self, h, edge_index, edge_attr):
        return self.norm(h + self.drop(nn.functional.elu(self.out(self.conv(h, edge_index, edge_attr)))))


def per_node(x: torch.Tensor) -> torch.Tensor:
    """[B, W, N, F] -> [B*N, W, F]: mỗi hex là một chuỗi cho GRU dùng chung."""
    b, w, n, f = x.shape
    return x.permute(0, 2, 1, 3).reshape(b * n, w, f)


class SurgeNet(nn.Module):
    """Head local: y_L = b + g_L(GRU_L(Local37)). Head graph (nếu use_graph):
    y_G = b + g_G(GATv2^2(LayerNorm(W_F [GRU_L(Local37) || GRU_N(Neighbor3)]), G_t)).
    Head local không bao giờ thấy Neighbor3, GATv2 hay head graph."""

    def __init__(self, n_local: int, use_graph: bool, cfg: ModelConfig):
        super().__init__()
        d = cfg.gru_hidden
        self.use_graph = use_graph
        self.encoder = nn.GRU(n_local, d, batch_first=True)
        self.head_local = _head(d, cfg.head_hidden, cfg.dropout)
        if use_graph:
            self.neighbor = nn.GRU(len(NEIGHBOR3), cfg.neighbor_hidden, batch_first=True)
            self.fuse = nn.Sequential(nn.Linear(d + cfg.neighbor_hidden, d), nn.LayerNorm(d))
            self.blocks = nn.ModuleList(GatBlock(d, cfg.gat_heads, cfg.dropout) for _ in range(cfg.gat_layers))
            self.head_graph = _head(d, cfg.head_hidden, cfg.dropout)

    def forward(self, x_local, b, x_neighbor=None, edge_index=None, edge_attr=None) -> dict[str, torch.Tensor]:
        """x_local [B, W, N, F] (đã bỏ cột hàng xóm), b [B, N] -> {"local", "graph"?} mỗi cái [B, N]."""
        shape = b.shape
        h = self.encoder(per_node(x_local))[1][-1]  # [B*N, d]
        out = {"local": b + self.head_local(h).view(shape)}
        if self.use_graph:
            n = self.neighbor(per_node(x_neighbor))[1][-1]
            z = self.fuse(torch.cat([h, n], dim=-1))
            for block in self.blocks:
                z = block(z, edge_index, edge_attr)
            out["graph"] = b + self.head_graph(z).view(shape)
        return out


def build_model(variant: Variant, cfg: ModelConfig) -> nn.Module:
    return SurgeNet(len(COLUMNS[variant.columns]), variant.graph, cfg)


def forward_batch(model: nn.Module, batch: dict) -> dict[str, torch.Tensor]:
    return model(batch["x_local"], batch["b"], batch.get("x_neighbor"), batch.get("edge_index"),
                 batch.get("edge_attr"))
