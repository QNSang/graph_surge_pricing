"""Numba simulation kernel: drivers, matching, cancellation, repositioning, snapshots, base surge.

Time unit is minutes since the start of the burn-in day. One tick = 1 minute, one window = 5 ticks.
All state lives in the `State` namedtuple of arrays (scalars in the small `cnt` array), so every
helper is a plain cache-able njit function.
"""
from collections import namedtuple

import numpy as np
from numba import njit

# --- parameter vector layout ------------------------------------------------
(P_INTRA_PROB, P_PRICE, P_PAT_MEAN, P_PAT_MAX, P_PC_BASE, P_PC_PER, P_SPD_PEAK, P_SPD_OFF,
 P_ROAD, P_FIXED, P_SIGMA, P_INTRA_FLOOR, P_PK_SAME_F, P_PK_SAME_E, P_PK_NB_F, P_PK_NB_E,
 P_REPO_PROB, P_REPO_POW, P_REPO_MIN, P_REPO_IDLE, P_SHIFT_LOGMED, P_SHIFT_SIG, P_MIN_SESS,
 P_SG_GAIN, P_SG_EMA, P_SG_MIN, P_SG_MAX, P_SG_STEP, P_ETA_SAME_F, P_ETA_SAME_E, P_ETA1_F,
 P_ETA1_E, P_ETA2_F, P_ETA2_E, P_ETA_FAR, P_RAIN_SPD, P_RAIN_ETA, P_DISP_LO, P_DISP_HI,
 P_INTRA_R, P_SG_DEAD, N_PARAMS) = range(42)

# cnt indices
C_ORDERS, C_PEND = 0, 1

STATE_FIELDS = [
    "adj", "adj_n", "hex_dist", "dkm", "home",
    "d_state", "d_hex", "d_release", "d_order", "d_cancel", "d_online_start", "d_shift",
    "d_idle_since", "d_move_to", "d_move_arr", "d_pos", "idle_list", "idle_cnt",
    "o_origin", "o_dest", "o_created", "o_est", "o_tau", "o_deadline", "o_accept", "o_pickup",
    "o_dropoff", "o_cancel", "pend", "cnt", "surge", "win_demand",
    "snap_demand", "snap_supply", "snap_wait", "snap_eta", "snap_surge", "stats",
    "scratch_i", "scratch_f", "cdf",
]
State = namedtuple("State", STATE_FIELDS)


def make_state(adj, adj_n, hex_dist, dkm, home, order_cap, n_windows):
    H = adj.shape[0]
    ND = home.shape[0]
    nan = np.nan
    return State(
        adj=adj.astype(np.int32), adj_n=adj_n.astype(np.int32), hex_dist=hex_dist.astype(np.int32),
        dkm=dkm.astype(np.float64), home=home.astype(np.int32),
        d_state=np.zeros(ND, np.int8), d_hex=home.astype(np.int32).copy(),
        d_release=np.zeros(ND), d_order=np.full(ND, -1, np.int64), d_cancel=np.zeros(ND, np.int8),
        d_online_start=np.zeros(ND), d_shift=np.zeros(ND), d_idle_since=np.zeros(ND),
        d_move_to=np.full(ND, -1, np.int32), d_move_arr=np.zeros(ND), d_pos=np.zeros(ND, np.int32),
        idle_list=np.zeros((H, ND), np.int32), idle_cnt=np.zeros(H, np.int64),
        o_origin=np.zeros(order_cap, np.int32), o_dest=np.zeros(order_cap, np.int32),
        o_created=np.zeros(order_cap), o_est=np.zeros(order_cap), o_tau=np.zeros(order_cap),
        o_deadline=np.zeros(order_cap), o_accept=np.full(order_cap, nan), o_pickup=np.full(order_cap, nan),
        o_dropoff=np.full(order_cap, nan), o_cancel=np.full(order_cap, nan),
        pend=np.zeros(order_cap, np.int64), cnt=np.zeros(4, np.int64),
        surge=np.ones(H), win_demand=np.zeros(H, np.int64),
        snap_demand=np.zeros((n_windows, H), np.int32), snap_supply=np.zeros((n_windows, H), np.int32),
        snap_wait=np.zeros((n_windows, H), np.int32), snap_eta=np.zeros((n_windows, H)),
        snap_surge=np.zeros((n_windows, H)), stats=np.zeros((n_windows, 4)),
        scratch_i=np.zeros(ND, np.int64), scratch_f=np.zeros(ND), cdf=np.zeros((H, H)),
    )


