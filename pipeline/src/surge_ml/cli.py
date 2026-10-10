"""Dòng lệnh surge-ml."""

import argparse
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
    surge.add_argument("--cutoff", type=int, required=True)
    surge.add_argument("--output", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
            from surge_ml.orchestration.propose import generate_proposals
            _, path = generate_proposals(cfg, args.variant, args.seed if args.seed is not None else cfg.seeds[0],
                                         args.cutoff, args.output)
            print(f"surge proposals: {path}")
    except SurgeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
