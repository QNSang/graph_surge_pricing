"""Bộ điều khiển surge Pressure/Revision. Chỉ hậu xử lý, không tham gia huấn luyện; chỉ dùng cho demo/shadow."""

from __future__ import annotations

import numpy as np

from surge_ml.config import ControllerConfig


def dead_zone(value: np.ndarray, threshold: float) -> np.ndarray:
    """Bỏ phần độ lớn nằm trong `threshold`, giữ dấu phần còn lại."""
    value = np.asarray(value, dtype=np.float64)
    return np.sign(value) * np.maximum(np.abs(value) - threshold, 0.0)


def apply_surge_controller(
    log_q_local: np.ndarray,
    log_q_graph: np.ndarray,
    bidding: np.ndarray,
    cfg: ControllerConfig,
) -> dict[str, np.ndarray]:
    """Đổi cặp dự báo log-ratio và giá bidding hiện tại thành đề xuất surge có giới hạn; đầu vào sai thì trả REVIEW."""
    y_local, y_graph, bid = np.broadcast_arrays(
        np.asarray(log_q_local, dtype=np.float64),
        np.asarray(log_q_graph, dtype=np.float64),
        np.asarray(bidding, dtype=np.float64),
    )
    shape = y_local.shape
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        q_local = np.exp(y_local)
        q_graph = np.exp(y_graph)
        pressure = (q_graph - cfg.reference_q) / cfg.reference_q
        revision = np.expm1(y_graph - y_local)

    valid_bid = np.isfinite(bid) & (bid >= cfg.surge_min) & (bid <= cfg.surge_max)
    finite_forecast = np.isfinite(y_local) & np.isfinite(y_graph) & np.isfinite(q_local) & np.isfinite(q_graph)
    valid_forecast = finite_forecast & (q_local >= cfg.q_min) & (q_graph > 0)
    valid = valid_bid & valid_forecast

    pressure_dz = dead_zone(pressure, cfg.pressure_dead_zone)
    revision_dz = dead_zone(revision, cfg.revision_dead_zone)
    pressure_component = cfg.pressure_gain * pressure_dz
    revision_component = cfg.revision_gain * revision_dz
    score = pressure_component + revision_component

    requested = np.zeros(shape, dtype=np.float64)
    positive = valid & (pressure > cfg.pressure_dead_zone)
    negative = valid & (pressure < -cfg.pressure_dead_zone)
    requested[positive] = np.clip(score[positive], 0.0, cfg.max_requested_delta)
    requested[negative] = np.clip(score[negative], -cfg.max_requested_delta, 0.0)
    requested_capped = valid & (np.abs(score) > cfg.max_requested_delta) & (np.sign(score) == np.sign(pressure))

    final = np.full(shape, np.nan, dtype=np.float64)
    final[valid_bid] = bid[valid_bid]
    final[valid] = np.clip(bid[valid] + requested[valid], cfg.surge_min, cfg.surge_max)
    applied = np.full(shape, np.nan, dtype=np.float64)
    applied[valid_bid] = 0.0
    applied[valid] = final[valid] - bid[valid]
    global_capped = valid & ~np.isclose(applied, requested, atol=1e-12, rtol=0.0)

    status = np.full(shape, "HOLD", dtype=object)
    status[valid & (applied > 0)] = "INCREASE"
    status[valid & (applied < 0)] = "DECREASE"
    status[~valid] = "REVIEW"

    reason = np.full(shape, "PRESSURE_DEAD_ZONE", dtype=object)
    active_pressure = positive | negative
    reason[valid & active_pressure & np.isclose(requested, 0.0, atol=1e-12, rtol=0.0)] = "DIRECTION_BLOCKED"
    reason[valid & active_pressure & ~np.isclose(requested, 0.0, atol=1e-12, rtol=0.0)] = "PRESSURE_REVISION"
    reason[requested_capped] = "REQUEST_CAP"
    reason[global_capped] = "GLOBAL_CAP"
    reason[~finite_forecast] = "NONFINITE_FORECAST"
    reason[finite_forecast & (q_local < cfg.q_min)] = "LOCAL_BELOW_Q_MIN"
    reason[finite_forecast & ~(q_graph > 0)] = "INVALID_GRAPH_FORECAST"
    reason[~valid_bid] = "INVALID_BIDDING"

    # Diagnostics are NaN for invalid forecasts so consumers cannot mistake placeholders for signals.
    # ``np.where`` also supports zero-dimensional arrays used by single-node callers.
    pressure = np.where(valid_forecast, pressure, np.nan)
    revision = np.where(valid_forecast, revision, np.nan)
    pressure_dz = np.where(valid_forecast, pressure_dz, np.nan)
    revision_dz = np.where(valid_forecast, revision_dz, np.nan)
    pressure_component = np.where(valid_forecast, pressure_component, np.nan)
    revision_component = np.where(valid_forecast, revision_component, np.nan)
    score = np.where(valid_forecast, score, np.nan)

    return {
        "q_local": q_local,
        "q_graph": q_graph,
        "pressure": pressure,
        "revision": revision,
        "pressure_after_dead_zone": pressure_dz,
        "revision_after_dead_zone": revision_dz,
        "pressure_component": pressure_component,
        "revision_component": revision_component,
        "score": score,
        "delta_requested": requested,
        "delta_applied": applied,
        "bidding": bid.copy(),
        "final_surge": final,
        "status": status,
        "reason": reason,
        "requested_capped": requested_capped,
        "global_capped": global_capped,
        "valid": valid,
    }
