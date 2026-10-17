from __future__ import annotations
import pandas as pd
STEP = pd.Timedelta(minutes=5)

def timestamps(values, timezone: str):
    result = pd.to_datetime(values, errors="raise")
    if result.isna().any():
        raise ValueError("Timestamp columns cannot contain nulls")
    if isinstance(result, pd.Series):
        return result.dt.tz_localize(timezone) if result.dt.tz is None else result.dt.tz_convert(timezone)
    result = pd.DatetimeIndex(result)
    return result.tz_localize(timezone) if result.tz is None else result.tz_convert(timezone)
