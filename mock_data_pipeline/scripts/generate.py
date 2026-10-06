"""python -m scripts.generate --profile dev --out output_dev [--g 1.0 0.5 0.0] [--shuffled] [--set demand.scale=1.5 ...]"""
import argparse
import sys
import ast

from surge_mock.config import load_config
from surge_mock.pipeline import generate


def parse_overrides(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = ast.literal_eval(v)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--profile", default="full", choices=["full", "dev"])
    ap.add_argument("--out", default="output")
    ap.add_argument("--g", type=float, nargs="*", default=None, help="graph signal strengths (default: config)")
    ap.add_argument("--shuffled", action="store_true", help="also write the g1.0_shuffled control (needs g1.0)")
    ap.add_argument("--days", type=int, default=None, help="shortcut for --set n_days=N (smoke test)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--set", nargs="*", default=None, help="dotted overrides, e.g. demand.scale=1.5")
    a = ap.parse_args()
    ov = parse_overrides(a.set)
    if a.seed is not None:
        ov["seed"] = a.seed
    cfg = load_config(a.config, a.profile, ov)
    if a.days:
        cfg["n_days"] = a.days
        cfg["split"] = {"train": [1, max(1, a.days - 2)], "val": [max(1, a.days - 1), max(1, a.days - 1)],
                        "test": [a.days, a.days]}
    generate(cfg, a.out, strengths=a.g, shuffled=True if a.shuffled else None)


if __name__ == "__main__":
    main()
