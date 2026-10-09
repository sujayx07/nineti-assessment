import asyncio
import logging

import aiohttp
import pytest
from aioresponses import aioresponses

from q2_client.client import (
    TOOL_DEFINITION,
    AuthError,
    DeviceProtocolError,
    DeviceUnavailable,
    MeterClient,
    MeterError,
    MeterStatus,
    handle_tool_call,
)

HOST = "192.168.1.50"
URL = f"http://{HOST}/api/v1/status"


class FakeSleep:

    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


def ok_payload(**overrides):
    body = {
        "device": {"serial": "SL-0042", "fw": "2.1.0"},
        "state": "ok",
        "power_w": 412.5,
        "energy_wh": "18234567",
        "uptime_s": 86400,
    }
    body.update(overrides)
    return body


def make_client(session, sleep):
    return MeterClient(session, HOST, "secret-token", sleep=sleep)


def request_count(m):
    key = next(iter(m.requests))
    return len(m.requests[key])


@pytest.mark.asyncio
async def test_success_maps_all_fields():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            status = await make_client(session, sleep).get_status()
    assert status == MeterStatus(
        serial="SL-0042",
        firmware="2.1.0",
        power_w=412.5,
        energy_kwh=18234.567,
        uptime_s=86400,
    )
    assert sleep.calls == []  # no retry needed


@pytest.mark.asyncio
async def test_auth_header_and_timeout_are_sent():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            await make_client(session, sleep).get_status()
    call = m.requests[next(iter(m.requests))][0]
    assert call.kwargs["headers"]["X-Auth-Token"] == "secret-token"
    assert call.kwargs["timeout"].total == 5


@pytest.mark.asyncio
async def test_negative_power_is_passed_through():
    # Negative power = PV feed-in; must not be rejected or clamped.
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload(power_w=-1830.0))
        async with aiohttp.ClientSession() as session:
            status = await make_client(session, sleep).get_status()
    assert status.power_w == -1830.0


@pytest.mark.asyncio
async def test_energy_wh_as_int_for_old_firmware():
    # Firmware < 2.0 sends energy_wh as a JSON integer, not a string.
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload(energy_wh=9123456))
        async with aiohttp.ClientSession() as session:
            status = await make_client(session, sleep).get_status()
    assert status.energy_kwh == 9123.456


@pytest.mark.asyncio
async def test_booting_raises_unavailable_without_retry():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload={"device": {"serial": "SL-0042", "fw": "2.2.0"},
                            "state": "booting"})
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceUnavailable):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 1
    assert sleep.calls == []


@pytest.mark.asyncio
async def test_unknown_state_raises_protocol_error():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload(state="confused"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceProtocolError):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 1
    assert sleep.calls == []


@pytest.mark.asyncio
async def test_401_raises_auth_error_without_retry():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=401)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AuthError):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 1
    assert sleep.calls == []


@pytest.mark.asyncio
async def test_403_raises_auth_error_without_retry():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=403)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(AuthError):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 1


@pytest.mark.asyncio
async def test_other_status_raises_protocol_error_without_retry():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=500)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceProtocolError):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 1
    assert sleep.calls == []


@pytest.mark.asyncio
async def test_503_then_success_retries_once():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=503)
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            status = await make_client(session, sleep).get_status()
    assert status.serial == "SL-0042"
    assert request_count(m) == 2
    assert sleep.calls == [0.5]


@pytest.mark.asyncio
async def test_timeout_then_success():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, exception=asyncio.TimeoutError("timed out"))
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            status = await make_client(session, sleep).get_status()
    assert status.serial == "SL-0042"
    assert sleep.calls == [0.5]


@pytest.mark.asyncio
async def test_connection_errors_exhaust_retries():
    sleep = FakeSleep()
    with aioresponses() as m:
        for _ in range(4):
            m.get(URL, exception=aiohttp.ClientConnectionError("down"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceUnavailable):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 4  # at most 4 requests in total
    assert sleep.calls == [0.5, 1.0, 2.0]  # waits before retries 1, 2, 3


@pytest.mark.asyncio
async def test_invalid_json_raises_protocol_error():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, body="this is not json{", content_type="text/plain")
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceProtocolError):
                await make_client(session, sleep).get_status()
    assert request_count(m) == 1


@pytest.mark.asyncio
async def test_non_object_json_raises_protocol_error():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=[1, 2, 3])
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceProtocolError):
                await make_client(session, sleep).get_status()


@pytest.mark.asyncio
async def test_missing_field_raises_protocol_error():
    body = ok_payload()
    del body["power_w"]
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=body)
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceProtocolError):
                await make_client(session, sleep).get_status()


@pytest.mark.asyncio
async def test_bool_power_is_rejected():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload(power_w=True))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(DeviceProtocolError):
                await make_client(session, sleep).get_status()


@pytest.mark.asyncio
async def test_retry_debug_marker_is_logged(caplog):
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=503)
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            with caplog.at_level(logging.DEBUG, logger="q2_client.client"):
                await make_client(session, sleep).get_status()
    assert "nt-b29c" in caplog.text


@pytest.mark.asyncio
async def test_retry_after_header_is_honoured():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=503, headers={"Retry-After": "2"})
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            await make_client(session, sleep).get_status()
    assert sleep.calls == [2.0]


@pytest.mark.asyncio
async def test_retry_after_is_capped_at_ten_seconds():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=503, headers={"Retry-After": "999"})
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            await make_client(session, sleep).get_status()
    assert sleep.calls == [10.0]


@pytest.mark.asyncio
async def test_unusable_retry_after_falls_back_to_normal_delay():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=503, headers={"Retry-After": "soon"})
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            await make_client(session, sleep).get_status()
    assert sleep.calls == [0.5]


def test_tool_definition_shape():
    assert TOOL_DEFINITION["name"] == "get_meter_status"
    assert isinstance(TOOL_DEFINITION["description"], str)
    assert TOOL_DEFINITION["description"].strip() != ""
    schema = TOOL_DEFINITION["input_schema"]
    assert isinstance(schema, dict) and schema.get("type") == "object"


@pytest.mark.asyncio
async def test_handle_tool_call_success():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, payload=ok_payload())
        async with aiohttp.ClientSession() as session:
            result = await handle_tool_call(make_client(session, sleep),
                                            "get_meter_status", {})
    assert result == {
        "serial": "SL-0042",
        "firmware": "2.1.0",
        "power_w": 412.5,
        "energy_kwh": 18234.567,
        "uptime_s": 86400,
    }


@pytest.mark.asyncio
async def test_handle_tool_call_meter_error_becomes_error_dict():
    sleep = FakeSleep()
    with aioresponses() as m:
        m.get(URL, status=401)
        async with aiohttp.ClientSession() as session:
            result = await handle_tool_call(make_client(session, sleep),
                                            "get_meter_status", {})
    assert result == {"error": "AuthError"}


@pytest.mark.asyncio
async def test_handle_tool_call_unknown_tool():
    sleep = FakeSleep()
    async with aiohttp.ClientSession() as session:
        result = await handle_tool_call(make_client(session, sleep),
                                        "nope", {})
    assert result == {"error": "unknown_tool"}
    assert issubclass(DeviceUnavailable, MeterError)
