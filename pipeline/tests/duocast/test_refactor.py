"""New architecture/data boundaries and checkpoint-to-MILP integration regressions."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ast
import json
import numpy as np
import pandas as pd
import pytest
import torch
import yaml
from surge_ml.datasets.fixtures import write_demo, make_fixture, make_fitted_fixture, synthetic_observations, fit_config
from surge_ml.datasets.duocast import load_panel, input_schema
from surge_ml.train.duocast._types import load_config, DataConfig
from surge_ml.train.duocast._constant import MAIN_VARIANTS
from surge_ml.train.duocast.train import run_trial, prepare, benchmark
from surge_ml.inferences.duocast import CheckpointForecastProvider, load_checkpoint
from surge_ml.inferences.service import run_decision
from surge_ml.reports.metrics import point_metrics, FORECAST_METRICS
from surge_ml.reports.benchmark import select, finalize, report
from surge_ml.train.responses.train import fit_from_config

def change(model, **updates):
    return type(model).model_validate({**model.model_dump(),**updates})

@pytest.fixture
def cfg(tmp_path):
    config = load_config(write_demo(tmp_path/'forecast',steps=120,nodes=3))
    config.model.hidden=8
    config.model.head_hidden=4
    config.train.epochs=1
    config.train.lgbm_rounds=3
    config.train.device='cpu'
    return config

@pytest.mark.parametrize('field,value', [('geo','x.csv'),('geo_features',['distance_to_cbd_km']),
    ('mobility_features',['flow_5m','distance_km']),('dynamic_features',['demand_5m','idle_supply_t','road_density'])])
def test_static_geo_is_rejected(cfg,field,value):
    with pytest.raises(ValueError):
        change(cfg.data,**{field:value})

@pytest.mark.parametrize('column',['demand_5m','idle_supply_t'])
def test_fractional_observation_not_a_count(cfg,column):
    frame=pd.read_csv(cfg.data.market)
    frame[column]=frame[column].astype(float)
    frame.loc[0,column]=1.5
    frame.to_csv(cfg.data.market,index=False)
    with pytest.raises(ValueError,match='integers'):
        load_panel(cfg.data)

@pytest.mark.parametrize('fault',['missing','incomplete','future'])
def test_missing_mobility_is_not_observed_empty(cfg,fault):
    frame=pd.read_csv(cfg.data.mobility_snapshots)
    if fault=='missing': frame=frame.iloc[1:]
    elif fault=='incomplete': frame.loc[0,'complete']=False
    else: frame.loc[0,'available_at']='2030-01-01T00:00:00+07:00'
    frame.to_csv(cfg.data.mobility_snapshots,index=False)
    with pytest.raises(ValueError): load_panel(cfg.data)

def test_count_and_schema_no_geo(cfg):
    panel=load_panel(cfg.data)
    assert not hasattr(panel,'geo')
    assert not any('geo' in name for name in input_schema(cfg,panel))
    assert set(MAIN_VARIANTS)=={'lgbm_local','gru','gru_spatial','gru_mobility','duocast'}
    meta=json.loads(cfg.data.metadata.read_text())
    meta['demand_definition']='quotes'
    cfg.data.metadata.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='semantics'): load_panel(cfg.data)

def test_six_metrics_use_log1p_counts_and_log_ratio(cfg):
    truth=np.array([[3.,1.],[0.,2.]])
    pred=np.array([[7.,1.],[0.,0.]])
    result=point_metrics(pred,truth,cfg.evaluation,cfg.train)
    delta=np.log1p(pred)-np.log1p(truth)
    ratio_delta=delta[:,0]-delta[:,1]
    assert result['demand_mae']==pytest.approx(2.)
    assert result['supply_mae']==pytest.approx(1.)
    assert result['log_d_mae']==pytest.approx(np.abs(delta[:,0]).mean())
    assert result['log_s_mae']==pytest.approx(np.abs(delta[:,1]).mean())
    assert result['log_ds_mae']==pytest.approx(np.abs(ratio_delta).mean())
    assert result['log_ds_rmse']==pytest.approx(np.sqrt(np.mean(ratio_delta**2)))
    assert set(FORECAST_METRICS)<=set(result)

def test_no_old_checkpoint_can_be_relabeled(tmp_path):
    path=tmp_path/'old.pt'
    torch.save({'contract_version':'geomobinet_smg_ds_h5_v1'},path)
    with pytest.raises(ValueError,match='checkpoints are rejected'): load_checkpoint(path)

def test_actual_duocast_checkpoint_to_response_to_milp(cfg):
    run_trial(cfg,'duocast',42)
    panel=load_panel(cfg.data)
    fixture=make_fitted_fixture(hex_count=panel.n_nodes)
    cutoff=panel.timestamps[-1].to_pydatetime()
    identity=change(fixture.identity,dataset_id=panel.metadata['dataset_id'],dataset_fingerprint=panel.fingerprint,
        cutoff_time=cutoff,target_time=cutoff+timedelta(minutes=5),feature_version=panel.metadata['feature_definition_version'])
    rows=tuple(change(row,available_at=cutoff,quote_available_at=cutoff,quote_window_start=cutoff,
        quote_window_end=identity.target_time,capacity=change(row.capacity,available_at=cutoff)) for row in fixture.operational.rows)
    ops=change(fixture.operational,identity=identity,rows=rows,pricing_graph_available_at=cutoff)
    provider=CheckpointForecastProvider(cfg,cfg.output_dir/'duocast'/'seed_42'/'best.pt',forecast_run_id='actual-forward')
    calls=[]
    def recorded(i):
        forecast=provider(i)
        calls.append(forecast)
        return forecast
    result=run_decision(identity=identity,operational=ops,response=fixture.response,
        policy=change(fixture.policy,br_min=0.),forecast_provider=recorded)
    assert result.result_status=='VALID',result.diagnostics
    assert len(calls)==1
    assert calls[0].forecast_model_id=='duocast'
    assert calls[0].parity_status=='TEST_ONLY_CHECKPOINT_VERIFIED'
    assert result.production_effective is False
    assert len(result.recommendations)==panel.n_nodes

def test_five_model_table_and_test_freeze(cfg):
    pytest.importorskip('lightgbm')
    assert tuple(cfg.variants)==MAIN_VARIANTS
    results=benchmark(cfg)
    assert len(results)==5
    table=report(cfg)
    assert {r['variant'] for r in table}==set(MAIN_VARIANTS)
    assert all(set(FORECAST_METRICS)<=set(r) for r in table)
    selected=select(cfg)
    assert selected['selected_variant'] in MAIN_VARIANTS
    result=finalize(cfg)
    assert len(result['trials'])==5
    table_file = cfg.output_dir/'forecast_test_comparison.csv'
    table = pd.read_csv(table_file)
    assert len(table) == 5 and 'Log D/S RMSE' in table
    assert (cfg.output_dir/'forecast_test_comparison.md').is_file()
    with pytest.raises(ValueError,match='already evaluated'): finalize(cfg)

def test_network_optimizer_imports_no_training_or_torch():
    import surge_ml.inferences.network_optimizer as optimizer
    tree=ast.parse(Path(optimizer.__file__).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert not any(x in (node.module or '') for x in ('torch','train','duocast'))

def test_reference_outside_response_support_is_invalid():
    fixture=make_fixture(hex_count=1)
    cell=fixture.response.cells[0]
    response=change(fixture.response,cells=(change(cell,support=change(cell.support,surge_min='1.3')),))
    result=fixture.run(response=response)
    assert result.result_status=='INVALID'
    assert not result.recommendations

def test_forecast_generation_after_service_start_is_valid():
    fixture=make_fixture()
    def generate(identity):
        return change(fixture.forecast,generated_at=datetime.now(timezone.utc))
    result=run_decision(identity=fixture.identity,operational=fixture.operational,
        response=fixture.response,policy=fixture.policy,forecast_provider=generate)
    assert result.result_status=='VALID',result.diagnostics

def test_response_fit_from_file(cfg,tmp_path):
    rows=synthetic_observations(n=120)
    source=tmp_path/'observations.json'
    source.write_text(json.dumps([r.model_dump(mode='json') for r in rows]))
    job=dict(input='observations.json',output='fitted/artifact.json',dataset_id='synthetic-cohorts',
        node_mapping_version='test-nodes',required_hex_ids=['test-hex-00'],artifact_version='fit-test-v1',
        split_time=rows[90].decision_time.isoformat(),fit_as_of=rows[-1].outcome_matured_at.isoformat(),
        fit=fit_config(replicas=1).model_dump(mode='json'))
    path=tmp_path/'response.yaml'
    path.write_text(yaml.safe_dump(job))
    report=fit_from_config(path)
    assert report['cells']==1 and report['production_eligible'] is False
    with pytest.raises(FileExistsError): fit_from_config(path)
