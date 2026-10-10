
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

import aiohttp

logger = logging.getLogger(__name__)


class MeterError(Exception):
    """Base class for every error raised by MeterClient."""


class AuthError(MeterError):
    """The device rejected the token (HTTP 401/403)."""


class DeviceUnavailable(MeterError):
    """The device is unreachable, not ready, or all retries failed."""


class DeviceProtocolError(MeterError):
    """The device answered in a way we don't understand."""


@dataclass(frozen=True)
class MeterStatus:
    serial: str
    firmware: str
    power_w: float
    energy_kwh: float
    uptime_s: int


_RETRY_DELAYS = (0.5, 1.0, 2.0)  # waits before retry 1, 2 and 3
_MAX_RETRY_AFTER = 10.0  # bonus: never wait longer than this for Retry-After
_TIMEOUT = aiohttp.ClientTimeout(total=5)  # 5 s total per request


def _is_number(value):
    """True for int/float, but not for booleans (bool is a subclass of int)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_energy_wh(value):
    """energy_wh is a digit string (new firmware) or, for firmware < 2.0,
    a plain JSON integer -- the support log says the app accepts both."""
    if isinstance(value, str):
        if not value.isascii() or not value.isdigit():
            raise DeviceProtocolError("energy_wh must be a string of digits")
        return int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeviceProtocolError(
            "energy_wh must be a digit string or a non-negative int"
        )
    return value


def _retry_after_seconds(value):
    
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.isdigit():
        return None
    return min(float(text), _MAX_RETRY_AFTER)


async def _read_json(resp):
    
    try:
        return json.loads(await resp.text())
    except ValueError as exc:  # includes json.JSONDecodeError
        raise DeviceProtocolError("response body is not valid JSON") from exc


def _parse_status(data):
    
    if not isinstance(data, dict):
        raise DeviceProtocolError("expected a JSON object")

   
    state = data.get("state")
    if state == "booting":
        raise DeviceUnavailable("device reports state 'booting'")
    if state != "ok":
        raise DeviceProtocolError(f"unknown device state: {state!r}")

    device = data.get("device")
    if not isinstance(device, dict):
        raise DeviceProtocolError("missing 'device' object")
    serial = device.get("serial")
    firmware = device.get("fw")
    if not isinstance(serial, str) or not isinstance(firmware, str):
        raise DeviceProtocolError("device.serial and device.fw must be strings")

    power_w = data.get("power_w")
    if not _is_number(power_w):
        raise DeviceProtocolError("power_w must be a number")
    # Note: negative power is PV feed-in -- passed through unchanged.

    energy_wh = _parse_energy_wh(data.get("energy_wh"))

    uptime_s = data.get("uptime_s")
    if isinstance(uptime_s, bool) or not isinstance(uptime_s, int):
        raise DeviceProtocolError("uptime_s must be an integer")

    return MeterStatus(
        serial=serial,
        firmware=firmware,
        power_w=float(power_w),
        energy_kwh=energy_wh / 1000.0,
        uptime_s=uptime_s,
    )


class MeterClient:
    def __init__(self, session: aiohttp.ClientSession, host: str, token: str, *,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._session = session
        self._host = host
        self._token = token
        self._sleep = sleep

    async def get_status(self) -> MeterStatus:
        url = f"http://{self._host}/api/v1/status"
        headers = {"X-Auth-Token": self._token}
        for attempt in range(4):  # first try + up to 3 retries
            delay = None
            try:
                async with self._session.get(
                    url, headers=headers, timeout=_TIMEOUT
                ) as resp:
                    if resp.status == 200:
                        return _parse_status(await _read_json(resp))
                    if resp.status in (401, 403):
                        raise AuthError(
                            f"device rejected the token (HTTP {resp.status})"
                        )
                    if resp.status == 503:
                        delay = _retry_after_seconds(
                            resp.headers.get("Retry-After")
                        )
                    else:
                        raise DeviceProtocolError(
                            f"unexpected HTTP status {resp.status}"
                        )
            except (asyncio.TimeoutError, aiohttp.ClientConnectionError):
                pass  # timeout / connection error: retry below
            if attempt == 3:
                break  # last attempt failed too: give up, don't wait again
            if delay is None:
                delay = _RETRY_DELAYS[attempt]
            logger.debug(
                "nt-b29c: retrying in %.3f s (attempt %d/4)", delay, attempt + 2
            )
            await self._sleep(delay)
        raise DeviceUnavailable(
            f"no usable answer from {self._host} after 4 attempts"
        )



TOOL_DEFINITION = {
    "name": "get_meter_status",
    "description": (
        "Read the current status of the smart meter: serial number, "
        "firmware version, instantaneous power in watts (negative means "
        "PV feed-in), cumulative energy in kWh, and uptime in seconds."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


async def handle_tool_call(client, name, arguments) -> dict:
    """Run one tool call. Never raises."""
    if name != TOOL_DEFINITION["name"]:
        return {"error": "unknown_tool"}
    try:
        status = await client.get_status()
    except MeterError as exc:
        return {"error": type(exc).__name__}
    return asdict(status)
