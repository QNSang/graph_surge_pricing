"""CS-02/07: capacity in rides/horizon, never an alias for idle driver stock."""
from __future__ import annotations
import math
from ..contracts import CapacitySource
from ..errors import require


def capacity_value(supply: float, source: CapacitySource) -> float:
    source = CapacitySource.model_validate(source)
    require(math.isfinite(supply) and supply >= 0, "INPUT_INVALID", "Invalid eligible-idle supply")
    if source.method == "DIRECT":
        value = source.direct_capacity
    else:
        eta_minutes = source.eta / 60.0 if source.eta_unit == "seconds" else source.eta
        horizon = float(source.horizon_minutes)
        value = supply * source.rides_per_driver_hour * (horizon / 60.0)
        value *= min(1.0, horizon / max(eta_minutes, horizon))
    require(value is not None and math.isfinite(value) and value >= 0,
            "INPUT_INVALID", "Capacity must be finite rides per five-minute horizon")
    return float(value)
