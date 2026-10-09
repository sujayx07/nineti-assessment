"""Q1: daily energy consumption from raw cumulative meter readings.

Takes a messy batch of cumulative counter readings and returns how much
energy (in kWh) was consumed on each calendar day, in Europe/Berlin time.

Do NOT rename daily_consumption_kwh or METER_SPEC_REV: the grader
imports them by these exact names.
"""

import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

METER_SPEC_REV = "nt-7f3a"

_BERLIN = ZoneInfo("Europe/Berlin")
_MAX_POWER_W = 20000.0  # glitch filter: anything above this is discarded


def _parse_ts(ts):
    """Return an aware datetime for a valid ts string, else None.

    A valid ts is an ISO-8601 string that carries a UTC offset
    ("+01:00", "+00:00" or "Z"). Naive timestamps are invalid.
    """
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
    """Return the counter value in Wh (float), or None if it is invalid.

    Firmware >= 2.0 sends "energy_kwh" (a number in kWh) and wins when both
    keys are present. Older firmware sends "energy" (a digit string in Wh).
    """
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
    # 1. Validate every reading; skip invalid ones silently. Dedupe by
    #    instant: aware datetimes compare/hash by instant, so two readings
    #    written with different UTC offsets still collide -- and because
    #    later input overwrites earlier input, the LAST one wins.
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

    # 2. Process the surviving readings in chronological order.
    ordered = [by_instant[key] for key in sorted(by_instant)]

    # 3. Walk consecutive pairs, totalling consumption per day (in Wh).
    #    `prev_*` always holds the last ACCEPTED reading: a glitch is
    #    discarded without moving it.
    per_day_wh = {}
    prev_dt, prev_wh = ordered[0]
    for cur_dt, cur_wh in ordered[1:]:
        delta_wh = cur_wh - prev_wh
        if delta_wh < 0:
            # Counter reset: the device rebooted and restarted from 0.
            delta_wh = cur_wh
        hours = (cur_dt - prev_dt).total_seconds() / 3600.0
        if delta_wh / hours > _MAX_POWER_W:
            continue  # glitch: discard this reading completely
        day = cur_dt.astimezone(_BERLIN).date().isoformat()
        per_day_wh[day] = per_day_wh.get(day, 0.0) + delta_wh
        prev_dt, prev_wh = cur_dt, cur_wh

    # 4. Convert to kWh, round to 3 decimals, ascending dates.
    # NOTE: use per_day_wh[day] here, not the loop variable `wh` left over
    # from validation above -- that one holds the last reading's raw value.
    return {day: round(per_day_wh[day] / 1000.0, 3) for day in sorted(per_day_wh)}
