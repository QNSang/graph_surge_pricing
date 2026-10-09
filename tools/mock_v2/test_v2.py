"""Regression tests against the actual H3/Numba generator and feature code."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'mock_data_pipeline'))
sys.path.insert(0,str(ROOT/'tools'/'mock_v2'))
from run import simulate, configuration
from surge_mock import kernel as K
from surge_mock.feature_v2 import (ns,points,intervals,inbound_counts,indexed_orders,
    build_nodes,asof_test,edge_block,NODE_COLS,EDGE_COLS,I,MINUTE,STEP)
from surge_mock.dataset_v2 import censor_orders

@pytest.fixture(scope='module')
def actual():
    return simulate(3,777,'fixed_baseline')


def test_30_day_contract():
    c=configuration(30,42)
    assert c.n_days==30
    assert c.split=={'train':[1,21],'val':[22,25],'test':[26,30]}
    assert len(NODE_COLS)==40 and len(EDGE_COLS)==10


def test_actual_generator_integrity(actual):
    checks=actual[5]
    assert all(checks.values()), checks


def test_intra_radius_actual_variation(actual):
    m=actual[6]
    assert m['intra_estimate_unique'] > 100
    assert m['intra_estimate_floor_share'] < .2


def test_cutoff_censors_each_event_independently(actual):
    o=actual[4]['orders']
    picked=o[o.pickup_ts.notna() & o.dropoff_ts.notna()].iloc[0]
    cutoff=picked.pickup_ts+pd.Timedelta(seconds=1)
    past=censor_orders(o,cutoff)
    row=past.set_index('order_id').loc[picked.order_id]
    assert pd.notna(row.pickup_ts) and pd.isna(row.dropoff_ts)
    assert (past.created_ts<=cutoff).all()


def test_right_closed_midnight_and_timestamp_units():
    times=ns(pd.date_range('2026-01-05',periods=3,freq='5min'))
    event=ns(pd.to_datetime(['2026-01-04 23:59:59','2026-01-05 00:00:00','2026-01-05 00:00:01']))
    assert points(times,event,np.zeros(3,dtype=int),1).ravel().tolist()==[2,1,0]
    assert (np.diff(times)==STEP).all()


def test_interval_bounds_are_half_open():
    times=np.array([0,5,10,15],dtype=np.int64)*MINUTE
    out=intervals(times,np.array([5*MINUTE]),np.array([10*MINUTE]),np.array([0]),1)
    assert out.ravel().tolist()==[0,1,0,0]


def test_open_trip_contributes_to_inbound():
    origin='a';destination='b'
    frame=pd.DataFrame({'origin_hex':[origin],'dest_hex':[destination],
        'created_ts':pd.to_datetime(['2026-01-05 00:00:00']),
        'accepted_ts':pd.to_datetime(['2026-01-05 00:01:00']),
        'pickup_ts':pd.to_datetime(['2026-01-05 00:02:00']),
        'dropoff_ts':pd.to_datetime([None]),'cancel_ts':pd.to_datetime([None]),
        'est_trip_duration_min':[10.]})
    d=indexed_orders(frame,['a','b'])
    counts=inbound_counts(ns(pd.to_datetime(['2026-01-05 00:05:00','2026-01-05 00:10:00'])),d,2)
    assert counts[1][0,1]==1 and counts[0][1,1]==1


def test_acceptance_checks_deadline_and_readiness():
    S=K.make_state(np.array([[1],[0]]),np.array([1,1]),np.array([[0,1],[1,0]]),np.ones((2,2)),np.array([0]),10,2)
    P=np.zeros(K.N_PARAMS)
    S.o_created[0]=1;S.o_ready[0]=2;S.o_deadline[0]=3
    K.add_idle(S,0,0,0.)
    assert not K.try_match(S,P,0,1.5)
    assert not K.try_match(S,P,0,3.1)
    assert S.idle_cnt[0]==1 and S.o_driver[0]==-1


def test_reposition_not_dispatchable():
    S=K.make_state(np.array([[1],[0]]),np.array([1,1]),np.array([[0,1],[1,0]]),np.ones((2,2)),np.array([0]),10,2)
    P=np.zeros(K.N_PARAMS);P[K.P_REPO_PROB]=1;P[K.P_REPO_MIN]=8;P[K.P_REPO_POW]=1
    K.add_idle(S,0,0,0.)
    K.reposition(S,P,5.)
    assert S.d_state[0]==4 and S.idle_cnt.sum()==0
    K.process_releases(S,12.9)
    assert S.idle_cnt.sum()==0
    K.process_releases(S,13.)
    assert S.d_state[0]==1 and S.idle_cnt[1]==1


def test_features_are_finite_and_asof_safe(actual):
    geo,tables=actual[1],actual[4]
    times,x,support,d=build_nodes(tables,geo)
    assert x.shape==(4*288,61,40)
    assert np.isfinite(x).all()
    assert (x[:,:,I['effective_supply_t']]>=x[:,:,I['idle_supply_t']]).all()
    assert ((x[:,:,I['match_rate_matured_15m']]>=0)&(x[:,:,I['match_rate_matured_15m']]<=1)).all()
    checks=asof_test(tables,geo,times,x,d)
    assert all(checks.values()),checks
    block=edge_block(times[-48:],d,geo)
    assert np.array_equal(block[0].sum(2),x[-48:,:,I['demand_5m']])
    assert np.allclose(block[4].sum(1),x[-48:,:,I['arriving_trip_count_eta_0_5_t']])
    assert np.allclose(block[6].sum(2),1.)


def test_missing_grid_is_not_zero_filled(actual):
    tables=dict(actual[4]);tables['snap']=tables['snap'].iloc[1:]
    with pytest.raises(ValueError,match='Incomplete'):
        build_nodes(tables,actual[1])
