"""Read-only dependency and source-provenance check for the 30-day release."""
import hashlib
import importlib
import json
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
packages = {}
for name in ('numpy', 'pandas', 'numba', 'h3', 'pyarrow', 'yaml', 'torch', 'lightgbm', 'pytest', 'scipy'):
    try:
        mod = importlib.import_module(name)
        packages[name] = {'available': True, 'version': getattr(mod, '__version__', 'unknown')}
    except Exception as exc:
        packages[name] = {'available': False, 'error': str(exc)}
paths = ['mock_data_pipeline/surge_mock/kernel.py', 'mock_data_pipeline/surge_mock/simulate.py', 'mock_data_pipeline/surge_mock/writers.py']
print(json.dumps({'python': sys.version, 'root': str(root), 'packages': packages,
    'disk_free_gb': round(shutil.disk_usage(root).free / 1024**3, 2),
    'source_sha256': {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}}, indent=2))
