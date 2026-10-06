"""train.py - train / so sanh model du doan lambda.

    python train.py config.yaml
    python train.py config.yaml --overfit     # chan doan: overfit mot batch nho, khong tao run
"""
from __future__ import annotations

import argparse
import copy
import pickle
import random
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

import data as D
import evaluate as E
import model as M

HERE = Path(__file__).resolve().parent


class Tee:
    """In ra terminal va ghi y nguyen vao train.log."""

    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def __call__(self, *a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        self.f.write(s + "\n")
        self.f.flush()


def next_run_dir():
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    nums = [int(p.name) for p in runs.iterdir() if p.is_dir() and p.name.isdigit()]
    d = runs / f"{max(nums, default=0) + 1:02d}"
    d.mkdir()
    return d


def git_hash():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "no-git"
    except OSError:
        return "no-git"


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# ----------------------------------------------------------------------------- du doan
@torch.no_grad()
def predict_torch(model, split, bs, device):
    model.eval()
    out = []
    for batch in split.iterate(bs, device=device):
        out.append(model(batch).cpu().numpy())
    return np.concatenate(out)                                          # [S, N, H]


def to_frame(split, lam, name, horizons):
    """lam [S, N, H] -> DataFrame predictions (ts, hex, horizon, lambda, y, b, vol, split)."""
    ks = split.ks
    y, m, v, b = split.targets(ks)
    mask_in = np.stack([split.raw.present[k - split.window + 1:k + 1].all(0) for k in ks])
    m = m & mask_in[:, :, None]
    ts, hexes = split.raw.ts[ks], np.array(split.raw.hexes)
    S, N, H = lam.shape
    frames = []
    for hi, h in enumerate(horizons):
        ok = m[..., hi]
        si, ni = np.nonzero(ok)
        frames.append(pd.DataFrame({
            "ts": ts[si], "hex": hexes[ni], "horizon": np.int32(h), "lambda": lam[si, ni, hi].astype(np.float64),
            "y": y[si, ni, hi], "b": b[si, ni], "vol": v[si, ni, hi], "split": name}))
    return pd.concat(frames, ignore_index=True)


def val_metrics(df, cfg):
    return E.compute_metrics(df, cfg["eval"]["margin_m"], cfg["eval"]["min_volume"])


# ----------------------------------------------------------------------------- fit theo loai model
# Moi ham fit tra ve (lam_val, lam_test, history, best_ep); history la list dong cho history.csv.
def fit_lgbm(cfg, splits, run, log):
    hz, val, test = cfg["data"]["horizons"], splits["val"], splits["test"]
    mdl = M.LGBMModel(cfg)
    t0 = time.time()
    mdl.fit(splits["train"], val, log)
    lam_val, lam_test = mdl.predict(val, val.ks), mdl.predict(test, test.ks)
    m = val_metrics(to_frame(val, lam_val, "val", hz), cfg)
    with open(run / "checkpoint.pkl", "wb") as f:
        pickle.dump({"boosters": mdl.boosters, "cfg": cfg}, f)
    return lam_val, lam_test, [row(0, {}, m, hz, 0.0, time.time() - t0)], 0


def fit_formula(cfg, splits, f_node, f_edge, run, device):
    hz, tc, name = cfg["data"]["horizons"], cfg["train"], cfg["model"]["name"]
    val, test = splits["val"], splits["test"]
    mdl = M.build_torch(cfg, f_node, f_edge)
    lam_val = predict_torch(mdl, val, tc["eval_batch_size"], device)
    lam_test = predict_torch(mdl, test, tc["eval_batch_size"], device)
    torch.save({"model": name, "cfg": cfg}, run / "checkpoint.pt")
    return lam_val, lam_test, [row(0, {}, val_metrics(to_frame(val, lam_val, "val", hz), cfg), hz, 0.0, 0.0)], 0


def train_epoch(mdl, opt, train, cfg, rng, device, ep, log):
    """Mot epoch tren train. Tra ve (loss trung binh theo thanh phan, gnorm trung binh), None neu khong co buoc hop le."""
    tc = cfg["train"]
    mdl.train()
    acc, gn, nsteps = {"total": 0.0, "level": 0.0, "diff": 0.0, "rank": 0.0, "short": 0.0}, 0.0, 0
    for batch in train.iterate(tc["batch_size"], shuffle=True, rng=rng, device=device):
        loss, parts = M.compute_loss(mdl(batch), batch, cfg["loss"])
        if not torch.isfinite(loss):
            log(f"WARN: loss NaN/inf o epoch {ep}, bo qua buoc nay")
            continue
        opt.zero_grad()
        loss.backward()
        g = torch.nn.utils.clip_grad_norm_(mdl.parameters(), tc["grad_clip"])
        if not torch.isfinite(g):
            log(f"WARN: gradient NaN/inf o epoch {ep}, bo qua buoc nay")
            continue
        opt.step()
        acc["total"] += float(loss.detach())
        for k, v in parts.items():
            acc[k] += v
        gn += float(g)
        nsteps += 1
    if nsteps == 0:
        return None
    return {k: v / nsteps for k, v in acc.items()}, gn / nsteps


def epoch_warnings(m, fr, ref, ep, sel_h, tc, log):
    if m[sel_h]["lam_std"] < tc["warn_const_ratio"] * fr[fr["horizon"] == sel_h]["y"].std():
        log(f"WARN: lambda gan nhu hang so (std {m[sel_h]['lam_std']:.4f})")
    if ep == 1 and m[sel_h]["pairacc"] > ref[sel_h]["pairacc"] + tc["warn_leak_margin"]:
        log(f"WARN: PairAcc val epoch 1 = {m[sel_h]['pairacc']:.4f} cao hon persistence "
            f"{ref[sel_h]['pairacc']:.4f} qua {tc['warn_leak_margin']} -> nghi leakage truoc khi mung")


def fit_torch(cfg, splits, nz, f_node, f_edge, run, device, ref, log):
    hz, tc, name = cfg["data"]["horizons"], cfg["train"], cfg["model"]["name"]
    sel_h = int(tc["select_by"].rsplit("_", 1)[1])
    val, test = splits["val"], splits["test"]
    mdl = M.build_torch(cfg, f_node, f_edge).to(device)
    log(f"[model] {name} | tham so {sum(p.numel() for p in mdl.parameters()):,}")
    opt = torch.optim.AdamW(mdl.parameters(), lr=tc["lr"], weight_decay=tc["weight_decay"])
    rng = np.random.default_rng(cfg["seed"])
    log("ep | loss level diff rank short | val " + " ".join(f"PA@{h}" for h in hz) +
        " | spearman | corr(b,y) | gnorm | sec")
    history, best, bad_epochs = [], {"score": -np.inf, "ep": 0}, 0
    for ep in range(1, tc["epochs"] + 1):
        t0 = time.time()
        out = train_epoch(mdl, opt, splits["train"], cfg, rng, device, ep, log)
        if out is None:
            log("WARN: khong co buoc hop le nao, dung")
            break
        tr, gnorm = out
        fr = to_frame(val, predict_torch(mdl, val, tc["eval_batch_size"], device), "val", hz)
        m = val_metrics(fr, cfg)
        history.append(row(ep, tr, m, hz, gnorm, time.time() - t0))
        log(fmt(history[-1], hz))
        epoch_warnings(m, fr, ref, ep, sel_h, tc, log)
        if m[sel_h]["pairacc"] > best["score"]:
            best = {"score": m[sel_h]["pairacc"], "ep": ep, "state": copy.deepcopy(mdl.state_dict())}
            torch.save({"state": best["state"], "cfg": cfg, "norm": nz.__dict__, "ep": ep}, run / "checkpoint.pt")
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= tc["patience"]:
                log(f"WARN: PairAcc val@{sel_h} khong cai thien sau {tc['patience']} epoch, dung som "
                    f"(tot nhat ep {best['ep']}: {best['score']:.4f})")
                break
    mdl.load_state_dict(best["state"])
    return (predict_torch(mdl, val, tc["eval_batch_size"], device),
            predict_torch(mdl, test, tc["eval_batch_size"], device), history, best["ep"])


def save_and_report(cfg, splits, lam_val, lam_test, history, best_ep, run, log):
    """Ghi history/predictions, in bang val + test (test nhin mot lan, checkpoint tot nhat)."""
    hz, name = cfg["data"]["horizons"], cfg["model"]["name"]
    pd.DataFrame(history).to_csv(run / "history.csv", index=False)
    fv, ft = to_frame(splits["val"], lam_val, "val", hz), to_frame(splits["test"], lam_test, "test", hz)
    pd.concat([fv, ft], ignore_index=True).to_parquet(run / "predictions.parquet", index=False)
    rows = {f"val  {name}": val_metrics(fv, cfg), f"test {name}": val_metrics(ft, cfg)}
    log(f"\n== ket qua cuoi ({name}, checkpoint tot nhat" + (f" ep {best_ep}" if best_ep else "") + ") ==")
    log(E.table(rows, hz))
    log(f"\nluu o {run}")


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--overfit", action="store_true")
    args = ap.parse_args()

    cfg = D.load_config(args.config)
    hz, name = cfg["data"]["horizons"], cfg["model"]["name"]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    if args.overfit:
        log, run = print, None
    else:
        run = next_run_dir()
        shutil.copy(args.config, run / "config.yaml")
        log = Tee(run / "train.log")
    seed_all(cfg["seed"])

    log(f"run {run.name if run else '(overfit)'} | model {name} | note: {cfg['note']!r}")
    log(f"git {git_hash()} | data {(HERE / cfg['data']['path']).resolve()} | seed {cfg['seed']} | device {device}")
    splits, nz = D.build_splits(cfg, log)
    for n, s in splits.items():
        log(f"[data] {n:5s} mau {len(s):6d} | ts {s.raw.ts[0]} .. {s.raw.ts[-1]}")
    f_node, f_edge = splits["train"].grid.node.shape[-1], splits["train"].grid.eattr.shape[-1]

    if args.overfit:
        return overfit(cfg, splits, f_node, f_edge, device)

    val = splits["val"]
    ref = val_metrics(to_frame(val, np.repeat(val.targets(val.ks)[3][..., None], len(hz), -1), "val", hz), cfg)
    log("[ref ] persistence (logds_eff) val PairAcc: " + "  ".join(f"@{h} {ref[h]['pairacc']:.4f}" for h in hz)
        + f"  | corr(b,y): " + "  ".join(f"@{h} {ref[h]['corr_by']:.3f}" for h in hz))

    if name == "lgbm":
        out = fit_lgbm(cfg, splits, run, log)
    elif name in ("logds", "logds_eff"):
        out = fit_formula(cfg, splits, f_node, f_edge, run, device)
    else:
        out = fit_torch(cfg, splits, nz, f_node, f_edge, run, device, ref, log)
    save_and_report(cfg, splits, *out, run, log)


def row(ep, tr, m, hz, gnorm, sec):
    r = {"ep": ep, "loss": tr.get("total", np.nan), "level": tr.get("level", np.nan), "diff": tr.get("diff", np.nan),
         "rank": tr.get("rank", np.nan), "short": tr.get("short", np.nan)}
    for h in hz:
        r[f"pa_{h}"] = m[h]["pairacc"]
    r["spearman"] = float(np.mean([m[h]["spearman"] for h in hz]))
    r["corr_by"] = float(np.mean([m[h]["corr_by"] for h in hz]))
    r["mae"] = float(np.mean([m[h]["mae"] for h in hz]))
    r["gnorm"], r["sec"] = gnorm, sec
    return r


def fmt(r, hz):
    return (f"{r['ep']:2d} | {r['loss']:6.3f} {r['level']:5.3f} {r['diff']:5.3f} {r['rank']:5.3f} {r['short']:5.3f} | "
            + " ".join(f"{r[f'pa_{h}']:5.3f}" for h in hz)
            + f" | {r['spearman']:8.3f} | {r['corr_by']:9.3f} | {r['gnorm']:5.2f} | {r['sec']:5.1f}")


def overfit(cfg, splits, f_node, f_edge, device, steps=200):
    """Chan doan: loss tren mot batch nho phai ve gan 0 neu pipeline dung."""
    mdl = M.build_torch(cfg, f_node, f_edge).to(device)
    assert mdl.trainable, "overfit chi cho model torch co tham so"
    batch = splits["train"].batch(splits["train"].ks[:cfg["train"]["batch_size"]], device)
    opt = torch.optim.AdamW(mdl.parameters(), lr=cfg["train"]["lr"] * 10)
    mdl.train()
    for s in range(1, steps + 1):
        loss, parts = M.compute_loss(mdl(batch), batch, cfg["loss"])
        opt.zero_grad(); loss.backward(); opt.step()
        if s == 1 or s % 20 == 0:
            print(f"step {s:4d} loss {float(loss):.4f}  " + " ".join(f"{k} {v:.3f}" for k, v in parts.items()))


if __name__ == "__main__":
    main()