@njit(cache=True)
def seed_rng(s):
    np.random.seed(s)


@njit(cache=True)
def _exp(mean):
    return -mean * np.log(1.0 - np.random.random())


@njit(cache=True)
def add_idle(S, d, h, t):
    c = S.idle_cnt[h]
    S.idle_list[h, c] = d
    S.d_pos[d] = c
    S.idle_cnt[h] = c + 1
    S.d_state[d] = 1
    S.d_hex[d] = h
    S.d_idle_since[d] = t
    S.d_move_to[d] = -1
    S.d_order[d] = -1


@njit(cache=True)
def remove_idle(S, d):
    h = S.d_hex[d]
    pos = S.d_pos[d]
    c = S.idle_cnt[h]
    last = S.idle_list[h, c - 1]
    S.idle_list[h, pos] = last
    S.d_pos[last] = pos
    S.idle_cnt[h] = c - 1


@njit(cache=True)
def try_match(S, P, oid, t):
    o = S.o_origin[oid]
    if S.idle_cnt[o] > 0:
        h = o
        pk = P[P_PK_SAME_F] + _exp(P[P_PK_SAME_E])
    else:
        best = -1
        bc = 0
        for q in range(S.adj_n[o]):
            j = S.adj[o, q]
            c = S.idle_cnt[j]
            if c > bc:
                bc = c
                best = j
        if best < 0:
            return False
        h = best
        pk = P[P_PK_NB_F] + _exp(P[P_PK_NB_E])
    r = np.random.randint(0, S.idle_cnt[h])
    d = S.idle_list[h, r]
    remove_idle(S, d)
    S.d_state[d] = 2
    S.d_order[d] = oid
    S.d_move_to[d] = -1
    S.o_accept[oid] = t
    pc = P[P_PC_BASE] + P[P_PC_PER] * max(0.0, pk - 4.0)
    if np.random.random() < pc:
        cts = t + max(np.random.random() * pk, 1.0 / 60.0)
        S.o_cancel[oid] = cts
        S.d_cancel[d] = 1
        S.d_release[d] = cts
    else:
        pick = t + pk
        S.o_pickup[oid] = pick
        S.o_dropoff[oid] = pick + S.o_tau[oid]
        S.d_cancel[d] = 0
        S.d_release[d] = pick
    return True


@njit(cache=True)
def process_releases(S, te):
    for d in range(S.d_state.shape[0]):
        s = S.d_state[d]
        if s == 2:
            if S.d_release[d] <= te:
                if S.d_cancel[d] == 1:
                    add_idle(S, d, S.d_hex[d], te)
                else:
                    S.d_state[d] = 3
                    S.d_release[d] = S.o_dropoff[S.d_order[d]]
        elif s == 3:
            if S.d_release[d] <= te:
                add_idle(S, d, S.o_dest[S.d_order[d]], te)
        elif s == 1:
            if S.d_move_to[d] >= 0 and S.d_move_arr[d] <= te:
                dest = S.d_move_to[d]
                remove_idle(S, d)
                add_idle(S, d, dest, te)


@njit(cache=True)
def shift_mgmt(S, P, te, target):
    ND = S.d_state.shape[0]
    n_on = 0
    for d in range(ND):
        if S.d_state[d] != 0:
            n_on += 1
    # drivers who finished their shift go home at the next idle moment
    for d in range(ND):
        if S.d_state[d] == 1 and te - S.d_online_start[d] >= S.d_shift[d]:
            remove_idle(S, d)
            S.d_state[d] = 0
            n_on -= 1
    if n_on < target:
        k = 0
        for d in range(ND):
            if S.d_state[d] == 0:
                S.scratch_i[k] = d
                k += 1
        need = min(target - n_on, k)
        for i in range(need):           # partial Fisher-Yates
            j = i + np.random.randint(0, k - i)
            tmp = S.scratch_i[i]
            S.scratch_i[i] = S.scratch_i[j]
            S.scratch_i[j] = tmp
            d = S.scratch_i[i]
            S.d_online_start[d] = te
            S.d_shift[d] = max(P[P_MIN_SESS], np.exp(P[P_SHIFT_LOGMED] + P[P_SHIFT_SIG] * np.random.randn()))
            add_idle(S, d, S.home[d], te)
    elif n_on > target:
        k = 0
        for d in range(ND):
            if S.d_state[d] == 1 and te - S.d_online_start[d] >= P[P_MIN_SESS]:
                S.scratch_i[k] = d
                S.scratch_f[k] = S.d_online_start[d]
                k += 1
        if k > 0:
            order = np.argsort(S.scratch_f[:k])     # longest online first
            drop = min(n_on - target, k)
            for i in range(drop):
                d = S.scratch_i[order[i]]
                remove_idle(S, d)
                S.d_state[d] = 0


