"""One entrypoint for forecast training, response fitting and GGSO decisions."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'configs' / 'duocast.yaml'

def parser():
    from surge_ml.train.duocast._constant import VARIANTS
    root = argparse.ArgumentParser(prog='surge-ml', description='DuoCast no-geo + per-cell response GLMs + GGSO MILP')
    commands = root.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='Create explicit synthetic no-geo training input')
    demo.add_argument('--output-dir', type=Path, required=True)
    demo.add_argument('--steps', type=int, default=160)
    demo.add_argument('--nodes', type=int, default=7)
    demo.add_argument('--seed', type=int, default=42)
    preflight = commands.add_parser('preflight', help='Validate data and split coverage without training')
    preflight.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    preflight.add_argument('--output', type=Path, help='Optional new JSON report; never overwrite')
    for name in ('prepare','train','benchmark','report','select','finalize','predict'):
        cmd = commands.add_parser(name)
        cmd.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
        cmd.add_argument('--smoke', action='store_true')
        if name in ('train','benchmark'):
            cmd.add_argument('--epochs', type=int)
        if name in ('train', 'benchmark'):
            cmd.add_argument('--resume', action='store_true', help='Continue neural checkpoints; benchmark also reuses verified completed trials')
        if name == 'train':
            cmd.add_argument('--variant', choices=VARIANTS, default='duocast')
            cmd.add_argument('--seed', type=int)
        if name == 'predict':
            cmd.add_argument('--checkpoint', type=Path, required=True)
            cmd.add_argument('--cutoff', type=int)
            cmd.add_argument('--output', type=Path, required=True)
    fit = commands.add_parser('fit-responses', help='Fit independent GLMs from explicitly matured observation JSON')
    fit.add_argument('--config', type=Path, required=True)
    dd = commands.add_parser('decision-demo', help='TEST_ONLY fitted/declared response and mock forecast workflow')
    dd.add_argument('--output-dir', type=Path, required=True)
    dd.add_argument('--cells', type=int, default=2)
    dd.add_argument('--fit-response', action='store_true')
    decide = commands.add_parser('decide', help='Run a real synthetic-trained DuoCast checkpoint and supplied GGSO inputs')
    decide.add_argument('--config', type=Path, required=True)
    decide.add_argument('--checkpoint', type=Path, required=True)
    decide.add_argument('--input', type=Path, required=True)
    decide.add_argument('--output-dir', type=Path, required=True)
    replay = commands.add_parser('replay', help='Replay frozen decision input without refitting models')
    replay.add_argument('--input', type=Path, required=True)
    replay.add_argument('--output', type=Path, required=True)
    schemas = commands.add_parser('schemas')
    schemas.add_argument('--output-dir', type=Path, required=True)
    return root

def effective_config(args):
    from surge_ml.train.duocast._types import load_config, Config
    cfg = load_config(args.config)
    values = cfg.model_dump()
    if args.smoke:
        values['study_id'] += '-smoke'
        values['output_dir'] = cfg.output_dir.with_name(cfg.output_dir.name+'-smoke')
        values['train'].update(epochs=2, limit_batches=2, lgbm_rounds=5)
    if getattr(args,'epochs',None) is not None:
        values['train']['epochs'] = args.epochs
    return Config.model_validate(values)

def save_decision(folder, result, payload, candidates=None):
    from surge_ml._utils.io import write_json, digest_file
    import platform
    import scipy
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder/'decision.json',result.model_dump(mode='json'))
    write_json(folder/'input.json',payload)
    if candidates is not None:
        write_json(folder/'candidates.json',candidates.model_dump(mode='json'))
    write_json(folder/'evidence.json',dict(scope='TEST_ONLY',production_eligible=False,
        python=platform.python_version(),scipy=scipy.__version__,result_status=result.result_status,
        artifact_sha256={p.name:digest_file(p) for p in sorted(folder.glob('*.json'))},
        solver=None if result.solver is None else result.solver.model_dump(mode='json')))

def main(argv=None):
    actual = list(sys.argv[1:] if argv is None else argv)
    if actual[:1] in (['legacy'], ['legacy-ggso']):
        from surge_ml.legacy import run_legacy
        return run_legacy(actual)
    args = parser().parse_args(actual)
    try:
        from surge_ml._utils.io import write_json
        if args.command == 'preflight':
            from surge_ml.datasets.preflight import inspect_dataset
            result = inspect_dataset(args.config)
            if args.output is not None:
                write_json(args.output, result)
            print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
            return 0
        if args.command == 'demo':
            from surge_ml.datasets.fixtures import write_demo
            print(write_demo(args.output_dir,steps=args.steps,nodes=args.nodes,seed=args.seed))
            return 0
        if args.command == 'schemas':
            from surge_ml.contracts import Forecast, OperationalSnapshot, ResponseArtifact, CandidateTable, DecisionResult
            from surge_ml.inferences.schemas import PolicyConfig
            from surge_ml.train.responses._types import FitConfig
            args.output_dir.mkdir(parents=True,exist_ok=False)
            for model in (Forecast,OperationalSnapshot,ResponseArtifact,CandidateTable,DecisionResult,PolicyConfig,FitConfig):
                write_json(args.output_dir/f'{model.__name__}.schema.json',model.model_json_schema())
            return 0
        if args.command == 'fit-responses':
            from surge_ml.train.responses.train import fit_from_config
            result = fit_from_config(args.config)
            print(json.dumps(result))
            return 0
        if args.command == 'decision-demo':
            from surge_ml.datasets.fixtures import make_fixture, make_fitted_fixture
            from surge_ml.inferences.candidate_utility import build_candidates
            fixture = (make_fitted_fixture if args.fit_response else make_fixture)(hex_count=args.cells)
            result = fixture.run()
            save_decision(args.output_dir,result,fixture.payload(),
                          build_candidates(fixture.network()) if result.result_status=='VALID' else None)
        elif args.command == 'replay':
            from surge_ml.inferences.service import replay_payload
            result = replay_payload(json.loads(args.input.read_text(encoding='utf-8')))
            write_json(args.output,result.model_dump(mode='json'))
        elif args.command == 'decide':
            from surge_ml.train.duocast._types import load_config
            from surge_ml.inferences.duocast import CheckpointForecastProvider
            from surge_ml.inferences.service import run_decision
            payload = json.loads(args.input.read_text(encoding='utf-8'))
            if set(payload) != {'identity','policy','operational','response'}:
                raise ValueError('Decision input must contain identity, policy, operational, response')
            config = load_config(args.config)
            if args.output_dir.exists():
                raise FileExistsError(f'Refusing to overwrite {args.output_dir}')
            captured = {'forecast': None}
            def once(identity):
                # Initialization failures belong to the same fail-closed boundary.
                provider = CheckpointForecastProvider(config, args.checkpoint,
                                                     forecast_run_id=identity.decision_id+':forecast')
                forecast = provider(identity)
                captured['forecast'] = forecast.model_dump(mode='json')
                return forecast
            result = run_decision(**payload,forecast_provider=once)
            candidates = None
            if result.result_status == 'VALID':
                from surge_ml.inferences.schemas import prepare_network
                from surge_ml.inferences.candidate_utility import build_candidates
                candidates = build_candidates(prepare_network(captured['forecast'],payload['operational'],
                                                               payload['response'],payload['policy']))
            save_decision(args.output_dir,result,{**payload,**captured},candidates)
        else:
            cfg = effective_config(args)
            from surge_ml.train.duocast import train as training
            from surge_ml.reports import benchmark as reporting
            if args.command=='prepare':
                panel,splits,_,_ = training.prepare(cfg)
                print(json.dumps(dict(nodes=panel.n_nodes,snapshots=len(panel.timestamps),samples={k:len(v) for k,v in splits.items()})))
            elif args.command=='train':
                training.run_trial(cfg,args.variant,args.seed if args.seed is not None else cfg.seeds[0],resume=args.resume)
            elif args.command=='benchmark':
                training.benchmark(cfg, resume=args.resume)
                reporting.report(cfg)
            elif args.command=='report': reporting.report(cfg)
            elif args.command=='select': print(json.dumps(reporting.select(cfg)))
            elif args.command=='finalize': reporting.finalize(cfg)
            elif args.command=='predict':
                from surge_ml.inferences.duocast import forecast
                forecast(cfg,args.checkpoint,cutoff=args.cutoff,output=args.output)
            return 0
        print(json.dumps(dict(status=result.result_status,recommendations=len(result.recommendations),
                              error_code=result.error_code,publication=result.publication)))
        return 0 if result.result_status=='VALID' else 2
    except (ValueError,OSError,RuntimeError,ImportError,KeyError,TypeError) as exc:
        print(f'DuoCast pipeline: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

if __name__ == '__main__':
    raise SystemExit(main())
