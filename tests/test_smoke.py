from q1_meter.meter import METER_SPEC_REV, daily_consumption_kwh
from q2_client.client import (
    AuthError,
    DeviceProtocolError,
    DeviceUnavailable,
    MeterClient,
    MeterError,
    MeterStatus,
)


def test_q1_names():
    assert METER_SPEC_REV == "nt-7f3a"
    assert callable(daily_consumption_kwh)


def test_q2_names():
    assert issubclass(AuthError, MeterError)
    assert issubclass(DeviceUnavailable, MeterError)
    assert issubclass(DeviceProtocolError, MeterError)
    assert hasattr(MeterClient, "get_status")
