"""Command-line entry point for the active GeoMobiNet-SMG pipeline."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import NEURAL_VARIANTS, VARIANTS, Config, load_config

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "geomobinet.yaml"


def parser():
    root = argparse.ArgumentParser(prog="surge-ml", description="GeoMobiNet-SMG demand/idle-supply forecasting")
    commands = root.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="write an isolated synthetic schema fixture; never real benchmark data")
    demo.add_argument("--output-dir", type=Path, required=True)
    demo.add_argument("--steps", type=int, default=160)
    demo.add_argument("--nodes", type=int, default=7)
    demo.add_argument("--seed", type=int, default=42)
    for name in ("prepare", "train", "benchmark", "report", "select", "finalize", "predict"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        command.add_argument("--smoke", action="store_true", help="isolated -smoke output directory, 2 epochs/2 training batches")
        if name in ("train", "benchmark"):
            command.add_argument("--epochs", type=int)
        if name == "train":
            command.add_argument("--variant", choices=VARIANTS, default="geomobinet_smg")
            command.add_argument("--seed", type=int)
            command.add_argument("--resume", action="store_true")
        if name == "predict":
            command.add_argument("--checkpoint", type=Path, required=True)
            command.add_argument("--cutoff", type=int, help="snapshot index; default is last observed timestamp")
            command.add_argument("--output", type=Path, required=True)
    return root


def effective_config(args) -> Config:
    original = load_config(args.config)
    value = original.model_dump()
    if args.smoke:
        value["study_id"] += "-smoke"
        value["output_dir"] = original.output_dir.with_name(original.output_dir.name + "-smoke")
        value["train"]["epochs"] = 2
        value["train"]["limit_batches"] = 2
    if getattr(args, "epochs", None) is not None:
        value["train"]["epochs"] = args.epochs
    return Config.model_validate(value)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            from .demo import write_demo
            path = write_demo(args.output_dir, steps=args.steps, nodes=args.nodes, seed=args.seed)
            print(f"Synthetic fixture config: {path}")
            return 0
        cfg = effective_config(args)
        from . import runner
        if args.command == "prepare":
            panel, splits, _, _ = runner.prepare(cfg)
            print(f"Prepared {len(panel.timestamps)} snapshots x {panel.n_nodes} nodes; "
                  f"samples: { {key: len(value) for key, value in splits.items()} }")
        elif args.command == "train":
            result = runner.run_trial(cfg, args.variant, args.seed if args.seed is not None else cfg.seeds[0],
                                      resume=args.resume)
            print(f"validation: {result['validation']['overall']}")
        elif args.command == "benchmark":
            runner.benchmark(cfg)
            runner.report(cfg)
        elif args.command == "report":
            runner.report(cfg)
        elif args.command == "select":
            selection = runner.select(cfg)
            print(f"Frozen selection: {selection['selected_variant']}")
        elif args.command == "finalize":
            runner.finalize(cfg)
            print(f"Final test report: {cfg.output_dir / 'test_report.json'}")
        elif args.command == "predict":
            frame = runner.forecast(cfg, args.checkpoint.resolve(), cutoff=args.cutoff, output=args.output)
            print(f"Wrote {len(frame)} forecasts: {args.output.resolve()}")
    except (ValueError, OSError, RuntimeError, ImportError, KeyError, TypeError) as exc:
        print(f"GeoMobiNet error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
