"""Publish a validated 30-day candidate; retain legacy data and diagnostics.

Only moves the newly generated staging directory after matching dataset-level
integrity reports, regression results and two successful model smoke tests.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def write(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')


def test_result(path):
    root=ET.parse(path).getroot()
    suites=list(root.iter('testsuite'))
    return {'tests':sum(int(x.attrib.get('tests',0)) for x in suites),
            'failures':sum(int(x.attrib.get('failures',0)) for x in suites),
            'errors':sum(int(x.attrib.get('errors',0)) for x in suites),
            'skipped':sum(int(x.attrib.get('skipped',0)) for x in suites)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--destination',required=True)
    p.add_argument('--lgbm-run',required=True);p.add_argument('--gat-run',required=True)
    a=p.parse_args()
    src=(ROOT/a.source).resolve();dest=(ROOT/a.destination).resolve()
    if ROOT/'data'/'staging' not in src.parents:raise ValueError('Source must be a staging dataset')
    if ROOT/'data'/'releases' not in dest.parents:raise ValueError('Destination must be a new release')
    if dest.exists():raise FileExistsError(dest)
    if (ROOT/'data'/'CURRENT.json').exists():raise FileExistsError('CURRENT exists; refusing to replace an unrelated dataset pointer')
    manifest=read(src/'dataset_manifest.json')
    raw=read(src/'reports'/'raw_integrity.json');features=read(src/'reports'/'feature_validation.json')
    if manifest['days']!=30 or manifest['tensor_shape']!=[8640,61,40]:raise AssertionError('30-day shape mismatch')
    if not all(raw.values()) or not all(features.values()):raise AssertionError('Integrity gate failed')
    tests={name:test_result(ROOT/'artifacts'/file) for name,file in
           [('new_regressions','mock_v2_tests.xml'),('legacy_regressions','mock_v2_legacy_tests.xml')]}
    if any(not t['tests'] or t['failures'] or t['errors'] for t in tests.values()):raise AssertionError(tests)
    runs={}
    for label,where in [('lgbm',a.lgbm_run),('gru_gatv2',a.gat_run)]:
        folder=ROOT/where
        report=read(folder/'verification.json')
        if report['status']!='passed' or report['model']!=label or report['dataset_fingerprint']!=manifest['dataset_fingerprint']:
            raise AssertionError(f'Model verification does not match this dataset: {label}')
        runs[label]=report
        target=src/'reports'/label;target.mkdir(exist_ok=False)
        for name in ['verification.json','train.log','history.csv']:
            shutil.copy2(folder/name,target/name)
    # Recheck tensor content after training; training must not change dataset arrays.
    for name,expected in read(src/'training_sha256.json').items():
        h=hashlib.sha256()
        with (src/'training'/name).open('rb') as f:
            for buf in iter(lambda:f.read(4*1024**2),b''):h.update(buf)
        if h.hexdigest()!=expected:raise AssertionError(f'Changed training payload {name}')
    metrics=read(src/'reports'/'eda_metrics.json')
    warnings=[]
    if not .75<=metrics['completion_rate_mature']<=.90:
        warnings.append({'metric':'completion_rate_mature','value':metrics['completion_rate_mature'],'reference_range':[.75,.90]})
    if not .15<=metrics['surge_gt1_share']<=.30:
        warnings.append({'metric':'surge_gt1_share','value':metrics['surge_gt1_share'],'reference_range':[.15,.30]})
    manifest.update({'training_ready':True,'status':'training_ready_with_realism_warnings' if warnings else 'training_ready',
        'readiness_scope':'technical input/training compatibility for synthetic experiments; not proof of marketplace realism or pricing impact',
        'realism_validation_complete':False,'deployment_ready':False,'realism_warnings':warnings,
        'model_smoke_tests':{k:v['status'] for k,v in runs.items()},'regression_tests':tests,
        'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'release_relative_path':dest.relative_to(ROOT).as_posix()})
    write(src/'dataset_manifest.json',manifest)
    write(src/'reports'/'regression_results.json',tests)
    write(src/'reports'/'readiness.json',{'technical_ready':True,'raw_checks':len(raw),'feature_checks':len(features),
        'smoke_models':list(runs),'tests':tests,'realism_warnings':warnings,'deployment_ready':False})
    provenance=src/'provenance';provenance.mkdir()
    sources=list(manifest['source_sha256'])+['pipeline/prepared_data.py','pipeline/train_v2.py','pipeline/model.py','tools/mock_v2/run.py','tools/mock_v2/test_v2.py','tools/mock_v2/promote.py']
    provenance_hashes={}
    for name in sources:
        target=provenance/name;target.parent.mkdir(parents=True,exist_ok=True)
        payload=(ROOT/name).read_bytes()
        expected=manifest['source_sha256'].get(name)
        if expected is not None and hashlib.sha256(payload).hexdigest()!=expected:
            # Preserve exact generation bytes after a CRLF-only working-copy format change.
            normalized=payload.replace(b'\r\n',b'\n')
            if hashlib.sha256(normalized).hexdigest()!=expected:
                raise AssertionError(f'Source changed since generation: {name}')
            payload=normalized
        target.write_bytes(payload)
        provenance_hashes[name]=hashlib.sha256(payload).hexdigest()
    write(provenance/'source_sha256.json',provenance_hashes)
    import importlib.metadata as package_metadata
    write(src/'reports'/'runtime_versions.json',{name:package_metadata.version(name)
        for name in ['numpy','pandas','numba','h3','pyarrow','torch','lightgbm','scikit-learn','pytest','scipy','PyYAML']})
    report=f'''# Mock V2 — 30-day training dataset

Status: **technical training ready, with realism warnings**.

- Dataset: `{manifest['dataset_id']}`
- Coverage: 2026-01-05 through 2026-02-03; last snapshot is 2026-02-04 00:00 local time.
- 61 H3 resolution-7 cells, 8,640 snapshots, {metrics['n_snapshot_rows']:,} hex rows.
- Observed main-period orders: {metrics['n_orders']:,}.
- One burn-in day retained in `context/`, excluded from the 30-day training grid.
- Node features: 40. Edge features: 10. GAT adds reverse/self flags -> 12 internally.
- Target: log((D[t+h]+1)/(S_eff[t+h]+1)), h=5/10/15 minutes.
- Train: Jan 5-25 (21 days); validation: Jan 26-29 (4 days); test: Jan 30-Feb 3 (5 days).
- Eligible samples: {manifest['sample_counts']}.
- Raw checks: {len(raw)}/{len(raw)}. Feature checks: {len(features)}/{len(features)}.
- Model runs are smoke tests only, NOT predictive-quality benchmarks.

## Physics and event-time fixes

Intra-hex radius is now configured. Dispatch cannot precede request readiness or
driver availability, and cannot occur after the patience deadline.
Repositioning is a separate unavailable state.
Unfinished lifecycle events are independently censored; historical context is retained.
Future arrival actuals and private simulator audit fields never enter features.

## EDA

| Metric | Value |
|---|---:|
| Intra-hex estimate unique values | {metrics['intra_estimate_unique']:,} |
| Intra-hex estimate median minutes | {metrics['intra_estimate_p50']:.4f} |
| Mature completion rate | {metrics['completion_rate_mature']:.4%} |
| Peak sampled utilization | {metrics['util_peak_sampled']:.4%} |
| Off-peak sampled utilization | {metrics['util_offpeak_sampled']:.4%} |
| Snapshot share demand > idle | {metrics['demand_gt_idle_share']:.4%} |
| Snapshot share surge > 1 | {metrics['surge_gt1_share']:.4%} |
| Snapshot share surge >= 2 | {metrics['surge_ge2_share']:.4%} |
| Trip duration median minutes | {metrics['trip_min_median']:.4f} |
| Accepted-to-pickup median minutes | {metrics['pickup_min_median']:.4f} |

Completion and surge exposure remain outside the old heuristic reference ranges.
The generator was not distorted to force these metrics to pass. Utilization is a
minute-end sample estimate, not exact driver-minute accounting. Booking/driver-offer
acceptance, revenue, real car service and res9 micro-cells are NOT fabricated.
OD/adjacency inputs are available; GNN benefit and pricing impact are not yet established.

## Runtime

Use `pipeline/prepared_data.py` or `pipeline/train_v2.py`, not the legacy raw loader.
Feature order and imputation/smoothing rules are in `feature_contract.json`.
Rates use fixed Beta(1,1) smoothing; zero-support pickup P90 falls back to current ETA.
Support columns are exported separately. Normalization is train-only.
No legacy feature cache is reused. SHA256 checks protect all training payloads.

Original `data/hcm_data`, prior runs and the user's EDA notebook remain untouched.
'''
    (src/'reports'/'REPORT.md').write_text(report,encoding='utf-8')
    dest.parent.mkdir(parents=True,exist_ok=True)
    src.rename(dest)
    pointer={'dataset_id':manifest['dataset_id'],'path':dest.relative_to(ROOT).as_posix(),
             'manifest':(dest/'dataset_manifest.json').relative_to(ROOT).as_posix(),
             'dataset_fingerprint':manifest['dataset_fingerprint'],'training_ready':True,
             'entrypoint':'pipeline/train_v2.py'}
    write(ROOT/'data'/'CURRENT.json',pointer)
    (ROOT/'artifacts'/'mock_v2_completion.json').write_text(json.dumps({'release':str(dest),**pointer,
        'metrics':metrics,'raw_checks':len(raw),'feature_checks':len(features),'regression_tests':tests,
        'edge_rows':manifest['edge_rows'],'sample_counts':manifest['sample_counts'],
        'size_bytes':sum(x.stat().st_size for x in dest.rglob('*') if x.is_file()),
        'original_dataset_exists':(ROOT/'data'/'hcm_data').exists()},indent=2),encoding='utf-8')
    print((ROOT/'artifacts'/'mock_v2_completion.json').read_text(encoding='utf-8'),flush=True)

if __name__=='__main__':main()
