"""model.py - 5 model cung dau ra lambda [B, N, H], va cac loss.

logds, logds_eff : cong thuc, khong train
lgbm             : du lieu phang, du doan phan du y - b
gru_only         : GRU -> head theo horizon,           lambda = b + g_h(z)
gru_gatv2        : GRU -> GATv2 x L (edge feature vao attention) -> head, lambda = b + g_h(z)
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn


# ----------------------------------------------------------------------------- cong thuc
class Formula(nn.Module):
    trainable = False

    def __init__(self, kind, n_h, eps):
        super().__init__()
        self.kind, self.n_h, self.eps = kind, n_h, eps

    def forward(self, batch):
        if self.kind == "logds":          # D / supply tho
            lam = torch.log((batch["d_t"] + self.eps) / (batch["s_t"] + self.eps))
        else:                             # logds_eff = persistence b (D / S_eff)
            lam = batch["b"]
        return lam[..., None].expand(-1, -1, self.n_h).contiguous()


# ----------------------------------------------------------------------------- torch
def _mlp(i, h, dropout):
    return nn.Sequential(nn.Linear(i, h), nn.ReLU(), nn.Dropout(dropout), nn.Linear(h, 1))


class GATv2Layer(nn.Module):
    """GATv2: e_ij = a^T LeakyReLU(Ws h_i + Wt h_j + We e_ij), softmax theo nut dich i (nhieu head)."""

    def __init__(self, dim, heads, edge_dim, dropout):
        super().__init__()
        assert dim % heads == 0
        self.h, self.c = heads, dim // heads
        self.ws, self.wt = nn.Linear(dim, dim), nn.Linear(dim, dim, bias=False)
        self.we = nn.Linear(edge_dim, dim, bias=False)
        self.att = nn.Parameter(torch.empty(heads, self.c))
        nn.init.xavier_uniform_(self.att)
        self.out, self.norm, self.drop = nn.Linear(dim, dim), nn.LayerNorm(dim), nn.Dropout(dropout)

    def forward(self, h, edge_index, edge_attr):
        src, dst = edge_index
        n, E = h.shape[0], src.shape[0]
        q = self.ws(h)[dst].view(E, self.h, self.c)
        v = self.wt(h)[src].view(E, self.h, self.c)
        e = Fn.leaky_relu(q + v + self.we(edge_attr).view(E, self.h, self.c), 0.2)
        score = (e * self.att).sum(-1)                                              # [E, heads]
        idx = dst[:, None].expand(-1, self.h)
        mx = torch.full((n, self.h), -1e30, device=h.device).scatter_reduce(0, idx, score, "amax", include_self=False)
        ex = (score - mx[dst]).exp()
        den = torch.zeros(n, self.h, device=h.device).index_add_(0, dst, ex)
        alpha = self.drop(ex / (den[dst] + 1e-16))
        agg = torch.zeros(n, self.h, self.c, device=h.device).index_add_(0, dst, alpha[..., None] * v).view(n, -1)
        return self.norm(h + self.drop(Fn.elu(self.out(agg))))


class GRUNet(nn.Module):
    trainable = True

    def __init__(self, f_node, f_edge, n_h, mcfg, graph):
        super().__init__()
        d, self.graph = mcfg["gru_hidden"], graph
        self.gru = nn.GRU(f_node, d, batch_first=True)
        if graph:
            self.edge_dim = f_edge + 2                   # + co chieu nguoc, + co self-loop
            self.layers = nn.ModuleList(GATv2Layer(d, mcfg["gat_heads"], self.edge_dim, mcfg["dropout"])
                                        for _ in range(mcfg["gat_layers"]))
        self.heads = nn.ModuleList(_mlp(d, mcfg["head_hidden"], mcfg["dropout"]) for _ in range(n_h))

    def _edges(self, batch, n):
        ei, ea = batch["edge_index"], batch["edge_attr"]
        z = ea.new_zeros(ea.shape[0], 1)
        fwd = torch.cat([ea, z, z], 1)
        rev = torch.cat([ea, z + 1, z], 1)
        loop_i = torch.arange(n, device=ea.device)
        loop = torch.cat([ea.new_zeros(n, ea.shape[1] + 1), ea.new_ones(n, 1)], 1)
        return torch.cat([ei, ei.flip(0), torch.stack([loop_i, loop_i])], 1), torch.cat([fwd, rev, loop], 0)

    def forward(self, batch):
        x = batch["x"]                                        # [B, W, N, F]
        B, W, N, Fd = x.shape
        _, h = self.gru(x.permute(0, 2, 1, 3).reshape(B * N, W, Fd))
        z = h[-1]                                             # [B*N, d]
        if self.graph:
            ei, ea = self._edges(batch, B * N)
            for layer in self.layers:
                z = layer(z, ei, ea)
        g = torch.cat([hd(z) for hd in self.heads], dim=-1).view(B, N, -1)
        return batch["b"][..., None] + g                      # chi hoc phan thay doi so voi persistence


def build_torch(cfg, f_node, f_edge):
    name, n_h = cfg["model"]["name"], len(cfg["data"]["horizons"])
    if name in ("logds", "logds_eff"):
        return Formula(name, n_h, cfg["data"]["eps"])
    return GRUNet(f_node, f_edge, n_h, cfg["model"], graph=(name == "gru_gatv2"))


# ----------------------------------------------------------------------------- loss
def huber(x, delta):
    a = x.abs()
    return torch.where(a <= delta, 0.5 * x * x, delta * (a - 0.5 * delta))


def compute_loss(lam, batch, lcfg):
    """Tong loss co trong so tu config; trong so 0 nghia la tat. Tra ve (total, {ten: float}).

    Cong thuc la de xuat tam (spec tro toi Phu luc A chua co) - moi loss nam gon trong mot khoi:
      level : Huber(delta) co trong so volume; du doan thap hon y (bo sot khan hiem) nhan (1 + rho)
      diff  : Huber tren (lam_i - lam_j) so voi (y_i - y_j) doc canh OD cua snapshot t
      rank  : RankNet softplus(-sign(dy) * dlam / T) tren cac cap hex cung mau, bo cap |dy| <= margin
      short : nhat quan giua horizon ke nhau: Huber(tau_s) tren (lam_{h+1} - lam_h) so voi (y_{h+1} - y_h)
    """
    y, m = batch["y"], batch["mask_y"].float()
    w = torch.log1p(batch["vol"]) * m                                    # [B, N, H]
    B, N, H = y.shape
    zero = lam.new_zeros(())
    parts = {}

    lv = lcfg["level"]
    err = lam - y
    asym = torch.where(err < 0, 1.0 + lv["rho"], 1.0)
    parts["level"] = (huber(err, lv["huber_delta"]) * asym * w).sum() / w.sum().clamp_min(1e-8)

    if lcfg["diff"]["weight"] > 0:
        lf, yf, wf, mf = lam.reshape(B * N, H), y.reshape(B * N, H), w.reshape(B * N, H), m.reshape(B * N, H)
        o, d = batch["edge_index"]
        ew = (wf[o] * wf[d]).sqrt() * mf[o] * mf[d]
        parts["diff"] = (huber((lf[o] - lf[d]) - (yf[o] - yf[d]), lv["huber_delta"]) * ew).sum() / ew.sum().clamp_min(1e-8)
    else:
        parts["diff"] = zero

    rk = lcfg["rank"]
    if rk["weight"] > 0:
        dl = lam[:, :, None, :] - lam[:, None, :, :]
        dy = y[:, :, None, :] - y[:, None, :, :]
        pw = w[:, :, None, :] * w[:, None, :, :] * (dy.abs() > rk["margin"])
        loss = Fn.softplus(-torch.sign(dy) * dl / rk["temperature"])
        parts["rank"] = (loss * pw).sum() / pw.sum().clamp_min(1e-8)
    else:
        parts["rank"] = zero

    sh = lcfg["short"]
    if sh["weight"] > 0 and H > 1:
        sw = (w[..., 1:] * w[..., :-1]).sqrt()
        parts["short"] = (huber((lam[..., 1:] - lam[..., :-1]) - (y[..., 1:] - y[..., :-1]), sh["tau_s"]) * sw).sum() \
            / sw.sum().clamp_min(1e-8)
    else:
        parts["short"] = zero

    total = sum(lcfg[k]["weight"] * parts[k] for k in parts)
    return total, {k: float(v.detach()) for k, v in parts.items()}


# ----------------------------------------------------------------------------- lgbm
class LGBMModel:
    """Mot booster moi horizon, du doan y - b tren du lieu phang. Trong so = log1p(vol)."""
    trainable = False

    def __init__(self, cfg):
        self.cfg = cfg
        self.boosters = []

    def fit(self, train, val, log=print):
        import lightgbm as lgb
        p = self.cfg["model"]["lgbm"]
        Xt, yt, mt, vt, bt = train.flat(train.ks)
        Xv, yv, mv, vv, bv = val.flat(val.ks)
        F = Xt.shape[-1]
        self.boosters, self.best_iters = [], []
        for hi, h in enumerate(self.cfg["data"]["horizons"]):
            kt, kv = mt[..., hi].ravel(), mv[..., hi].ravel()
            rt = (yt[..., hi] - bt).ravel()[kt]
            rv = (yv[..., hi] - bv).ravel()[kv]
            est = lgb.LGBMRegressor(
                objective="huber", alpha=self.cfg["loss"]["level"]["huber_delta"],
                n_estimators=p["n_estimators"], learning_rate=p["learning_rate"], num_leaves=p["num_leaves"],
                min_child_samples=p["min_child_samples"], subsample=p["subsample"], subsample_freq=1,
                colsample_bytree=p["colsample_bytree"], random_state=self.cfg["seed"], verbose=-1, n_jobs=-1)
            est.fit(Xt.reshape(-1, F)[kt], rt, sample_weight=np.log1p(vt[..., hi]).ravel()[kt],
                    eval_set=[(Xv.reshape(-1, F)[kv], rv)], eval_sample_weight=[np.log1p(vv[..., hi]).ravel()[kv]],
                    callbacks=[lgb.early_stopping(p["early_stopping_rounds"], verbose=False)])
            self.boosters.append(est)
            self.best_iters.append(est.best_iteration_)
            log(f"[lgbm] h={h:>2}  rows {kt.sum():,}  best_iter {est.best_iteration_}")

    def predict(self, split, ks):
        X, _, _, _, b = split.flat(ks)
        S, N, F = X.shape
        res = np.stack([est.predict(X.reshape(-1, F)).reshape(S, N) for est in self.boosters], axis=-1)
        return b[..., None] + res                                       # [S, N, H]
