"""
Pack telemetry: where the battery number comes from, and what happens when
there isn't one.

The helmet runs off a 20,000 mAh USB-C PD bank, which exposes no state of
charge to the Pi. Every path below therefore has to be labelled, because
"63%" from a fuel gauge and "63%" coulomb-counted since boot are different
claims, and "no reading" must never render as a comfortable-looking number.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pyrosight.core.diagnostics import Diagnostics


class FakeEsp32:
    """Stands in for the helmet's ESP32 serial link."""

    def __init__(self, payload=None):
        self.payload = payload

    def battery(self, max_age_s: float = 15.0):
        return self.payload


def _sample(diag: Diagnostics):
    # interval=0 would still cache; force a collection by sampling directly.
    return diag._collect(sim_mode=False)


def test_fuel_gauge_reading_is_used_verbatim():
    diag = Diagnostics(esp32=FakeEsp32({"percent": 63}))
    out = _sample(diag)
    assert out["battery_percent"] == 63.0
    assert out["battery_source"] == "gauge"


def test_shunt_only_is_coulomb_counted_and_labelled():
    diag = Diagnostics(esp32=FakeEsp32({"volts": 5.02, "amps": 1.8}))
    first = _sample(diag)
    assert first["battery_source"] == "counted"
    assert first["battery_percent"] == 100.0  # boot assumption: full

    # A later sample must have drained, never risen.
    diag._coulomb_ts -= 600.0  # pretend ten minutes passed
    second = _sample(diag)
    assert second["battery_source"] == "counted"
    assert second["battery_percent"] < first["battery_percent"]


def test_gauge_reading_rezeroes_the_counter():
    diag = Diagnostics(esp32=FakeEsp32({"volts": 5.0, "amps": 2.0}))
    _sample(diag)
    diag._coulomb_ts -= 3600.0
    drifted = _sample(diag)
    assert drifted["battery_percent"] < 100.0

    diag._esp32 = FakeEsp32({"percent": 88})
    assert _sample(diag)["battery_source"] == "gauge"
    assert diag._coulomb_mah is None, "a real gauge must clear counter drift"


def test_no_esp32_on_a_pi_reports_no_gauge_not_a_number():
    diag = Diagnostics(esp32=FakeEsp32(None))
    out = _sample(diag)
    # On a host with its own battery (a dev laptop) psutil legitimately
    # answers; what must never happen is an invented figure on the helmet.
    assert out["battery_source"] in ("host", "none")
    if out["battery_source"] == "none":
        assert out["battery_percent"] is None
        assert out["power_state"] == "unknown"


def test_peripheral_failure_cannot_break_telemetry():
    class Exploding:
        def battery(self, max_age_s: float = 15.0):
            raise RuntimeError("serial went away mid-read")

    diag = Diagnostics(esp32=Exploding())
    out = _sample(diag)  # must not raise
    assert "battery_source" in out
