"""Explicit subprocess compatibility. Retired code never enters the active namespace."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run_legacy(arguments: list[str]) -> int:
    pipeline = Path(__file__).resolve().parents[2]
    archive = pipeline/'_archive'/'pre_duocast_20261017'
    if not (archive/'src'/'surge_ml'/'cli.py').is_file():
        raise ValueError('Archived compatibility source is unavailable')
    env = {**os.environ, 'PYTHONPATH': str(archive/'src')}
    args = list(arguments[1:])
    if arguments[0] == 'legacy-ggso':
        return subprocess.run([sys.executable,'-m','surge_ml.ggso',*args],env=env,check=False).returncode
    legacy_commands = {'prepare','train','benchmark','sweep','select','report','finalize','surge'}
    # Archived YAML is byte-preserved. Only a temporary copy resolves its relative
    # paths against the ORIGINAL config directory, never against the archive.
    with tempfile.TemporaryDirectory(prefix='duocast-legacy-config-') as temporary:
        if args and args[0] in legacy_commands and not {'-h','--help'}.intersection(args):
            index = args.index('--config') if '--config' in args else None
            supplied = Path(args[index+1]).resolve() if index is not None else pipeline/'configs'/'train.yaml'
            inline = next((a for a in args if a.startswith('--config=')), None)
            if inline is not None:
                supplied = Path(inline.split('=',1)[1]).resolve()
            original = pipeline/'configs'/'train.yaml'
            if not supplied.is_file() and supplied == original:
                import yaml
                raw = yaml.safe_load((archive/'configs'/'train.yaml').read_text(encoding='utf-8'))
                for key in ('runs_root',):
                    if raw.get(key):
                        raw[key] = str((original.parent/Path(raw[key])).resolve())
                for key in ('source_root','derived_root'):
                    if raw.get('data',{}).get(key):
                        raw['data'][key] = str((original.parent/Path(raw['data'][key])).resolve())
                resolved = Path(temporary)/'train.yaml'
                resolved.write_text(yaml.safe_dump(raw,sort_keys=False),encoding='utf-8')
                if inline is not None:
                    args[args.index(inline)] = '--config='+str(resolved)
                elif index is None:
                    args.extend(['--config',str(resolved)])
                else:
                    args[index+1] = str(resolved)
        return subprocess.run([sys.executable,'-m','surge_ml.cli','legacy',*args],env=env,check=False).returncode
