"""Dòng lệnh surge-ml."""

import argparse
import json
import sys
from pathlib import Path

from surge_ml.config import apply_overrides, load_config
from surge_ml.errors import SurgeError

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "train.yaml"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="surge-ml")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("prepare", "train", "benchmark", "sweep", "select", "report", "finalize"):
        s = sub.add_parser(name)
        s.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        if name in ("train", "benchmark", "sweep"):
            s.add_argument("--smoke", action="store_true", help="2 epochs, few batches, study_id suffix -smoke")
            s.add_argument("--no-tracking", action="store_true")
        if name == "train":
            s.add_argument("--variant", default="gru_gatv2_40")
            s.add_argument("--seed", type=int)
            s.add_argument("--epochs", type=int)
            s.add_argument("--resume", action="store_true")
        if name == "sweep":
            s.add_argument("--variant", required=True)
            s.add_argument("--grid", action="append", required=True, metavar="SECTION.FIELD=V1,V2",
                           help="repeatable, e.g. --grid model.gru_hidden=32,64 --grid train.lr=1e-3,5e-4")
            s.add_argument("--seeds", type=int, nargs="+", help="default: first seed in the config")
        if name in ("select", "report", "finalize"):
            s.add_argument("--smoke", action="store_true", help="operate on the -smoke study")
    surge = sub.add_parser("surge", help="forecast one cutoff and write demo/shadow surge proposals")
    surge.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    surge.add_argument("--variant", default="gru_gatv2_40")
    surge.add_argument("--seed", type=int)
    target = surge.add_mutually_exclusive_group(required=True)
    target.add_argument("--cutoff", type=int, help="one cutoff index")
    target.add_argument("--split", choices=("train", "val", "test"), help="every eligible cutoff of a split")
    target.add_argument("--from-cutoff", type=int, help="first cutoff of a range (needs --to-cutoff)")
    surge.add_argument("--to-cutoff", type=int, help="last cutoff of a range, inclusive")
    surge.add_argument("--stride", type=int, default=1, help="keep every n-th cutoff of a split or range")
    surge.add_argument("--output", type=Path, help="output file for --cutoff")
    surge.add_argument("--out-dir", type=Path, help="output directory for --split or a range")
    return p


def main(argv: list[str] | None = None) -> int:
    actual = list(sys.argv[1:] if argv is None else argv)
    if actual[:1] != ["legacy"]:
        from surge_ml.geomobinet.cli import main as geomobinet_main
        return geomobinet_main(actual)
    actual = actual[1:]
    args = _parser().parse_args(actual)
    try:
        cfg = apply_overrides(load_config(args.config), smoke=getattr(args, "smoke", False),
                              epochs=getattr(args, "epochs", None), no_tracking=getattr(args, "no_tracking", False))
        if args.command in ("train", "benchmark", "sweep"):
            from surge_ml.tracking.mlflow_adapter import stamped_experiment
            cfg.tracking.experiment = stamped_experiment(cfg.tracking.experiment)
        if args.command == "prepare":
            from surge_ml.orchestration.runner import run_prepare
            run_prepare(cfg)
        elif args.command == "train":
            from surge_ml.features import VARIANTS
            from surge_ml.orchestration.runner import train
            if args.variant not in VARIANTS:
                raise SurgeError("CONFIG", f"unknown variant {args.variant!r}; known: {list(VARIANTS)}")
            result = train(cfg, args.variant, args.seed if args.seed is not None else cfg.seeds[0], args.resume)
            print(f"best_epoch={result['best_epoch']} trial_result: "
                  f"{cfg.runs_root / cfg.study_id / args.variant}")
        elif args.command == "benchmark":
            from surge_ml.orchestration.runner import benchmark
            benchmark(cfg)
        elif args.command == "sweep":
            from surge_ml.orchestration.sweep import parse_grid, sweep
            sweep(cfg, args.variant, parse_grid(args.grid), args.seeds or cfg.seeds[:1])
        elif args.command == "select":
            from surge_ml.evaluation.selection import select
            select(cfg)
        elif args.command == "report":
            from surge_ml.evaluation.report import report
            report(cfg)
        elif args.command == "finalize":
            from surge_ml.evaluation.finalize import finalize
            finalize(cfg)
        else:
            seed = args.seed if args.seed is not None else cfg.seeds[0]
            if args.cutoff is not None:
                from surge_ml.orchestration.propose import generate_proposals
                _, path = generate_proposals(cfg, args.variant, seed, args.cutoff, args.output)
                print(f"surge proposals: {path}")
            else:
                from surge_ml.orchestration.propose import generate_proposal_range
                index = generate_proposal_range(cfg, args.variant, seed, split=args.split,
                                                from_cutoff=args.from_cutoff, to_cutoff=args.to_cutoff,
                                                stride=args.stride, out_dir=args.out_dir)
                count = json.loads(index.read_text(encoding="utf-8"))["count"]
                print(f"surge proposals: {count} cutoffs, index {index}")
    except SurgeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
