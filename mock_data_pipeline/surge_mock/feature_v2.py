"""Point-in-time 40-node/10-edge feature contract for mock_v2.

Only observed orders, snapshots, weather and geography enter this module.
No oracle flags, driver audit, future actual duration, or training labels are inputs.
Counts and physical units are exported unscaled; normalization is fit on train only.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

VERSION = 'hex40_edge10_v2.1'
NODE_COLS = [
    'demand_5m','idle_supply_t','backlog_t','eta_sec_t','local_pressure_log_t',
    'demand_sum_15m','demand_mean_60m','demand_std_60m','demand_momentum_15m',
    'idle_supply_mean_15m','idle_supply_momentum_15m','match_rate_matured_15m',
    'cancel_rate_matured_15m','pickup_wait_p90_30m','current_surge_t','surge_delta_15m',
    'rain_intensity_t','hour_sin','hour_cos','dow_sin','dow_cos','is_weekend',
    'zone_airport','zone_cbd','zone_office','zone_residential','zone_suburb','zone_venue','ring',
    'effective_supply_t','arriving_trip_count_eta_0_5_t','arriving_trip_count_eta_5_10_t',
    'arriving_trip_count_eta_10_15_t','completed_inflow_15m','pickup_outflow_15m',
    'neighbor_demand_mean_t','neighbor_idle_supply_mean_t','neighbor_pressure_mean_t',
    'od_destination_entropy_30m','od_support_30m']
EDGE_COLS = ['edge_is_adjacent','edge_is_od','distance_km','travel_time_est_min',
             'od_requests_5m','od_requests_30m','od_completed_15m','od_in_trip_count_t',
             'od_arrivals_eta_le5m_t','od_transition_prob_30m']
SUPPORT_COLS = ['mature_request_count_15m','matched_within_5m_count','cancelled_within_5m_count',
                'pickup_wait_support_30m','history_steps_available']
I = {n:i for i,n in enumerate(NODE_COLS)}
STEP = 300_000_000_000
MINUTE = 60_000_000_000
NAT = np.iinfo(np.int64).min
FAR = np.int64(2**62)


def ns(x):
    return np.asarray(pd.to_datetime(x).astype('datetime64[ns]')).astype(np.int64)


def safe_events(x):
    a = ns(x)
    return np.where(a == NAT, FAR, a)


def points(times, events, cols, n, weight=None):
    k = np.searchsorted(times, events, side='left')
    valid = (events > times[0]-STEP) & (events <= times[-1]) & (k < len(times))
    w = None if weight is None else np.asarray(weight)[valid]
    return np.bincount(k[valid]*n+cols[valid], weights=w, minlength=len(times)*n).reshape(len(times), n).astype(float)


def intervals(times, lo, hi, cols, n):
    # A row is active at timestamp t exactly when lo <= t < hi.
    a = np.searchsorted(times, lo, side='left').clip(0, len(times))
    b = np.searchsorted(times, hi, side='left').clip(0, len(times))
    valid = (b > a) & (lo < FAR)
    size = (len(times)+1)*n
    delta = np.bincount(a[valid]*n+cols[valid], minlength=size) - np.bincount(b[valid]*n+cols[valid], minlength=size)
    return np.cumsum(delta.reshape(len(times)+1,n), axis=0)[:-1].astype(float)


def roll(x, steps):
    p = np.concatenate([np.zeros_like(x[:1]), np.cumsum(x, axis=0)], axis=0)
    return p[1:] - p[np.maximum(np.arange(len(x))+1-steps, 0)]


def lag(x, steps):
    out = np.zeros_like(x)
    out[steps:] = x[:-steps]
    return out


def indexed_orders(o, cells):
    mapping = {h:i for i,h in enumerate(cells)}
    return {'origin': o.origin_hex.map(mapping).to_numpy(np.int64),
            'dest': o.dest_hex.map(mapping).to_numpy(np.int64),
            'created': safe_events(o.created_ts), 'accepted': safe_events(o.accepted_ts),
            'pickup': safe_events(o.pickup_ts), 'dropoff': safe_events(o.dropoff_ts),
            'cancel': safe_events(o.cancel_ts),
            'duration': np.rint(o.est_trip_duration_min.to_numpy()*MINUTE).astype(np.int64)}


def inbound_counts(times, d, n, columns=None):
    dest = d['dest'] if columns is None else columns
    p, finish = d['pickup'], np.minimum(d['dropoff'], d['cancel'])
    # Addition guarded so NaT/sentinel can never wrap.
    est_end = np.where(p < FAR, np.minimum(p, FAR-10**15)+d['duration'], FAR)
    out = []
    for j, minutes in enumerate([5,10,15]):
        lo = np.maximum(p, est_end-minutes*MINUTE)
        hi = finish if j == 0 else np.minimum(finish, est_end-(minutes-5)*MINUTE)
        out.append(intervals(times, lo, hi, dest, n))
    return out


def build_nodes(tables, geo):
    s, o = tables['snap'], tables['orders']
    times = ns(pd.DatetimeIndex(s.ts.unique()).sort_values())
    cells = list(geo.cells)
    index = pd.MultiIndex.from_product([pd.to_datetime(times), cells], names=['ts','hex_id'])
    aligned = s.set_index(['ts','hex_id']).reindex(index)
    if aligned[['demand','supply','eta_sec','surge_multiplier']].isna().any().any():
        raise ValueError('Incomplete/invalid grid; refusing zero-fill')
    T, N = len(times),len(cells)
    D,S,ETA,SURGE = [aligned[c].to_numpy().reshape(T,N) for c in ['demand','supply','eta_sec','surge_multiplier']]
    d = indexed_orders(o,cells)
    incoming = inbound_counts(times,d,N)
    seff = S+incoming[0]+.5*incoming[1]+.2*incoming[2]
    backlog = intervals(times, d['created'], np.minimum(d['accepted'], d['cancel']), d['origin'], N)
    done = points(times,d['dropoff'],d['dest'],N)
    pickups = points(times,d['pickup'],d['origin'],N)
    mature_at = d['created']+5*MINUTE
    eligible = points(times,mature_at,d['origin'],N)
    hit = d['accepted'] <= mature_at
    cancelled = d['cancel'] <= mature_at
    matched = points(times,mature_at[hit],d['origin'][hit],N)
    cancels = points(times,mature_at[cancelled],d['origin'][cancelled],N)
    denom,matchn,canceln = roll(eligible,3),roll(matched,3),roll(cancels,3)
    # Fixed Beta(1,1) shrinkage; no outcome-dependent fitted prior.
    mr,cr = (matchn+1)/(denom+2),(canceln+1)/(denom+2)
    q90 = np.full((T,N),np.nan)
    qsupport = roll(pickups,6)
    # Time-based rolling quantile, with snapshot markers ordered AFTER same-time events.
    for h in range(N):
        select = (d['origin']==h) & (d['pickup'] < FAR)
        ev = pd.DataFrame({'time':pd.to_datetime(d['pickup'][select]),
                           'wait':(d['pickup'][select]-d['created'][select])/1e9, 'marker':False})
        marks = pd.DataFrame({'time':pd.to_datetime(times),'wait':np.nan,'marker':True})
        frame = pd.concat([ev,marks],ignore_index=True).sort_values(['time','marker'],kind='stable')
        quant = frame.set_index('time')['wait'].rolling('30min',closed='right').quantile(.9).to_numpy()
        q90[:,h] = quant[frame.marker.to_numpy()]
    # Current observed ETA fallback is explicit; support column records unobserved quantiles.
    q90 = np.where(np.isfinite(q90),q90,ETA)
    dyn = np.zeros((T,N,40),np.float32)
    put = lambda name,val: dyn.__setitem__((slice(None),slice(None),I[name]),val)
    count12 = np.minimum(np.arange(T)+1,12)[:,None]
    avg = roll(D,12)/count12
    std = np.sqrt(np.maximum(roll(D*D,12)/count12-avg*avg,0))
    pressure = np.log1p(D)-np.log1p(S)
    values = {'demand_5m':D,'idle_supply_t':S,'backlog_t':backlog,'eta_sec_t':ETA,
        'local_pressure_log_t':pressure,'demand_sum_15m':roll(D,3),'demand_mean_60m':avg,'demand_std_60m':std,
        'demand_momentum_15m':roll(D,3)-lag(roll(D,3),3),
        'idle_supply_mean_15m':roll(S,3)/np.minimum(np.arange(T)+1,3)[:,None],
        'idle_supply_momentum_15m':S-lag(S,3),'match_rate_matured_15m':mr,'cancel_rate_matured_15m':cr,
        'pickup_wait_p90_30m':q90,'current_surge_t':SURGE,'surge_delta_15m':SURGE-lag(SURGE,3),
        'effective_supply_t':seff,'arriving_trip_count_eta_0_5_t':incoming[0],
        'arriving_trip_count_eta_5_10_t':incoming[1],'arriving_trip_count_eta_10_15_t':incoming[2],
        'completed_inflow_15m':roll(done,3),'pickup_outflow_15m':roll(pickups,3)}
    for k,v in values.items(): put(k,v)
    dates = pd.DatetimeIndex(pd.to_datetime(times))
    hour = dates.hour.to_numpy()+dates.minute.to_numpy()/60
    dow = dates.dayofweek.to_numpy()
    rain = tables['weather'].set_index('ts').rain_intensity.reindex(dates)
    if rain.isna().any(): raise ValueError('Missing weather; not silently filled as dry')
    for k,v in {'rain_intensity_t':rain.to_numpy(),'hour_sin':np.sin(2*np.pi*hour/24),
        'hour_cos':np.cos(2*np.pi*hour/24),'dow_sin':np.sin(2*np.pi*dow/7),
        'dow_cos':np.cos(2*np.pi*dow/7),'is_weekend':dow>=5}.items(): put(k,np.asarray(v)[:,None])
    zones = geo.static_table().zone.to_numpy()
    for zone in ['airport','cbd','office','residential','suburb','venue']: put('zone_'+zone,(zones==zone)[None,:])
    put('ring',geo.ring[None,:])
    adj = (geo.hex_dist==1).astype(float)
    degree = adj.sum(1).clip(min=1)
    for name,x in [('neighbor_demand_mean_t',D),('neighbor_idle_supply_mean_t',S),('neighbor_pressure_mean_t',pressure)]:
        put(name,(x@adj.T)/degree[None,:])
    support = np.stack([denom,matchn,canceln,qsupport,np.broadcast_to(np.minimum(np.arange(T)+1,12)[:,None],(T,N))],axis=-1).astype(np.float32)
    if not np.isfinite(dyn).all(): raise ValueError('Non-finite node feature')
    return times,dyn,support,d


def edge_block(times,d,geo):
    T,N = len(times),geo.n
    pair = d['origin']*N+d['dest']
    req = points(times,d['created'],pair,N*N).reshape(T,N,N)
    completed = points(times,d['dropoff'],pair,N*N).reshape(T,N,N)
    in_trip = intervals(times,d['pickup'],np.minimum(d['dropoff'],d['cancel']),pair,N*N).reshape(T,N,N)
    arrival5 = inbound_counts(times,d,N*N,pair)[0].reshape(T,N,N)
    good = (d['dropoff'] < FAR) & (d['pickup'] < FAR)
    elapsed = (d['dropoff'][good]-d['pickup'][good])/MINUTE
    elapsed_sum = points(times,d['dropoff'][good],pair[good],N*N,elapsed).reshape(T,N,N)
    req30,comp15,comp30 = roll(req,6),roll(completed,3),roll(completed,6)
    duration_sum30 = roll(elapsed_sum,6)
    # Fallback prior depends only on geometry/configured engineering assumption.
    prior = 2.+1.3*np.where(geo.dist_km>0,geo.dist_km,1.16)/28.*60
    travel = np.where(comp30>0,duration_sum30/np.maximum(comp30,1),prior[None,:,:])
    totals = req30.sum(axis=2)
    probs = (req30+.1)/(totals[:,:,None]+.1*N)
    p = req30/np.maximum(totals[:,:,None],1)
    entropy = -(p*np.log(np.maximum(p,1e-30))).sum(axis=2)
    return req,req30,comp15,in_trip,arrival5,travel,probs,entropy,totals


def asof_test(tables,geo,times,nodes,d):
    from .dataset_v2 import censor_orders
    checks = {}
    for fraction in [.25,.5,.75]:
        k = max(12,int(len(times)*fraction))
        cutoff = pd.Timestamp(times[k])
        partial = {'orders':censor_orders(tables['orders'],cutoff),
                   'snap':tables['snap'].loc[tables['snap'].ts<=cutoff],
                   'weather':tables['weather'].loc[tables['weather'].ts<=cutoff]}
        tt,xx,_,dd = build_nodes(partial,geo)
        # Network entropy/support are computed in edge export and compared separately.
        checks[f'node_prefix_{k}'] = bool(np.allclose(xx[-1,:,:38],nodes[k,:,:38],rtol=1e-6,atol=1e-5))
        sub = times[max(0,k-12):k+1]
        full = edge_block(sub,d,geo)
        past = edge_block(sub,dd,geo)
        checks[f'edge_prefix_{k}'] = all(np.allclose(a[-1],b[-1]) for a,b in zip(full,past))
    return checks


def export_features(out,cfg,geo,tables,log=print):
    out = Path(out)
    training = out/'training'
    training.mkdir()
    times,nodes,support,d = build_nodes(tables,geo)
    T,N = nodes.shape[:2]
    main = times > pd.Timestamp(cfg.start_date).value
    idx = np.flatnonzero(main)
    start = idx[0]
    nt = len(idx)
    assert nt == cfg.n_days*288 and N==61 and nodes.shape[-1]==40
    # Preflight point-in-time tests before exporting any target.
    log('checking point-in-time prefixes')
    tests = asof_test(tables,geo,times,nodes,d)
    if not all(tests.values()): raise AssertionError(tests)
    edge_day_paths=[]
    node_days=[]
    diagnostics=[]
    adj_src,adj_dst = np.where(geo.hex_dist==1)
    total_edges=0
    edge_sum=np.zeros(10)
    edge_sq=np.zeros(10)
    train_edges=0
    for day in range(cfg.n_days):
        lo=start+day*288
        hi=lo+288
        left=max(0,lo-12)
        block=edge_block(times[left:hi],d,geo)
        req,req30,comp15,intrip,a5,travel,prob,entropy,odsupport=block
        take=slice(lo-left,hi-left)
        nodes[lo:hi,:,I['od_destination_entropy_30m']]=entropy[take]
        nodes[lo:hi,:,I['od_support_30m']]=odsupport[take]
        if not np.array_equal(req[take].sum(2),nodes[lo:hi,:,I['demand_5m']]):
            raise AssertionError('Edge requests and local demand disagree')
        if not np.allclose(a5[take].sum(1),nodes[lo:hi,:,I['arriving_trip_count_eta_0_5_t']]):
            raise AssertionError('OD arrival buckets and node inbound disagree')
        attrs=[]; sources=[]; destinations=[]; ptr=[0]
        count=[]
        for k in range(lo-left,hi-left):
            osrc,odst=np.where((req30[k]+comp15[k]+intrip[k])>0)
            na,no=len(adj_src),len(osrc)
            sr=np.concatenate([adj_src,osrc]); ds=np.concatenate([adj_dst,odst])
            ea=np.zeros((na+no,10),np.float32)
            ea[:na,0]=1; ea[na:,1]=1
            ea[:,2]=geo.dist_km[sr,ds]
            ea[:,3]=travel[k,sr,ds]
            for col,ar in enumerate([req,req30,comp15,intrip,a5,prob],start=4):
                ea[na:,col]=ar[k,osrc,odst]
            if not np.isfinite(ea).all(): raise AssertionError('Invalid edge feature')
            attrs.append(ea);sources.append(sr.astype(np.int16));destinations.append(ds.astype(np.int16))
            ptr.append(ptr[-1]+len(sr));count.append(no)
        attr=np.concatenate(attrs);src=np.concatenate(sources);dst=np.concatenate(destinations)
        total_edges+=len(src)
        stamp=pd.Timestamp(times[lo]-STEP).strftime('%Y-%m-%d')
        path=out/'features'/'graph_edges_5min'/f'date={stamp}'
        path.mkdir(parents=True)
        edgeframe=pd.DataFrame(attr,columns=EDGE_COLS)
        edgeframe.insert(0,'dst_hex',np.asarray(geo.cells)[dst])
        edgeframe.insert(0,'src_hex',np.asarray(geo.cells)[src])
        edgeframe.insert(0,'ts',np.repeat(pd.to_datetime(times[lo:hi]),np.diff(ptr)))
        edgeframe.to_parquet(path/'part.parquet',index=False)
        arrpath=training/f'edges_day{day:02d}.npz'
        np.savez_compressed(arrpath,src=src,dst=dst,attr=attr,ptr=np.asarray(ptr,np.int64))
        edge_day_paths.append(arrpath)
        if cfg.split['train'][0]-1 <= day < cfg.split['train'][1]:
            edge_sum+=attr.sum(0,dtype=np.float64);edge_sq+=np.square(attr.astype(float)).sum(0);train_edges+=len(attr)
        npth=out/'features'/'hex_features_5min'/f'date={stamp}'
        npth.mkdir(parents=True)
        nf=pd.DataFrame(nodes[lo:hi].reshape(-1,40),columns=NODE_COLS)
        nf.insert(0,'hex_id',np.tile(geo.cells,288));nf.insert(0,'ts',np.repeat(pd.to_datetime(times[lo:hi]),N))
        for z,name in enumerate(SUPPORT_COLS): nf[name]=support[lo:hi,:,z].ravel()
        nf.to_parquet(npth/'part.parquet',index=False)
        diagnostics.append({'date':stamp,'od_edges_mean':float(np.mean(count)),
            'od_edges_min':int(np.min(count)),'od_edges_max':int(np.max(count)),
            'od_density_mean_including_self':float(np.mean(count)/N**2),
            'adjacency_edges_per_snapshot':len(adj_src),'all_relation_edges':len(attr)})
        log('features day',day+1,'/',cfg.n_days,'edges',len(attr))
        del block,edgeframe,nf,attrs,attr
    # Concatenate compact daily edge arrays into mmap-ready arrays.
    srcmap=np.lib.format.open_memmap(training/'edge_src.npy',mode='w+',dtype=np.int16,shape=(total_edges,))
    dstmap=np.lib.format.open_memmap(training/'edge_dst.npy',mode='w+',dtype=np.int16,shape=(total_edges,))
    attrmap=np.lib.format.open_memmap(training/'edge_attr.npy',mode='w+',dtype=np.float32,shape=(total_edges,10))
    globalptr=[0];offset=0
    for path in edge_day_paths:
        with np.load(path,allow_pickle=False) as blob:
            size=len(blob['src'])
            srcmap[offset:offset+size]=blob['src'];dstmap[offset:offset+size]=blob['dst'];attrmap[offset:offset+size]=blob['attr']
            globalptr.extend((blob['ptr'][1:]+offset).tolist());offset+=size
    srcmap.flush();dstmap.flush();attrmap.flush()
    del srcmap,dstmap,attrmap
    # Temporary files belong to THIS export and are redundant after successful concat.
    for path in edge_day_paths: path.unlink()
    np.save(training/'edge_ptr.npy',np.asarray(globalptr,np.int64))
    x=nodes[main]
    np.save(training/'node.npy',x)
    np.save(training/'feature_support.npy',support[main])
    np.save(training/'timestamps_ns.npy',times[main])
    b=np.log1p(x[:,:,I['demand_5m']].astype(float))-np.log1p(x[:,:,I['effective_supply_t']].astype(float))
    volume=x[:,:,I['demand_5m']]+x[:,:,I['effective_supply_t']]
    np.save(training/'baseline.npy',b.astype(np.float32));np.save(training/'volume.npy',volume.astype(np.float32))
    split=np.empty(nt,dtype=np.int8)
    samples=[]
    for sid,(name,bounds) in enumerate(cfg.split.items()):
        a,z=(bounds[0]-1)*288,bounds[1]*288
        split[a:z]=sid
        # Four input snapshots wholly inside split; 30min purge plus max horizon.
        for k in range(a+3,z-6-3): samples.append({'k':k,'ts':pd.Timestamp(times[main][k]),'split':name})
    pd.DataFrame(samples).to_parquet(training/'sample_index.parquet',index=False)
    target=np.full((nt,N,3),np.nan,np.float32)
    mask=np.zeros((nt,N,3),bool)
    for j,h in enumerate([1,2,3]):
        valid=split[:-h]==split[h:]
        ii=np.flatnonzero(valid)
        target[ii,:,j]=b[ii+h];mask[ii,:,j]=True
    np.save(training/'targets.npy',target);np.save(training/'target_mask.npy',mask)
    # Human-readable targets; ts is forecast creation time, never a feature timestamp at t+h.
    td=out/'targets';td.mkdir()
    for day in range(cfg.n_days):
        a,z=day*288,(day+1)*288
        frames=[]
        for j,h in enumerate([5,10,15]):
            frames.append(pd.DataFrame({'ts':np.repeat(pd.to_datetime(times[main][a:z]),N),
                'hex_id':np.tile(geo.cells,288),'horizon_min':h,'future_pressure':target[a:z,:,j].ravel(),
                'target_valid':mask[a:z,:,j].ravel()}))
        pd.concat(frames,ignore_index=True).to_parquet(td/f'day{day+1:02d}.parquet',index=False)
    train=x[split==0].reshape(-1,40).astype(float)
    node_mean=train.mean(0);node_std=train.std(0);node_std[node_std<1e-6]=1
    edge_mean=edge_sum/train_edges;edge_std=np.sqrt(np.maximum(edge_sq/train_edges-edge_mean**2,0));edge_std[edge_std<1e-6]=1
    np.savez(training/'normalization.npz',node_mean=node_mean,node_std=node_std,edge_mean=edge_mean,edge_std=edge_std)
    contract={'version':VERSION,'node_features':NODE_COLS,'edge_features':EDGE_COLS,'support_columns':SUPPORT_COLS,
        'node_dim':40,'edge_dim':10,'window':4,'horizons_min':[5,10,15],'epsilon':1.0,'purge_min':30,
        'target':'log((demand[t+h]+1)/(effective_supply[t+h]+1))',
        'rates':'Beta(1,1) shrinkage on requests created in (t-20min,t-5min]; outcomes within 5min of creation.',
        'pickup_wait_p90_30m':'seconds; pickups in (t-30min,t]; fallback current eta_sec when support is zero.',
        'supply_buckets':'pickup observed; no known dropoff/cancel yet; ETA from pickup+initial estimate. Overdue active trips remain in <=5 bucket.',
        'edges':'Separate adjacency and directed OD relations; OD active if requests in 30min, completions in15min, or in-flight trips. Self OD preserved.',
        'travel_prior':'2 + 1.3*centroid_distance/28*60 minutes; intra fallback 1.16km. Observed completed trip mean in trailing30min overrides prior.',
        'normalization':'z-score using train node/edge rows only; raw exports contain physical values.',
        'support_usage':'Stored for audit; not appended to the fixed 40-dimensional tensor.',
        'hex_ids':list(geo.cells)}
    (out/'feature_contract.json').write_text(json.dumps(contract,indent=2),encoding='utf-8')
    sample_frame=pd.DataFrame(samples)
    sk=sample_frame.k.to_numpy(np.int64)
    edge_payload=np.load(training/'edge_attr.npy',mmap_mode='r',allow_pickle=False)
    split_safe=all(np.all(split[sk]==split[sk+offset]) for offset in [-3,-2,-1,0,1,2,3])
    tests.update({'node_dim_40':x.shape[-1]==40,'edge_dim_10':edge_payload.shape==(total_edges,10),
                  'finite_node_tensor':bool(np.isfinite(x).all()),
                  'exact_30_day_grid':cfg.n_days==30 and nt==8640,
                  'split_samples_within_bounds':bool(split_safe),
                  'all_training_sample_targets_valid':bool(mask[sk].all()),
                  'finite_sample_targets':bool(np.isfinite(target[sk]).all()),
                  'finite_positive_normalization':bool(np.isfinite(node_mean).all() and np.isfinite(node_std).all()
                    and np.isfinite(edge_mean).all() and np.isfinite(edge_std).all()
                    and (node_std>0).all() and (edge_std>0).all()),
                  'edge_pointer_accounting':bool(len(globalptr)==nt+1 and globalptr[-1]==total_edges
                    and (np.diff(globalptr)>=0).all())})
    del edge_payload
    if not all(tests.values()):raise AssertionError(tests)
    (out/'reports'/'feature_validation.json').write_text(json.dumps(tests,indent=2),encoding='utf-8')
    pd.DataFrame(diagnostics).to_csv(out/'reports'/'graph_by_day.csv',index=False)
    # Content-derived fingerprint of all published tensor payloads; no path-only cache.
    fingerprints={}
    for path in sorted(training.iterdir()):
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for buf in iter(lambda:stream.read(4*1024**2),b''):h.update(buf)
        fingerprints[path.name]=h.hexdigest()
    (out/'training_sha256.json').write_text(json.dumps(fingerprints,indent=2),encoding='utf-8')
    fingerprint=hashlib.sha256(json.dumps(fingerprints,sort_keys=True).encode()).hexdigest()
    return {'feature_version':VERSION,'node_dim':40,'edge_dim':10,'tensor_shape':list(x.shape),
        'edge_rows':total_edges,'sample_counts':pd.DataFrame(samples).groupby('split').size().to_dict(),
        'feature_integrity_pass':all(tests.values()),'dataset_fingerprint':fingerprint,
        'feature_contract':'feature_contract.json','epsilon':1.0,'horizons_minutes':[5,10,15]}
