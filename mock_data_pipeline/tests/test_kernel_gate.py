"""Release gate: a hex under pressure may not lend drivers to neighbours, but serves its own requests."""
import numpy as np

from surge_mock import kernel as K


def _state(idle_origin: int, idle_neighbour: int):
    adj = np.array([[1, -1], [0, -1]], np.int32)
    s = K.make_state(adj, np.array([1, 1]), np.zeros((2, 2)), np.ones((2, 2)), np.zeros(4, np.int32), 4, 1)
    for h, n in ((0, idle_origin), (1, idle_neighbour)):
        s.idle_cnt[h] = n
    s.o_origin[0] = 0
    s.o_deadline[0] = 1.0
    s.o_accept[0] = np.nan
    s.o_cancel[0] = np.nan
    return s


def _params():
    p = np.zeros(K.N_PARAMS)
    p[K.P_GATE_THETA], p[K.P_GATE_FLOOR] = 1.0, 0.2
    return p


def test_neighbour_gate_blocks_release_under_pressure():
    s = _state(0, 1)
    s.win_demand[1] = 50  # neighbour hex is saturated
    assert not K._can_release(s, _params(), 1)


def test_origin_hex_is_exempt_from_gate():
    s = _state(1, 0)
    s.win_demand[0] = 50  # origin is saturated
    s.idle_list[0, 0], s.d_state[0], s.d_hex[0] = 0, 1, 0
    assert not K._can_release(s, _params(), 0)  # would refuse to lend to a neighbour ...
    assert K.try_match(s, _params(), 0, 0.5)    # ... yet still serves its own request
    assert s.o_driver[0] == 0
