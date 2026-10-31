"""A run's dashboard model, read through the DAOs from the real event schema and advanced by MQTT."""
from __future__ import annotations

import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from event.ev_charger_state_event import EVChargerStateEvent
from repository.evc_event_dao import EVChargerEventDAO
from repository.utils import duckdb_utils
from transaction_scripts.stateful_event_storage.save_subscribed_data import prepare_event_storage, save_event
from view.dashboard_data import load_run


def at(day, hhmm):
    return f"2026-10-0{day}T{hhmm}:00+00:00"


def event(run_id, kind, ts, payload, *, connector=None, session=None, charger="1"):
    return EVChargerStateEvent(run_id=run_id, id=uuid.uuid4().hex, type=kind, ts=ts, object_id=charger,
                               connector_id=connector, session_id=session, payload=payload)


# Charger 1 in run A: one finished session and two still charging on connectors 2 and 3.
RUN_A = [
    event("run-a", "price_update", at(1, "00:00"), {"price_per_kwh": 0.0, "wholesale_per_kwh": -0.02}),
    event("run-a", "session_start", at(1, "00:01"), {"price_per_kwh": 0.5, "vehicle_model": "EV A"},
          connector=1, session="ended-a"),
    event("run-a", "session_end", at(1, "00:30"), {"charge_end_ts": at(1, "00:29"), "charge_minutes": 28.0,
          "energy_kwh": 2.0, "price_per_kwh": 0.5, "cost_aud": 1.0}, connector=1, session="ended-a"),
    event("run-a", "session_start", at(1, "01:00"), {"price_per_kwh": 0.0, "vehicle_model": "EV A"},
          connector=2, session="active-a"),
    event("run-a", "session_start", at(1, "01:01"), {"price_per_kwh": 0.4, "vehicle_model": "EV B"},
          connector=3, session="active-b"),
    event("run-a", "meter", at(1, "01:05"), {"power_kw": 50.0, "energy_kwh": 0.5, "soc_pct": 44.0},
          connector=2, session="active-a"),
    event("run-a", "meter", at(1, "01:08"), {"power_kw": 40.0, "energy_kwh": 0.8, "soc_pct": 38.0},
          connector=3, session="active-b"),
    event("run-a", "meter", at(1, "01:10"), {"power_kw": 50.0, "energy_kwh": 1.2, "soc_pct": 55.0},
          connector=2, session="active-a"),
]
# Run B reuses charger 1 a day later, so charger_state now holds run B's state.
RUN_B = [
    event("run-b", "price_update", at(2, "00:00"), {"price_per_kwh": 0.9}),
    event("run-b", "session_start", at(2, "00:01"), {"price_per_kwh": 0.9, "vehicle_model": "EV C"},
          connector=1, session="ended-b"),
    event("run-b", "session_end", at(2, "01:00"), {"charge_end_ts": at(2, "00:59"), "charge_minutes": 58.0,
          "energy_kwh": 3.0, "price_per_kwh": 0.9, "cost_aud": 2.7}, connector=1, session="ended-b"),
]


class DashboardModelTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(duckdb_utils, "duckdb_config", return_value=dict(
            database=Path(directory.name) / "dashboard.db", read_only=False, extensions=()))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(duckdb_utils.close_connection)  # Runs first, releasing the file.
        duckdb_utils.execute("""
            CREATE TABLE operator (operator_id INTEGER PRIMARY KEY, operator_name VARCHAR);
            CREATE TABLE charger_location (charger_id INTEGER PRIMARY KEY, source_objectid BIGINT,
                station_name VARCHAR, station_address VARCHAR, operator_id INTEGER, latitude DOUBLE, longitude DOUBLE);
            CREATE TABLE charger_characteristic (charger_id INTEGER PRIMARY KEY, charger_type VARCHAR,
                number_of_plugs INTEGER, rating_kw DOUBLE);
            CREATE TABLE charger_connector (charger_connector_id INTEGER PRIMARY KEY, charger_id INTEGER, connector_type VARCHAR);
            INSERT INTO operator VALUES (1, 'Network');
            INSERT INTO charger_location VALUES (1, 1, 'One', '1 Road', 1, -33.8, 151.2), (2, 2, 'Two', '2 Road', 1, -33.9, 151.3);
            INSERT INTO charger_characteristic VALUES (1, 'DC', 2, 50), (2, 'AC', 1, 7);
            INSERT INTO charger_connector VALUES (1, 1, 'CCS2');
        """)
        prepare_event_storage()
        for item in RUN_A + RUN_B:
            self.assertTrue(save_event(item))

    def stored_run(self, run_id):
        """What a page opening on run_id shows: that run's stored events, replayed."""
        run_ids, model = load_run(run_id, (1, 2))
        return model.snapshot(run_ids)

    def test_selected_run_replays_its_own_state_despite_latest_state_overwrite(self):
        events = self.stored_run("run-a")
        self.assertEqual(events.run_id, "run-a")
        self.assertEqual(events.run_ids, ("run-b", "run-a"))  # latest simulated time first
        self.assertEqual(events.active_session_count, 2)
        self.assertEqual(events.completed_sessions, 1)
        self.assertEqual(events.average_price_per_kwh, 0.0)
        self.assertEqual([session.key for session in events.active_sessions], [(1, 2, "active-a"), (1, 3, "active-b")])
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 2, "active-a")]], [0.5, 1.2])
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 3, "active-b")]], [0.8])
        # A completed session remains independently selectable with its exact
        # immutable meter series; it is never mixed with either active connector.
        completed = events.completed_session_records[0]
        self.assertEqual(completed.key, (1, 1, "ended-a"))
        self.assertEqual(events.meter_points.get(completed.key, ()), ())
        self.assertEqual(events.analytics.station_history[1].price_points[0].price_per_kwh, 0.0)

    def test_connectors_hold_each_ports_current_session_and_history(self):
        events = self.stored_run("run-a")
        # Charger 1 lists 2 plugs; connector 3 still gets a view because a session used it.
        first, second, third = events.connectors(1, 2)
        self.assertEqual((first.connector_no, first.status, first.active), (1, "available", None))
        self.assertEqual([session.session_id for session in first.completed], ["ended-a"])
        self.assertEqual(first.last_event_ts, first.completed[0].session_end_ts)
        # Charging stopped a minute before unplugging, which the charger's state history shows as idle time.
        self.assertEqual(first.completed[0].charge_end_ts, datetime.fromisoformat(at(1, "00:29")))
        self.assertEqual(events.analytics.station_history[1].price_points[0].wholesale_per_kwh, -0.02)
        self.assertEqual((second.status, second.active.session_id, second.active.power_kw), ("charging", "active-a", 50.0))
        self.assertEqual([(point.energy_kwh, point.power_kw, point.soc_pct) for point in second.meter_points["active-a"]],
                         [(0.5, 50.0, 44.0), (1.2, 50.0, 55.0)])
        self.assertEqual((third.connector_no, third.active.session_id), (3, "active-b"))
        # A connector's history ends at its own latest event, not at another charger's.
        self.assertEqual(second.event_times()[-1], datetime.fromisoformat(at(1, "01:10")))
        self.assertEqual(third.active.span_end_ts, datetime.fromisoformat(at(1, "01:08")))
        self.assertEqual([view.status for view in events.connectors(2, 1)], ["unknown"])  # No events for charger 2.

    def test_other_run_does_not_leak_active_sessions_or_prices(self):
        events = self.stored_run("run-b")
        self.assertEqual(events.run_id, "run-b")
        self.assertEqual(events.active_session_count, 0)
        self.assertEqual(events.completed_sessions, 1)
        self.assertEqual(events.average_price_per_kwh, 0.9)
        self.assertEqual(events.active_sessions, ())
        self.assertEqual(events.meter_points, {})

    def test_mqtt_events_continue_a_loaded_run_exactly_as_storing_them_would(self):
        run_ids, model = load_run("run-a", (1, 2))
        live = [
            event("run-a", "meter", at(1, "01:12"), {"power_kw": 40.0, "energy_kwh": 1.4},
                  connector=3, session="active-b"),
            event("run-a", "session_end", at(1, "01:20"), {"charge_end_ts": at(1, "01:15"), "charge_minutes": 15.0,
                  "energy_kwh": 1.2, "price_per_kwh": 0.0, "cost_aud": 0.0}, connector=2, session="active-a"),
            event("run-a", "price_update", at(1, "01:30"), {"price_per_kwh": 0.6}, charger="2"),
        ]
        for item in live:
            self.assertTrue(model.apply(item))
            self.assertTrue(save_event(item))
        _, reloaded = load_run("run-a", (1, 2))
        self.assertEqual(model.snapshot(run_ids), reloaded.snapshot(run_ids))

    def test_model_ignores_what_storage_would_reject(self):
        run_ids, model = load_run("run-a", (1, 2))
        before = model.snapshot(run_ids)
        for item in (
            RUN_A[-1],                                                   # stored, then redelivered
            replace(RUN_A[-1], id=str(uuid.UUID(RUN_A[-1].id))),         # the same id, hyphenated
            event("run-a", "session_start", at(1, "01:30"), {"price_per_kwh": 0.5},
                  connector=2, session="other"),                         # connector 2 is occupied
            event("run-a", "meter", at(1, "01:30"), {"power_kw": 1.0, "energy_kwh": 1.0},
                  connector=4, session="unknown"),                       # no such session
            event("run-a", "price_update", at(1, "01:30"), {"price_per_kwh": 0.5}, charger="99"),  # not a station
            event("run-c", "price_update", at(1, "01:30"), {"price_per_kwh": 0.5}),                 # another run
        ):
            self.assertFalse(model.apply(item))
        self.assertEqual(model.snapshot(run_ids), before)

    def test_a_run_storage_has_not_seen_yet_starts_empty(self):
        run_ids, model = load_run("run-new", (1, 2))
        self.assertEqual(run_ids, ("run-b", "run-a"))
        events = model.snapshot(run_ids)
        self.assertEqual((events.run_id, events.analytics.total_events, events.active_sessions), ("run-new", 0, ()))

    def test_event_dao_lists_runs_latest_first_and_a_runs_events_in_publish_order(self):
        dao = EVChargerEventDAO()
        self.assertTrue(dao.has_tables())
        self.assertEqual(dao.list_run_ids(), ("run-b", "run-a"))
        stored = dao.list_run_events("run-a")
        self.assertEqual([item.id for item in stored], [item.id for item in RUN_A])
        self.assertEqual(stored[2].payload, RUN_A[2].payload)  # session_end, including charge_end_ts


if __name__ == "__main__":
    unittest.main()
