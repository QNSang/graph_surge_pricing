"""Hình PNG ghi lên MLflow: tổng quan dữ liệu (cache theo thư mục derived) và chẩn đoán từng trial."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from surge_ml.data.target import to_ratio  # noqa: E402
from surge_ml.features import IDX_DEMAND, IDX_EDGE_ADJ, IDX_EFFECTIVE, Splits, candidates  # noqa: E402

FIGURES_VERSION = "2"  # bump to regenerate cached data figures
SPLIT_COLORS ={"train": "tab:blue", "val": "tab:orange", "test": "tab:green"}


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _shade_splits(ax, times: pd.DatetimeIndex, splits: Splits) -> None:
    for split, (a, z) in splits.items():
        ax.axvspan(times[a], times[z - 1], color=SPLIT_COLORS[split], alpha=0.08, label=split)


def data_figures(derived: Path) -> Path:
    """Vẽ hình tổng quan dữ liệu vào <derived>/figures (một lần) và trả về thư mục đó."""
    out = derived / "figures"
    done = out / ".done"
    if done.exists() and done.read_text(encoding="utf-8") == FIGURES_VERSION:
        return out
    out.mkdir(exist_ok=True)
    manifest = json.loads((derived / "manifest.json").read_text(encoding="utf-8"))
    x = np.load(derived / "x.npy", mmap_mode="r")
    y, b = np.load(derived / "y.npy"), np.load(derived / "b.npy")
    T = x.shape[0]
    splits = {s: tuple(v["bounds"]) for s, v in manifest["splits"].items()}
    times = pd.date_range(manifest["first_ts"], periods=T, freq="5min")
    hours = times.hour.to_numpy()
    demand, supply = np.asarray(x[..., IDX_DEMAND]), np.asarray(x[..., IDX_EFFECTIVE])
    train = slice(*splits["train"])

    # 1. City-wide demand / effective supply / mean log-ratio over the whole dataset.
    fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    city = pd.DataFrame({"demand_5m": demand.sum(1), "effective_supply_t": supply.sum(1), "mean_log_q": b.mean(1)},
                        index=times).resample("1h").mean()
    axes[0].plot(city.index, city["demand_5m"], lw=0.8, label="demand_5m (sum over hexes)")
    axes[0].plot(city.index, city["effective_supply_t"], lw=0.8, label="effective_supply_t (sum)")
    axes[1].plot(city.index, city["mean_log_q"], lw=0.8, color="tab:red", label="mean log q")
    for ax in axes:
        _shade_splits(ax, times, splits)
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_title("City-wide demand and supply (hourly mean), split shading")
    _save(fig, out / "01_city_timeseries.png")

    # 2. Daily profile on train.
    fig, ax = plt.subplots(figsize=(9, 4))
    prof = pd.DataFrame({"hour": hours[train], "D": demand[train].mean(1), "S": supply[train].mean(1),
                         "log_q": b[train].mean(1)}).groupby("hour").mean()
    ax.plot(prof.index, prof["D"], marker="o", label="mean demand_5m per hex")
    ax.plot(prof.index, prof["S"], marker="o", label="mean effective_supply_t per hex")
    ax2 = ax.twinx()
    ax2.plot(prof.index, prof["log_q"], color="tab:red", ls="--", label="mean log q")
    ax.set_xlabel("hour of day")
    ax.set_title("Daily profile (train)")
    ax.legend(loc="upper left", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    _save(fig, out / "02_daily_profile.png")

    # 3. Target distribution per split.
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for split in splits:
        vals = y[candidates(split, splits)].ravel()
        vals = vals[np.isfinite(vals)]
        axes[0].hist(vals, bins=80, density=True, histtype="step", color=SPLIT_COLORS[split], label=split)
        axes[1].hist(np.clip(to_ratio(vals), 0, 6), bins=80, density=True, histtype="step",
                     color=SPLIT_COLORS[split], label=split)
    axes[0].set_title("target y = log((D+1)/(S_eff+1)) at H5")
    axes[1].set_title("q = exp(y), clipped at 6")
    for ax in axes:
        ax.legend()
    _save(fig, out / "03_target_distribution.png")

    # 4. Hex x hour heatmap of mean log q (train).
    fig, ax = plt.subplots(figsize=(10, 9))
    grid = pd.DataFrame(b[train]).groupby(hours[train]).mean().T.to_numpy()  # [N, 24]
    order = np.argsort(grid.mean(1))
    im = ax.imshow(grid[order], aspect="auto", cmap="RdBu_r", vmin=-np.abs(grid).max(), vmax=np.abs(grid).max())
    ax.set_yticks(range(len(order)), [f"{i:02d} {manifest['hex_ids'][i].rstrip('f')}" for i in order], fontsize=5)
    ax.set_ylabel("hex (contract index, H3 id)")
    ax.set_xlabel("hour of day")
    ax.set_title("Mean log q per hex and hour (train), hexes sorted by mean")
    fig.colorbar(im, ax=ax, label="log q (>0: demand exceeds supply)")
    _save(fig, out / "04_hex_hour_heatmap.png")

    # 5. Persistence: current vs next-step log-ratio on val.
    fig, ax = plt.subplots(figsize=(6, 6))
    ks = candidates("val", splits)
    hb = ax.hexbin(b[ks].ravel(), y[ks].ravel(), gridsize=60, bins="log", cmap="viridis")
    lim = [min(b[ks].min(), y[ks].min()), max(b[ks].max(), y[ks].max())]
    ax.plot(lim, lim, "r--", lw=1)
    ax.set_xlabel("b = log q at t (persistence)")
    ax.set_ylabel("y = log q at t+5")
    ax.set_title("Persistence on val")
    fig.colorbar(hb, ax=ax, label="log10 count")
    _save(fig, out / "05_persistence_val.png")

    # 6. Feature correlation on a train subsample.
    fig, ax = plt.subplots(figsize=(12, 10))
    rng = np.random.default_rng(0)
    rows = np.asarray(x[rng.choice(np.arange(*splits["train"]), 600, replace=False)]).reshape(-1, x.shape[2])
    std = rows.std(0)
    corr = np.corrcoef(rows[:, std > 0], rowvar=False)
    names = [n for n, s in zip(manifest["node_features"], std) if s > 0]
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(names)), names, rotation=90, fontsize=6)
    ax.set_yticks(range(len(names)), names, fontsize=6)
    ax.set_title("Node feature correlation (train subsample)")
    fig.colorbar(im, ax=ax)
    _save(fig, out / "06_feature_correlation.png")

    # 7. Graph size per snapshot by relation.
    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    ptr = np.load(derived / "edge_ptr.npy")
    is_adj = np.load(derived / "edge_attr.npy", mmap_mode="r")[:, IDX_EDGE_ADJ] == 1
    k_of_edge = np.repeat(np.arange(T), np.diff(ptr))
    adj = np.bincount(k_of_edge[is_adj], minlength=T)
    od = np.bincount(k_of_edge[~is_adj], minlength=T)
    edges = pd.DataFrame({"adjacency": adj, "od": od}, index=times)
    edges.resample("1h").mean().plot(ax=axes[0], lw=0.8)
    axes[0].set_title("Edges per snapshot (hourly mean)")
    edges.groupby(hours).mean().plot(ax=axes[1], marker="o")
    axes[1].set_xlabel("hour of day")
    axes[1].set_title("Edges per snapshot by hour")
    _save(fig, out / "07_edges_per_snapshot.png")

    done.write_text(FIGURES_VERSION, encoding="utf-8")
    return out


def trial_figures(history: list[dict], preds: dict[str, np.ndarray], y: np.ndarray, primary: str,
                  out: Path) -> Path:
    """Đường học và chẩn đoán dự đoán val của một trial."""
    out.mkdir(parents=True, exist_ok=True)
    if history:
        h = pd.DataFrame(history).set_index("epoch")
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        h[[c for c in h.columns if c.startswith("train/loss")]].plot(ax=axes[0], marker="o")
        axes[0].set_title("train loss")
        h[[c for c in h.columns if c.startswith("val/") and c.endswith("/mae_q")]].plot(ax=axes[1], marker="o")
        axes[1].set_title("val mae_q")
        _save(fig, out / "learning_curve.png")

    mask = np.isfinite(y)
    q, q_hat = to_ratio(y[mask]), to_ratio(preds[primary][mask])
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    hb = axes[0].hexbin(q, q_hat, gridsize=60, bins="log", cmap="viridis", xscale="log", yscale="log")
    lim = [min(q.min(), q_hat.min()), max(q.max(), q_hat.max())]
    axes[0].plot(lim, lim, "r--", lw=1)
    axes[0].set_xlabel("actual q")
    axes[0].set_ylabel(f"predicted q ({primary} head)")
    axes[0].set_title("val: predicted vs actual (best checkpoint)")
    fig.colorbar(hb, ax=axes[0], label="log10 count")
    for head, p in preds.items():
        axes[1].hist((p[mask] - y[mask]), bins=80, histtype="step", density=True, label=head)
    axes[1].set_title("val residual y_hat - y (log space)")
    axes[1].legend()
    _save(fig, out / "val_predictions.png")
    return out
