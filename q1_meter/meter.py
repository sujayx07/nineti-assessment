
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

METER_SPEC_REV = "nt-7f3a"

_BERLIN = ZoneInfo("Europe/Berlin")
_MAX_POWER_W = 20000.0  


def _parse_ts(ts):
   
    if not isinstance(ts, str):
        return None
    text = ts.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt


def _energy_wh(reading):

    if "energy_kwh" in reading:
        value = reading["energy_kwh"]
        if isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return float(value) * 1000.0
    if "energy" in reading:
        value = reading["energy"]
        if not isinstance(value, str):
            return None
        if not re.fullmatch(r"[0-9]+", value):
            return None
        return float(int(value))
    return None


def daily_consumption_kwh(readings: list) -> dict[str, float]:
    
    by_instant = {}
    for reading in readings:
        if not isinstance(reading, dict):
            continue
        dt = _parse_ts(reading.get("ts"))
        wh = _energy_wh(reading)
        if dt is None or wh is None:
            continue
        by_instant[dt] = (dt, wh)

    if len(by_instant) < 2:
        return {}

  
    ordered = [by_instant[key] for key in sorted(by_instant)]

   
    per_day_wh = {}
    prev_dt, prev_wh = ordered[0]
    for cur_dt, cur_wh in ordered[1:]:
        delta_wh = cur_wh - prev_wh
        if delta_wh < 0:
        
            delta_wh = cur_wh
        hours = (cur_dt - prev_dt).total_seconds() / 3600.0
        if delta_wh / hours > _MAX_POWER_W:
            continue  
        day = cur_dt.astimezone(_BERLIN).date().isoformat()
        per_day_wh[day] = per_day_wh.get(day, 0.0) + delta_wh
        prev_dt, prev_wh = cur_dt, cur_wh

   
    return {day: round(per_day_wh[day] / 1000.0, 3) for day in sorted(per_day_wh)}
