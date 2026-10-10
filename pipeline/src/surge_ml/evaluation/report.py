"""Báo cáo so sánh chỉ trên val: nhóm baseline/local/network, đại diện từng nhóm, so sánh cặp và quyết định triển khai."""

import json

import numpy as np

from surge_ml.config import Config
from surge_ml.errors import SurgeError
from surge_ml.evaluation.selection import load_results
from surge_ml.features import VARIANTS
from surge_ml.orchestration.runner import study_dir, trial_dir, write_json

METRICS = ("mae_q", "rmse_q", "bias_q", "pair_acc", "spearman")
GROUPS = ("baseline", "local", "network")
MIN_SEEDS = 3
BLOCK = 12  # 1 hour of 5-min cutoffs per bootstrap block
N_BOOT = 2000


def _mean_std(values: list) -> tuple[float | None, float | None]:
    values = [v for v in values if v is not None]
    return (float(np.mean(values)), float(np.std(values))) if values else (None, None)


def summarize(results: list[dict]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for r in results:
        variant = VARIANTS[r["variant"]]
        row = rows.setdefault(variant.name, {"group": variant.group, "kind": variant.kind, "family": variant.family,
                                             "primary_head": r["primary_head"], "per_seed": {}})
        row["per_seed"][r["seed"]] = {**{m: r["val"][r["primary_head"]].get(m) for m in METRICS},
                                      "n_params": r.get("n_params"), "n_trees": r.get("n_trees"),
                                      "train_seconds": r.get("train_seconds")}
    for row in rows.values():
        seeds = row["per_seed"].values()
        row["seeds"] = sorted(row["per_seed"])
        for m in (*METRICS, "train_seconds"):
            row[f"{m}_mean"], row[f"{m}_std"] = _mean_std([s[m] for s in seeds])
        row["n_params"] = next((s["n_params"] for s in seeds if s["n_params"] is not None), None)
        row["n_trees"], _ = _mean_std([s["n_trees"] for s in seeds])
    return rows


def best(rows: dict[str, dict], **match) -> str | None:
    names = [n for n, r in rows.items() if all(r[k] == v for k, v in match.items()) and r["mae_q_mean"] is not None]
    return min(names, key=lambda n: rows[n]["mae_q_mean"]) if names else None


def _load_errors(cfg: Config, name: str, seed: int) -> tuple[np.ndarray, np.ndarray] | None:
    path = trial_dir(cfg, name, seed) / "val_preds.npz"
    if not path.is_file():
        return None
    z = np.load(path)
    return z["ks"], z["abs_err_q"]


def paired_ci(cfg: Config, a: str, b: str, seeds: list[int], rng: np.random.Generator) -> list[float] | None:
    """Khoảng tin cậy 95% (bootstrap theo khối) của chênh lệch MAE_q(b) - MAE_q(a) trên các cutoff val."""
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for seed in seeds:
        ea, eb = _load_errors(cfg, a, seed), _load_errors(cfg, b, seed)
        if ea is None or eb is None:
            return None
        common, ia, ib = np.intersect1d(ea[0], eb[0], return_indices=True)
        diff = eb[1][ib] - ea[1][ia]  # [K, N], NaN where unscored in either
        for k, row in zip(common, diff):
            ok = np.isfinite(row)
            sums[k] = sums.get(k, 0.0) + float(row[ok].sum())
            counts[k] = counts.get(k, 0) + int(ok.sum())
    ks = sorted(k for k in sums if counts[k])
    if len(ks) < BLOCK:
        return None
    s = np.array([sums[k] for k in ks])
    c = np.array([counts[k] for k in ks], float)
    starts = rng.integers(0, len(ks) - BLOCK + 1, size=(N_BOOT, -(-len(ks) // BLOCK)))
    idx = (starts[..., None] + np.arange(BLOCK)).reshape(N_BOOT, -1)[:, :len(ks)]
    stats = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))]


def compare(cfg: Config, rows: dict[str, dict], question: str, a: str | None, b: str | None,
            rng: np.random.Generator) -> dict:
    """b là thách thức; chỉ thắng nếu tốt hơn trên mọi seed chung và khoảng tin cậy không chứa 0."""
    out = {"question": question, "reference": a, "challenger": b}
    if a is None or b is None:
        return {**out, "decision": "missing"}
    ra, rb = rows[a], rows[b]
    seeds = sorted(set(ra["seeds"]) & set(rb["seeds"]))
    wins = sum(rb["per_seed"][s]["mae_q"] < ra["per_seed"][s]["mae_q"] for s in seeds)
    delta = rb["mae_q_mean"] - ra["mae_q_mean"]
    ci = paired_ci(cfg, a, b, seeds, rng)
    if len(seeds) < MIN_SEEDS:
        decision = "not enough seeds"
    elif ci is None:
        decision = "no paired predictions"
    elif wins == len(seeds) and ci[1] < 0:
        decision = "challenger wins"
    else:
        decision = "keep reference"
    return {**out, "delta_mae_q": delta, "delta_pct": 100 * delta / ra["mae_q_mean"], "seeds": seeds,
            "wins": wins, "ci95": ci, "decision": decision}


def recommend(rows: dict[str, dict], comparisons: dict[str, dict]) -> dict:
    floor, net, gnn = comparisons["local_vs_baseline"], comparisons["network_vs_local"], comparisons["gnn_vs_handcrafted"]
    if net["decision"] == "challenger wins":
        pick, why = net["challenger"], "network beats the best local model on every seed and the CI excludes 0"
        if rows[pick]["kind"] == "gnn" and gnn["decision"] != "challenger wins" and gnn["reference"]:
            pick, why = gnn["reference"], "network helps, but the GNN is not clearly better than handcrafted neighbors"
    else:
        pick, why = net["reference"], f"network is not clearly better ({net['decision']}); keep the simpler local model"
    warning = None if floor["decision"] == "challenger wins" else f"best local vs baseline: {floor['decision']}"
    return {"model": pick, "reason": why, "warning": warning}


def _fmt(mean, std=None, digits=4) -> str:
    if mean is None:
        return "–"
    return f"{mean:.{digits}f}" if not std else f"{mean:.{digits}f} ± {std:.{digits}f}"


def to_markdown(report: dict) -> str:
    rows, reps = report["variants"], report["representatives"]
    lines = [f"# Eval report — {report['study_id']} (validation only)", "",
             "## A. All models by group", "",
             "| Group | Kind | Model | MAE_q ↓ | RMSE_q ↓ | Bias_q | Pair acc ↑ | Spearman ↑ | Params / trees | Train s | Seeds |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for group in GROUPS:
        for name in sorted((n for n, r in rows.items() if r["group"] == group), key=lambda n: rows[n]["mae_q_mean"]):
            r = rows[name]
            label = f"**{name}**" if reps.get(group) == name else name
            size = f"{r['n_params']:,}" if r["n_params"] is not None else (
                f"{r['n_trees']:.0f} trees" if r["n_trees"] is not None else "–")
            lines.append(f"| {group} | {r['kind'] or '–'} | {label} | {_fmt(r['mae_q_mean'], r['mae_q_std'])} | "
                         f"{_fmt(r['rmse_q_mean'], r['rmse_q_std'])} | {_fmt(r['bias_q_mean'])} | "
                         f"{_fmt(r['pair_acc_mean'])} | {_fmt(r['spearman_mean'])} | {size} | "
                         f"{_fmt(r['train_seconds_mean'], digits=0)} | {len(r['seeds'])} |")
    lines += ["", "Bold = group representative (lowest mean val MAE_q).", "",
              "## B. Representative comparisons (challenger − reference)", "",
              "| Question | Reference | Challenger | ΔMAE_q | Δ% | Seeds won | 95% CI | Decision |",
              "|---|---|---|---:|---:|---:|---|---|"]
    for c in report["comparisons"].values():
        if c["decision"] == "missing":
            lines.append(f"| {c['question']} | {c['reference'] or '–'} | {c['challenger'] or '–'} | – | – | – | – | missing |")
            continue
        ci = f"[{c['ci95'][0]:+.4f}, {c['ci95'][1]:+.4f}]" if c["ci95"] else "–"
        lines.append(f"| {c['question']} | {c['reference']} | {c['challenger']} | {c['delta_mae_q']:+.4f} | "
                     f"{c['delta_pct']:+.1f}% | {c['wins']}/{len(c['seeds'])} | {ci} | {c['decision']} |")
    rec = report["recommendation"]
    lines += ["", "## C. Decision", "", f"- Recommended model: **{rec['model']}**", f"- Reason: {rec['reason']}"]
    if rec["warning"]:
        lines.append(f"- Warning: {rec['warning']}")
    lines += ["", f"A challenger wins only if it is better on every shared seed (at least {MIN_SEEDS}) and the "
              f"paired block-bootstrap 95% CI of ΔMAE_q is below 0.", ""]
    return "\n".join(lines)


def report(cfg: Config) -> dict:
    results = load_results(cfg)
    if not results:
        raise SurgeError("NO_TRIALS", f"no trial_result.json under {study_dir(cfg)}")
    rows = summarize(results)
    reps = {g: best(rows, group=g) for g in GROUPS}
    reps.update({k: best(rows, group="network", kind=k) for k in ("handcrafted", "gnn")})
    rng = np.random.default_rng(0)
    comparisons = {
        "local_vs_baseline": compare(cfg, rows, "Does the local model learn anything?", reps["baseline"],
                                     reps["local"], rng),
        "network_vs_local": compare(cfg, rows, "Does network information help?", reps["local"], reps["network"], rng),
        "gnn_vs_handcrafted": compare(cfg, rows, "Is a GNN better than handcrafted neighbors?",
                                      reps["handcrafted"], reps["gnn"], rng),
    }
    out = {"study_id": cfg.study_id, "metric": "val/<primary>/mae_q", "variants": rows, "representatives": reps,
           "comparisons": comparisons, "recommendation": recommend(rows, comparisons)}
    root = study_dir(cfg)
    write_json(root / "eval_report.json", out)
    md = to_markdown(out)
    (root / "eval_report.md").write_text(md, encoding="utf-8")
    for c in comparisons.values():  # ASCII only: Windows consoles may not be UTF-8
        print(f"{c['question']:45s} {c['reference']} -> {c['challenger']}: {c['decision']}")
    print(f"recommended: {out['recommendation']['model']}")
    print(f"written: {root / 'eval_report.md'}")
    return out
