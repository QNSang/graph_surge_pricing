"""Standalone GGSO TEST_ONLY CLI; does not change the default surge-ml CLI."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
import numpy as np
import pydantic
import scipy
from .config import FitConfig, PolicyConfig
from .contracts import CandidateTable, DecisionResult, Forecast, OperationalSnapshot, ResponseArtifact
from .fixtures import make_fitted_fixture, make_fixture
from .integration.decision_runner import run_decision
from .simulation.candidates import build_candidates


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def replay_payload(payload: dict) -> DecisionResult:
    if not isinstance(payload, dict) or set(payload) != {"identity", "policy", "operational", "response", "forecast"}:
        raise ValueError("Replay requires exactly identity, policy, operational, response and forecast")
    forecast = payload["forecast"]
    # Parsing errors are handled inside the same fail-closed decision boundary.
    try:
        generated_at = Forecast.model_validate(forecast).generated_at
    except ValueError:
        generated_at = None
    return run_decision(identity=payload["identity"], policy=payload["policy"], operational=payload["operational"],
                        response=payload["response"], forecast_provider=lambda _: forecast, generated_at=generated_at)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GGSO synthetic/offline verification only; no price publication")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the explicit synthetic network fixture")
    demo.add_argument("--output-dir", required=True, type=Path)
    demo.add_argument("--cells", default=2, type=int)
    demo.add_argument("--fit-response", action="store_true", help="Fit synthetic NB/Binomial models and paired bootstrap first")
    replay = commands.add_parser("replay", help="Replay frozen GGSO TEST_ONLY JSON inputs without refitting/inference")
    replay.add_argument("--input", required=True, type=Path)
    replay.add_argument("--output", required=True, type=Path)
    schemas = commands.add_parser("schemas", help="Export executable versioned JSON schemas")
    schemas.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "schemas":
            args.output_dir.mkdir(parents=True, exist_ok=False)
            for model in (Forecast, OperationalSnapshot, ResponseArtifact, CandidateTable, DecisionResult, PolicyConfig, FitConfig):
                write_json(args.output_dir / f"{model.__name__}.schema.json", model.model_json_schema())
            print(f"Wrote TEST_ONLY schemas to {args.output_dir}")
            return 0
        if args.command == "replay":
            if args.output.exists():
                raise FileExistsError(f"Refusing to overwrite {args.output}")
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            result = replay_payload(payload)
            write_json(args.output, result.model_dump(mode="json"))
        else:
            args.output_dir.mkdir(parents=True, exist_ok=False)
            factory = make_fitted_fixture if args.fit_response else make_fixture
            fixture = factory(hex_count=args.cells)
            result = fixture.run()
            write_json(args.output_dir / "input.json", fixture.payload())
            write_json(args.output_dir / "decision.json", result.model_dump(mode="json"))
            write_json(args.output_dir / "response.json", fixture.response.model_dump(mode="json"))
            if result.result_status == "VALID":
                write_json(args.output_dir / "candidates.json", build_candidates(fixture.network()).model_dump(mode="json"))
            write_json(args.output_dir / "evidence.json", {
                "scope": "TEST_ONLY_SOFTWARE_VERIFICATION", "production_eligible": False,
                "python": platform.python_version(), "scipy": scipy.__version__, "numpy": np.__version__,
                "pydantic": pydantic.__version__, "fitted_synthetic_responses": args.fit_response,
                "hex_count": args.cells, "result_status": result.result_status,
                "artifact_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(args.output_dir.glob("*.json"))},
                "source_sha256": {path.relative_to(Path(__file__).parent).as_posix():
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(Path(__file__).parent.rglob("*.py"))},
                "solver": None if result.solver is None else result.solver.model_dump(mode="json"),
                "limitations": "No real source-data/checkpoint parity, no causal/realized uplift claim, no price writes"})
        print(json.dumps({"status": result.result_status, "recommendations": len(result.recommendations),
                          "error_code": result.error_code, "publication": result.publication,
                          "production_effective": False}, ensure_ascii=False))
        return 0 if result.result_status == "VALID" else 2
    except (ValueError, OSError) as exc:
        print(f"GGSO CLI: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
