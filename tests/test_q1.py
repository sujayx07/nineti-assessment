
import copy

from q1_meter.meter import METER_SPEC_REV, daily_consumption_kwh


def test_spec_rev_constant():
    assert METER_SPEC_REV == "nt-7f3a"


def test_spec_example():
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        {"ts": "2026-01-10T20:00:00+01:00", "energy": "1004500"},
        {"ts": "2026-01-11T08:00:00+01:00", "energy_kwh": 1007.25},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 4.5, "2026-01-11": 2.75}


def test_appendix_a_sample():
    readings = [
        {"ts": "2026-03-28T06:00:00+01:00", "energy": "18200000"},
        {"ts": "2026-03-28T12:00:00+01:00", "energy": "18203100"},
        {"ts": "2026-03-28T18:00:00+01:00", "energy": "18206900"},
        {"ts": "2026-03-28T23:00:00Z", "energy": "18208400"},
        {"ts": "2026-03-29T06:00:00+02:00", "energy": "18209000"},
        {"ts": "2026-03-29T12:00:00+02:00", "energy": None},
        {"ts": "2026-03-29T12:00:00+02:00", "energy": "18211800"},
        {"ts": "2026-03-29T18:00:00+02:00", "energy_kwh": 18214.3},
        {"ts": "2026-03-29T19:00:00+02:00", "energy": "99999999"},
        {"ts": "2026-03-30T06:00:00+02:00", "energy_kwh": 1.2},
        {"ts": "2026-03-30T12:00:00+02:00", "energy": "4000"},
        {"ts": "not-a-date", "energy": "4100"},
        {"ts": "2026-03-30T18:00:00", "energy": "4200"},
    ]
    assert daily_consumption_kwh(readings) == {
        "2026-03-28": 6.9,
        "2026-03-29": 7.4,
        "2026-03-30": 4.0,
    }


def test_invalid_readings_are_skipped_silently():
    good = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "1001000"},
    ]
    bad = [
        "not a dict",
        42,
        None,
        {},  # missing everything
        {"ts": "2026-01-10T08:30:00+01:00"},  # missing energy value
        {"energy": "1000500"},  # missing ts
        {"ts": 12345, "energy": "1000500"},  # ts not a string
        {"ts": "not-a-date", "energy": "1000500"},  # unparseable ts
        {"ts": "2026-01-10T08:30:00", "energy": "1000500"},  # no UTC offset
        {"ts": "2026-01-10T08:30:00+01:00", "energy": ""},  # empty digits
        {"ts": "2026-01-10T08:30:00+01:00", "energy": "12.5"},
        {"ts": "2026-01-10T08:30:00+01:00", "energy": "-5"},
        {"ts": "2026-01-10T08:30:00+01:00", "energy": None},
        {"ts": "2026-01-10T08:30:00+01:00", "energy": 1000500},  # not a str
        {"ts": "2026-01-10T08:30:00+01:00", "energy_kwh": True},  # bool!
        {"ts": "2026-01-10T08:30:00+01:00", "energy_kwh": -1.5},
        {"ts": "2026-01-10T08:30:00+01:00", "energy_kwh": float("nan")},
        {"ts": "2026-01-10T08:30:00+01:00", "energy_kwh": float("inf")},
        {"ts": "2026-01-10T08:30:00+01:00", "energy_kwh": "1000.5"},
    ]
    # None of the bad readings may change the result (or raise).
    assert daily_consumption_kwh(good + bad) == {"2026-01-10": 1.0}
    assert daily_consumption_kwh(bad) == {}


def test_energy_kwh_wins_when_both_keys_present():
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        # "energy" would mean 999999 Wh, but energy_kwh (1000.5 kWh) wins.
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "999999", "energy_kwh": 1000.5},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 0.5}


def test_duplicate_instant_keeps_last_in_input():
    # Same instant written two ways; the later one in the INPUT list wins.
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        {"ts": "2026-01-10T07:00:00Z", "energy": "2000000"},  # same instant!
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "2001000"},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 1.0}


def test_input_may_be_in_any_order():
    readings = [
        {"ts": "2026-01-11T08:00:00+01:00", "energy_kwh": 1007.25},
        {"ts": "2026-01-10T20:00:00+01:00", "energy": "1004500"},
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 4.5, "2026-01-11": 2.75}


def test_counter_reset():
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "5000"},  # rebooted
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 5.0}


def test_glitch_is_discarded_and_reference_is_kept():
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        # +21000 Wh in 1 h = 21 kW -> glitch, discarded completely.
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "1021000"},
        # Compared against the last ACCEPTED reading (08:00), not the glitch.
        {"ts": "2026-01-10T10:00:00+01:00", "energy": "1002000"},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 2.0}


def test_exactly_20000_w_is_allowed():
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        # Exactly 20000 Wh in 1 h = 20000 W -> allowed, not a glitch.
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "1020000"},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 20.0}


def test_day_is_berlin_date_of_later_reading():
    # 22:30Z is already the next day in Berlin (UTC+2 in June).
    readings = [
        {"ts": "2026-06-01T21:30:00Z", "energy": "1000000"},
        {"ts": "2026-06-01T22:30:00Z", "energy": "1001000"},
    ]
    assert daily_consumption_kwh(readings) == {"2026-06-02": 1.0}


def test_zero_consumption_day_still_appears():
    readings = [
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        {"ts": "2026-01-10T09:00:00+01:00", "energy": "1000000"},
    ]
    assert daily_consumption_kwh(readings) == {"2026-01-10": 0.0}


def test_fewer_than_two_accepted_readings():
    assert daily_consumption_kwh([]) == {}
    assert daily_consumption_kwh([{"ts": "2026-01-10T08:00:00+01:00", "energy": "1"}]) == {}
    assert daily_consumption_kwh([{"ts": "nope", "energy": "1"}]) == {}


def test_does_not_modify_input():
    readings = [
        {"ts": "2026-01-10T20:00:00+01:00", "energy": "1004500"},
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
    ]
    snapshot = copy.deepcopy(readings)
    daily_consumption_kwh(readings)
    assert readings == snapshot


def test_keys_are_in_ascending_date_order():
    readings = [
        {"ts": "2026-01-12T08:00:00+01:00", "energy": "1010000"},
        {"ts": "2026-01-10T08:00:00+01:00", "energy": "1000000"},
        {"ts": "2026-01-11T08:00:00+01:00", "energy": "1005000"},
    ]
    result = daily_consumption_kwh(readings)
    assert list(result) == ["2026-01-11", "2026-01-12"]
    assert result == {"2026-01-11": 5.0, "2026-01-12": 5.0}
