"""Core entity contracts. Run: python -m unittest discover -s tests -v

AI assistance acknowledgement: OpenAI Codex assisted in creating these tests.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from repository.entity.ev_charger import EVCharger
from repository.entity.ev_charger_event import EVChargerEvent
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.entity.ev_charger_state import EVChargerState


BASE_TIME = datetime(2026, 10, 1, 10, tzinfo=timezone(timedelta(hours=10)))


def event(kind, event_id, minute=0, *, session_id="session-1", connector_id=1,
          station_id="42", run_id="run-1", payload=None):
    defaults = {
        "price_update": {"price_per_kwh": 0.6, "wholesale_per_kwh": -0.02},
        "session_start": {"price_per_kwh": 0.6, "vehicle_model": "Example EV"},
        "meter": {"power_kw": 60.0, "energy_kwh": 1.0, "soc_pct": 40.0},
        "session_end": {
            "charge_end_ts": (BASE_TIME + timedelta(minutes=2)).isoformat(),
            "charge_minutes": 2.0, "energy_kwh": 2.0,
            "price_per_kwh": 0.6, "cost_aud": 1.2,
        },
    }
    return EVChargerEvent(
        run_id=run_id, event_id=event_id, type=kind,
        ts=BASE_TIME + timedelta(minutes=minute), station_id=station_id,
        connector_id=None if kind == "price_update" else connector_id,
        session_id=None if kind == "price_update" else session_id,
        payload=defaults[kind] if payload is None else payload,
    )


class StationTests(unittest.TestCase):
    def test_sql_record_preserves_identity_missing_values_and_json_numbers(self):
        station = EVCharger.from_record({
            "charger_id": 42, "source_objectid": 9001,
            "latitude": Decimal("-33.86"), "rating_kw": Decimal("22.0"),
            "number_of_plugs": None, "unrelated_column": "ignored",
        })
        self.assertEqual(station.station_id, "42")
        self.assertEqual(station.source_objectid, 9001)
        self.assertEqual(station.rating_kw, 22.0)
        self.assertIsNone(station.number_of_plugs)
        self.assertIsNone(station.operator_name)
        self.assertIsNone(EVCharger(charger_id=42).rating_kw)
        self.assertEqual(EVCharger.from_record(json.loads(json.dumps(
            station.to_dict()))).to_dict(), station.to_dict())

    def test_station_id_must_be_a_positive_integer(self):
        for invalid in (True, 0, -1, 1.5, "42"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                EVCharger(charger_id=invalid)


class EventTests(unittest.TestCase):
    def test_four_types_roundtrip_over_json(self):
        for kind in ("price_update", "session_start", "meter", "session_end"):
            with self.subTest(kind=kind):
                original = event(kind, kind, 3)
                restored = EVChargerStateEvent.from_json(original.to_json())
                self.assertIsInstance(restored, EVChargerEvent)
                self.assertEqual(restored.to_dict(), original.to_dict())
                self.assertEqual(restored.ts, original.ts)
        self.assertEqual(event("price_update", "p").payload["wholesale_per_kwh"], -0.02)

    def test_required_fields_and_event_envelope_are_checked(self):
        cases = [("meter", "connector_id", None), ("meter", "session_id", None),
                 ("meter", "type", "unknown"), ("meter", "ts", "2026-10-01T10:00:00"),
                 ("price_update", "session_id", "unexpected-session")]
        for kind, field, value in cases:
            message = event(kind, "e", 3).to_dict()
            message[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                EVChargerEvent.from_dict(message)
        for kind, field in (("price_update", "price_per_kwh"),
                            ("session_start", "price_per_kwh"),
                            ("meter", "energy_kwh"), ("session_end", "charge_end_ts")):
            message = event(kind, "e", 3).to_dict()
            del message["payload"][field]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                EVChargerEvent.from_dict(message)

    def test_invalid_meter_values_and_future_results_at_start_are_rejected(self):
        for field, value in (("power_kw", float("nan")), ("energy_kwh", float("inf")),
                             ("energy_kwh", -1), ("power_kw", True), ("soc_pct", 101)):
            message = event("meter", "m").to_dict()
            message["payload"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                EVChargerEvent.from_dict(message)
        with self.assertRaises(ValueError):
            event("session_start", "s", payload={"price_per_kwh": 0.6, "cost_aud": 10})


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = EVChargerState(station_id="42", run_id="run-1")

    def test_two_ports_update_independently_and_end_accepts_generator_rounding(self):
        self.state.apply(event("price_update", "p"))
        self.state.apply(event("session_start", "s1"))
        self.state.apply(event("session_start", "s2", session_id="session-2", connector_id=2))
        self.assertEqual(self.state.price_per_kwh, 0.6)
        self.assertEqual(self.state.active_session_count, 2)
        self.state.apply(event("meter", "m", 2, payload={"power_kw": 60, "energy_kwh": 2.004}))
        self.assertEqual(self.state.active_sessions["session-1"]["latest_meter"]["payload"]["energy_kwh"], 2.004)
        self.assertTrue(self.state.apply(event("session_end", "e", 2)))
        self.state.apply(event("session_start", "s3", 2, session_id="session-3"))
        self.assertEqual(set(self.state.active_sessions), {"session-2", "session-3"})
        self.assertEqual(set(self.state.occupied_connector_ids), {1, 2})
        json.dumps(self.state.to_dict(), allow_nan=False)

    def test_wrong_identity_unknown_session_and_occupied_port_are_rejected(self):
        for message in (event("price_update", "p", station_id="43"),
                        event("price_update", "p", run_id="run-2"), event("meter", "m", 1),
                        event("session_end", "e", 3)):
            with self.assertRaises(ValueError):
                self.state.apply(message)
        self.state.apply(event("session_start", "s"))
        for message in (event("session_start", "s2", session_id="session-2"),
                        event("meter", "m", 1, connector_id=2)):
            with self.assertRaises(ValueError):
                self.state.apply(message)
        self.assertEqual(self.state.active_session_count, 1)

    def test_late_events_and_decreasing_cumulative_energy_are_rejected(self):
        self.state.apply(event("session_start", "s"))
        self.state.apply(event("meter", "m1", 2))
        for message in (event("price_update", "p", 1),
                        event("meter", "m2", 3, payload={"power_kw": 60, "energy_kwh": 0.5})):
            with self.assertRaises(ValueError):
                self.state.apply(message)


if __name__ == "__main__":
    unittest.main()