@njit(cache=True)
def expire_pending(S, te):
    j = 0
    for q in range(S.cnt[C_PEND]):
        oid = S.pend[q]
        if S.o_deadline[oid] < te:
            S.o_cancel[oid] = S.o_deadline[oid]
        else:
            S.pend[j] = oid
            j += 1
    S.cnt[C_PEND] = j


@njit(cache=True)
def match_pending(S, P, te):
    j = 0
    for q in range(S.cnt[C_PEND]):
        oid = S.pend[q]
        if not try_match(S, P, oid, te):
            S.pend[j] = oid
            j += 1
    S.cnt[C_PEND] = j


@njit(cache=True)
def new_orders(S, P, k, intents_row, cdf, rain, vpeak):
    H = S.idle_cnt.shape[0]
    start = S.cnt[C_ORDERS]
    OC = S.o_origin.shape[0]
    for i in range(H):
        n = intents_row[i]
        if n == 0:
            continue
        p = np.exp(-P[P_PRICE] * (S.surge[i] - 1.0))
        keep = np.random.binomial(n, p)
        S.win_demand[i] += keep
        for _ in range(keep):
            oid = S.cnt[C_ORDERS]
            if oid >= OC:
                raise ValueError("order capacity exceeded")
            S.cnt[C_ORDERS] = oid + 1
            S.o_origin[oid] = i
            S.o_created[oid] = k + (1.0 + np.floor(np.random.random() * 60.0)) / 60.0
            v = P[P_SPD_PEAK] if vpeak else P[P_SPD_OFF]
            if rain > 0:
                v = v * P[P_RAIN_SPD]
            intra = np.random.random() < P[P_INTRA_PROB]
            if intra:
                j = i
                r = P[P_INTRA_R]
                a1 = 2 * np.pi * np.random.random()
                a2 = 2 * np.pi * np.random.random()
                r1 = r * np.sqrt(np.random.random())
                r2 = r * np.sqrt(np.random.random())
                dx = r1 * np.cos(a1) - r2 * np.cos(a2)
                dy = r1 * np.sin(a1) - r2 * np.sin(a2)
                dist = np.sqrt(dx * dx + dy * dy)
            else:
                u = 1.0 - np.random.random()
                j = H - 1
                for jj in range(H):
                    if cdf[i, jj] >= u:
                        j = jj
                        break
                dist = S.dkm[i, j]
            est = P[P_FIXED] + P[P_ROAD] * dist / v * 60.0
            if intra:
                est = max(est, P[P_INTRA_FLOOR])
            S.o_dest[oid] = j
            S.o_est[oid] = est
            S.o_tau[oid] = est * np.exp(P[P_SIGMA] * np.random.randn())
            pat = min(_exp(P[P_PAT_MEAN]), P[P_PAT_MAX])
            S.o_deadline[oid] = S.o_created[oid] + max(pat, 0.1)
    end = S.cnt[C_ORDERS]
    if end > start:
        order = np.argsort(S.o_created[start:end])
        for q in range(end - start):
            oid = start + order[q]
            t = S.o_created[oid] + (P[P_DISP_LO] + np.random.random() * (P[P_DISP_HI] - P[P_DISP_LO])) / 60.0
            if not try_match(S, P, oid, t):
                S.pend[S.cnt[C_PEND]] = oid
                S.cnt[C_PEND] += 1


@njit(cache=True)
def reposition(S, P, te):
    for d in range(S.d_state.shape[0]):
        if S.d_state[d] == 1 and S.d_move_to[d] < 0 and te - S.d_idle_since[d] >= P[P_REPO_IDLE]:
            if np.random.random() < P[P_REPO_PROB]:
                h = S.d_hex[d]
                total = 0.0
                for q in range(S.adj_n[h]):
                    total += S.surge[S.adj[h, q]] ** P[P_REPO_POW]
                if total > 0:
                    r = np.random.random() * total
                    acc = 0.0
                    pick = S.adj[h, 0]
                    for q in range(S.adj_n[h]):
                        j = S.adj[h, q]
                        acc += S.surge[j] ** P[P_REPO_POW]
                        if acc >= r:
                            pick = j
                            break
                    S.d_move_to[d] = pick
                    S.d_move_arr[d] = te + P[P_REPO_MIN]


