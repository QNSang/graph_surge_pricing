"""CLI error envelopes and import isolation for the refactored pipeline."""
from __future__ import annotations
import ast
import json
from pathlib import Path

from surge_ml.cli import main
from surge_ml.datasets.fixtures import make_fixture, write_demo


def test_missing_checkpoint_is_a_persisted_invalid_result(tmp_path):
    config = write_demo(tmp_path/'forecast', steps=120, nodes=3)
    payload = make_fixture(hex_count=3).payload()
    payload.pop('forecast')
    source = tmp_path/'operational.json'
    source.write_text(json.dumps(payload), encoding='utf-8')
    out = tmp_path/'decision'
    assert main(['decide','--config',str(config),'--checkpoint',str(tmp_path/'missing.pt'),
                 '--input',str(source),'--output-dir',str(out)]) == 2
    result = json.loads((out/'decision.json').read_text())
    assert result['result_status'] == 'INVALID'
    assert result['recommendations'] == [] and result['optimized_policy'] is None
    assert result['publication'] == 'NOT_REQUESTED'
    assert json.loads((out/'input.json').read_text())['forecast'] is None
    replayed = tmp_path/'replayed.json'
    assert main(['replay','--input',str(out/'input.json'),'--output',str(replayed)]) == 2
    assert json.loads(replayed.read_text())['recommendations'] == []


def test_active_package_has_no_imports_from_retired_engines():
    import surge_ml
    root = Path(surge_ml.__file__).parent
    forbidden = ('surge_ml.geomobinet', 'surge_ml.ggso', 'surge_ml.models', 'surge_ml.training', 'surge_ml.orchestration')
    for path in root.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = [node.module or ''] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
            assert not any(name.startswith(forbidden) for name in names), path
