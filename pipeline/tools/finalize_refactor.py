"""Record refactor evidence and update scoped documentation after passing tests.

No dataset, checkpoint, backend, UI, Git index, commit or remote is mutated.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

PIPE = Path(__file__).resolve().parents[1]
ROOT = PIPE.parent
ARCHIVE = PIPE/'_archive'/'pre_duocast_20261017'
EVIDENCE = PIPE/'runs'/'duocast-refactor-verification'
REPORT = ROOT/'docs'/'implementation'/'PIPELINE_REFACTOR_STATUS.md'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_counts(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
    counts = {key: sum(int(s.get(key,'0')) for s in suites) for key in ('tests','failures','errors','skipped')}
    if not counts['tests'] or any(counts[k] for k in ('failures','errors','skipped')):
        raise RuntimeError(f'Tests not fully passing: {path}: {counts}')
    return {**counts,'sha256':sha(path)}


def update_document(path: Path, body: str) -> None:
    if not path.is_file():
        return
    before = path.read_bytes()
    text = before.decode('utf-8')
    marker = '<!-- duocast-refactor-active -->'
    if marker in text:
        return
    backup = ARCHIVE/'documentation_before_refactor'/path.relative_to(ROOT)
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():
        backup.write_bytes(before)
    head, separator, tail = text.partition('\n')
    block = marker+'\n\n## Active code update — 2026-10-17\n\n'+body+'\n\nThe following pre-refactor notes are retained as history where they describe the older implementation.\n\n'
    if path.read_bytes() != before:
        raise RuntimeError(f'Concurrent document edit: {path}')
    path.write_text(head+'\n\n'+block+tail,encoding='utf-8',newline='\n')


def main() -> None:
    manifest = json.loads((ARCHIVE/'manifest.json').read_text(encoding='utf-8'))
    mismatches = [name for name,digest in manifest['original_sha256'].items()
                  if not (ARCHIVE/name).is_file() or sha(ARCHIVE/name)!=digest]
    if mismatches:
        raise RuntimeError(f'Original source archive mismatch: {mismatches[:10]}')
    reports = {name:test_counts(EVIDENCE/name) for name in ('active-tests.xml','backend-unit-tests.xml')}
    check = subprocess.run(['git','diff','--check'],cwd=ROOT,capture_output=True,text=True,check=False)
    if check.returncode:
        raise RuntimeError('git diff --check failed: '+check.stdout+check.stderr)
    source = PIPE/'src'/'surge_ml'
    for file in source.rglob('*.py'):
        compile(file.read_text(encoding='utf-8'),str(file),'exec')
    evidence = dict(scope='SYNTHETIC_SOFTWARE_ACCEPTANCE',created_at=datetime.now(timezone.utc).isoformat(),
        official_data_used=False,production_effective=False,
        active_source_sha256={p.relative_to(source).as_posix():sha(p) for p in sorted(source.rglob('*.py'))},
        tests=reports,archive_files_verified=len(manifest['original_sha256']),
        original_archive=str(ARCHIVE.relative_to(ROOT)),git_diff_check_exit=check.returncode,
        git_diff_check_warnings=check.stderr)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    path=EVIDENCE/'evidence.json'
    if path.exists():
        raise FileExistsError('Evidence is immutable: '+str(path))
    path.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    # Retain staging evidence and the one-shot migration implementation outside the active tree.
    staging=PIPE/'.duocast-refactor'
    if staging.exists():
        staging.rename(ARCHIVE/'refactor_staging_evidence')
    tool=PIPE/'tools'/'refactor_duocast.py'
    if tool.exists():
        tool.rename(ARCHIVE/'migration_tool.py')
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text('''# DuoCast pipeline refactor — executed code and evidence

User-authorized replacement of the active GeoMobiNet pipeline with the agreed no-static-geo folder architecture. This is a code implementation, not another proposal. Existing datasets, checkpoints and backend/UI source were not modified.

## Active implementation

`pipeline/src/surge_ml/` now contains `_utils`, `contracts`, `datasets`, `train/duocast`, `train/responses`, `inferences`, `reports` and a separate simulated-receipt integration module. GeoMobiNet and the old ratio/GGSO namespaces were removed from the active source tree, not renamed into DuoCast.

Forecast catalog: `lgbm_local`, `gru`, `gru_spatial`, `gru_mobility`, `duocast`. Default study seeds: 42/43/44. Spatial and Mobility variants retain the shared GRU. DuoCast keeps both GATv2 branches and dual count heads, without a Geo Encoder, geo input table, geo metadata identity, or static geographic edge features. Old checkpoints are explicitly rejected by the new `duocast_ds_h5_v1` contract.

Response likelihoods, per-cell constrained fits and paired bootstrap remain independent from forecast training. Candidate equations, fixed capacity, 0.1 additive grid within +/-0.3, nominal network GMV no-loss, BR constraints, HiGHS status handling and solver-independent validation were preserved. The new decision service has no production pricing writes.

Six metrics are emitted to validation/test CSV and Markdown tables with mean/std across configured seeds: D-MAE, S-MAE, Log D-MAE, Log S-MAE, Log D/S MAE, Log D/S RMSE. The log-ratio diagnostic is log((D+1)/(S+1)); the forecast target remains two counts. Validation log-Huber selects models; test does not change selection.

## Additional guards and integration

Observed target counts reject fractional values. A complete mobility snapshot manifest distinguishes missing records from an observed empty graph. Baseline response support is checked independently of policy bounds. Service timestamps allow a forecast genuinely generated after request start. Missing or incompatible checkpoints produce persisted INVALID/no-policy results through the CLI. A test exercises a newly trained DuoCast checkpoint through fitted response models, candidate simulation, HiGHS and validation with one network inference.

## Verification actually executed

- Staging suite: 137 passed, 0 failures/errors/skips; 3 library warnings, exit 0.
- Activated package suite: 137 passed, 0 failures/errors/skips, 32.96 seconds; 3 PyTorch/LightGBM library warnings, exit 0.
- Existing backend unit suite: 49 passed, 2.28 seconds, exit 0. This is not DB/API/UI E2E.
- Root `git diff --check`: exit 0. Existing CRLF warnings remain; CodeLocal's broad wrapper also sees pre-existing pseudo-repository cache warnings.
- Source syntax compilation and SHA-256 verification of the preserved original source/config/test/README/pyproject archive passed.

These are 186 unique cases across the final active and backend suites; staging reruns are not counted again. Tests include small real training/fitting operations on explicit synthetic fixtures only. No official-data training, real calibration, shadow run or production action was performed.

Exact final test commands:

```text
uv run --offline --no-sync --project pipeline pytest pipeline/tests -q --basetemp=pipeline/.pytest_tmp_duocast_refactor_final --junitxml=pipeline/runs/duocast-refactor-verification/active-tests.xml
uv run --offline --no-sync --project backend pytest backend/tests/unit -q --basetemp=backend/.pytest_tmp_duocast_refactor_final --junitxml=pipeline/runs/duocast-refactor-verification/backend-unit-tests.xml
```

Verification files: `pipeline/runs/duocast-refactor-verification/`. Standalone five-model synthetic demo: `pipeline/runs/duocast-refactor-demo-20261017/`. Standalone fitted-response GGSO demo: `pipeline/runs/ggso-refactor-demo-20261017/`. Use actual saved artifacts/exit codes for numerical claims; synthetic demo ranks do not establish forecasting superiority.

## Preservation and compatibility

Byte-preserved old source/configs/tests: `pipeline/_archive/pre_duocast_20261017/`, with original and staged SHA-256 manifests. Staging reports and the one-shot migration tool are retained there as well. Archived ratio commands and old GGSO replay are opt-in subprocess routes (`surge-ml legacy ...`, `surge-ml legacy-ggso ...`), not dependencies of the active runtime. No old checkpoints or datasets were deleted.

GGSO output schemas are now v2 and no-geo. The existing backend v1 bridge was not automatically switched or modified. UI/DB/API migration, official source semantics and production approval remain separate tasks. Unrelated pre-existing working-tree changes were preserved. No stage/commit/push/deploy was performed.

GitNexus was unavailable in the runtime extension catalog; dependency inspection, isolated staging, fresh regression and explicit integration tests were used instead. No GitNexus impact run is claimed.

See `pipeline/README.md` for commands and `pipeline/DATA_INPUTS.md` for the input contract to use when data is supplied. Config numerical values for response/pricing remain TEST_ONLY, not approved operating defaults.
''',encoding='utf-8',newline='\n')
    notes = {
        'docs/ai-context/READ_FIRST.md': 'Start with pipeline/README.md and pipeline/DATA_INPUTS.md. The active source is the no-geo DuoCast refactor; train/duocast and inferences replace the old GeoMobiNet/GGSO source paths.',
        'docs/ai-context/CURRENT_STATE.md': 'The refactor is activated and verified: 137 active pipeline tests plus 49 backend unit tests passed. The default CLI now uses DuoCast, not GeoMobiNet. Source/data/checkpoint approval for official data remains pending.',
        'docs/ai-context/CODEBASE_MAP.md': 'Current code paths: pipeline/src/surge_ml/{contracts,datasets,train/duocast,train/responses,inferences,reports}. Original source/configs/tests are byte-preserved in pipeline/_archive/pre_duocast_20261017 and are not active imports.',
        'docs/ai-context/ARCHITECTURE.md': 'Current executable architecture is datasets -> independent forecast/response training -> trained-artifact inference -> candidate utility -> HiGHS -> independent validator. DuoCast has no static-geo branch. V2 decision schemas are not silently mapped into the old backend v1 provider.',
        'docs/implementation/TASKS.md': 'The user-authorized folder/model refactor has been implemented and tested. This closes the scoped code/synthetic refactor only, not official-data model eligibility or backend/UI production integration.',
        'docs/implementation/DECISION_LOG.md': 'User authorized implementation of the proposed folder architecture and removal of GeoMobiNet from the active pipeline. Spatial and directed Mobility GATv2 remain in DuoCast. No-static-geo checkpoint identity is duocast_ds_h5_v1; GGSO envelope versions are v2. Existing numeric TEST_ONLY policies are not promoted to official policies.',
        'docs/model/forecasting_contract.md': 'The no-static-geo DuoCast implementation now exists in train/duocast/variants/neural.py with catalog ID duocast. Synthetic code/checkpoint integration is tested. Real source semantics, calibration and official checkpoint eligibility remain unverified.',
        'docs/contracts/MODEL_IO_CONTRACT.md': 'Active checkpoint contract: duocast_ds_h5_v1. Runtime GGSO contracts use v2 no-geo identities and reject older GeoMobiNet/ratio checkpoints. Exact executable schemas can be exported with surge-ml schemas. The old interface description below is historical.',
        'docs/contracts/DATA_SCHEMA.md': 'The active no-geo input contract is documented in pipeline/DATA_INPUTS.md: market, spatial edges, directed mobility edges, complete mobility snapshot coverage, and metadata. Geo tables are no longer required or accepted by the active config.',
        'docs/evaluation/MODEL_EVALUATION.md': 'The active five-model study uses lgbm_local, gru, gru_spatial, gru_mobility, duocast. Reports include D/S MAE, log1p D/S MAE, and log((D+1)/(S+1)) MAE/RMSE. Mean/std are computed across seeds; selection uses validation log-Huber and final test is frozen.'
    }
    for relative, note in notes.items():
        target=ROOT/relative
        link=os.path.relpath(REPORT,target.parent).replace(os.sep,'/')
        update_document(target,note+' See [executed refactor evidence]('+link+').')
    for name in ('AGENTS.md','CLAUDE.md'):
        path=ROOT/name
        if not path.is_file():
            continue
        text=path.read_text(encoding='utf-8')
        marker='<!-- active-duocast-routing -->'
        if marker in text:
            continue
        before=path.read_bytes()
        backup=ARCHIVE/'documentation_before_refactor'/name
        backup.parent.mkdir(parents=True,exist_ok=True)
        backup.write_bytes(before)
        text=text.replace('The active GeoMobiNet config is `pipeline/configs/geomobinet.yaml`',
                          'The active no-geo DuoCast config is `pipeline/configs/duocast.yaml`')
        text=text.replace('The default CLI dispatches to GeoMobiNet; legacy commands require their explicit route.',
                          'The default CLI uses the refactored no-geo DuoCast pipeline; archived legacy commands require their explicit subprocess route.')
        anchor='## Skill and documentation routing'
        text=text.replace(anchor,marker+'\n\nCurrent implementation: read `docs/implementation/PIPELINE_REFACTOR_STATUS.md`, `pipeline/README.md` and `pipeline/DATA_INPUTS.md`. Active modules use `train/duocast`, `train/responses` and `inferences`; old GeoMobiNet/GGSO source is archived. Do not restore a Geo Encoder or relabel old checkpoints. Official-data eligibility is still a separate gate.\n\n'+anchor,1)
        if path.read_bytes()!=before:
            raise RuntimeError('Concurrent instruction edit: '+name)
        path.write_text(text,encoding='utf-8',newline='\n')
    print(json.dumps({'archive_verified_files':evidence['archive_files_verified'],
        'active_source_files':len(evidence['active_source_sha256']), 'tests':reports,
        'evidence':str(EVIDENCE/'evidence.json'),'git_diff_check_exit':check.returncode}))


if __name__=='__main__':
    main()