@njit(cache=True)
def snapshot(S, P, w, rain):
    H = S.idle_cnt.shape[0]
    wait = np.zeros(H, np.int64)
    for q in range(S.cnt[C_PEND]):
        wait[S.o_origin[S.pend[q]]] += 1
    eta_mult = P[P_RAIN_ETA] if rain > 0 else 1.0
    for i in range(H):
        sup = S.idle_cnt[i]
        dem = S.win_demand[i]
        S.snap_demand[w, i] = dem
        S.snap_supply[w, i] = sup
        S.snap_wait[w, i] = wait[i]
        # ETA to nearest idle driver (spec 4.8)
        nearest = 99
        for j in range(H):
            if S.idle_cnt[j] > 0 and S.hex_dist[i, j] < nearest:
                nearest = S.hex_dist[i, j]
        if nearest == 0:
            eta = P[P_ETA_SAME_F] + _exp(P[P_ETA_SAME_E])
        elif nearest == 1:
            eta = P[P_ETA1_F] + _exp(P[P_ETA1_E])
        elif nearest == 2:
            eta = P[P_ETA2_F] + _exp(P[P_ETA2_E])
        else:
            eta = P[P_ETA_FAR]
        S.snap_eta[w, i] = eta * eta_mult * 60.0
        # base surge (spec 4.9)
        r = np.log((dem + wait[i] + 1.0) / (sup + 1.0))
        raw = min(max(1.0 + P[P_SG_GAIN] * max(0.0, r - P[P_SG_DEAD]), P[P_SG_MIN]), P[P_SG_MAX])
        s = (1.0 - P[P_SG_EMA]) * raw + P[P_SG_EMA] * S.surge[i]
        s = np.round(np.round(s / P[P_SG_STEP]) * P[P_SG_STEP], 2)
        s = min(max(s, P[P_SG_MIN]), P[P_SG_MAX])
        S.surge[i] = s
        S.snap_surge[w, i] = s
        S.win_demand[i] = 0


@njit(cache=True)
def build_cdf(S, A_row, L_row):
    H = S.idle_cnt.shape[0]
    for i in range(H):
        tot = 0.0
        for j in range(H):
            wt = 0.0
            if j != i:
                wt = A_row[j] * np.exp(-S.dkm[i, j] / L_row[i])
            S.cdf[i, j] = wt
            tot += wt
        acc = 0.0
        for j in range(H):
            acc += S.cdf[i, j] / tot
            S.cdf[i, j] = acc
        S.cdf[i, H - 1] = 1.0


@njit(cache=True)
def run_windows(S, P, w0, w1, intents, A, L, rain, vpeak, target):
    """Simulate windows [w0, w1). Window w covers ticks 5w .. 5w+4; its snapshot is stamped at 5w+5 min."""
    for w in range(w0, w1):
        build_cdf(S, A[w], L[w])
        for m in range(5):
            k = w * 5 + m
            te = k + 1.0
            process_releases(S, te)
            shift_mgmt(S, P, te, target[k])
            expire_pending(S, te)
            match_pending(S, P, te)
            new_orders(S, P, k, intents[k], S.cdf, rain[k], vpeak[k])
            n_on = 0
            n_idle = 0
            n2 = 0
            n3 = 0
            for d in range(S.d_state.shape[0]):
                s = S.d_state[d]
                if s != 0:
                    n_on += 1
                if s == 1:
                    n_idle += 1
                elif s == 2:
                    n2 += 1
                elif s == 3:
                    n3 += 1
            S.stats[w, 0] += n_on
            S.stats[w, 1] += n_idle
            S.stats[w, 2] += n2
            S.stats[w, 3] += n3
        reposition(S, P, w * 5 + 5.0)
        snapshot(S, P, w, rain[w * 5 + 4])


@njit(cache=True)
def finalize(S):
    """Orders still waiting at the end of the horizon cancel at their patience deadline."""
    for q in range(S.cnt[C_PEND]):
        oid = S.pend[q]
        S.o_cancel[oid] = S.o_deadline[oid]
    S.cnt[C_PEND] = 0
