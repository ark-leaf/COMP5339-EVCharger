"""Historical Run queries against Yeh's current state-table primary keys."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from view.dashboard_data import load_dashboard_snapshot


class DashboardInitialLoadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db_path = Path(temp.name) / "dashboard.duckdb"
        with duckdb.connect(str(self.db_path)) as conn:
            conn.execute("""
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
                -- Yeh's newest PK shape. It contains only Run B's latest state.
                CREATE TABLE charger_state (charger_id INTEGER PRIMARY KEY, run_id VARCHAR, price_per_kwh DOUBLE,
                    active_sessions INTEGER, last_event_ts TIMESTAMPTZ);
                CREATE TABLE connector_state (charger_id INTEGER, connector_no INTEGER, run_id VARCHAR, status VARCHAR,
                    session_id VARCHAR, PRIMARY KEY(charger_id, connector_no));
                CREATE TABLE charger_event (event_id VARCHAR, run_id VARCHAR, event_type VARCHAR, event_ts TIMESTAMPTZ,
                    charger_id INTEGER, connector_no INTEGER, session_id VARCHAR, price_per_kwh DOUBLE, vehicle_model VARCHAR,
                    power_kw DOUBLE, energy_kwh DOUBLE, soc_pct DOUBLE, charge_minutes DOUBLE, cost_aud DOUBLE);
                INSERT INTO charger_state VALUES (1, 'run-b', 0.9, 0, '2026-10-02 01:00:00+00');
                INSERT INTO connector_state VALUES (1, 1, 'run-b', 'available', NULL);
                INSERT INTO charger_event VALUES
                    ('a-price', 'run-a', 'price_update', '2026-10-01 00:00:00+00', 1, NULL, NULL, 0.0, NULL, NULL, NULL, NULL, NULL, NULL),
                    ('a-start-ended', 'run-a', 'session_start', '2026-10-01 00:01:00+00', 1, 1, 'ended-a', 0.5, 'EV A', NULL, NULL, NULL, NULL, NULL),
                    ('a-end', 'run-a', 'session_end', '2026-10-01 00:30:00+00', 1, 1, 'ended-a', 0.5, NULL, NULL, 2.0, NULL, 29, 1.0),
                    ('a-start-1', 'run-a', 'session_start', '2026-10-01 01:00:00+00', 1, 2, 'active-a', 0.0, 'EV A', NULL, NULL, NULL, NULL, NULL),
                    ('a-start-2', 'run-a', 'session_start', '2026-10-01 01:01:00+00', 1, 3, 'active-b', 0.4, 'EV B', NULL, NULL, NULL, NULL, NULL),
                    ('a-m1', 'run-a', 'meter', '2026-10-01 01:05:00+00', 1, 2, 'active-a', NULL, NULL, 50, 0.5, 44, NULL, NULL),
                    ('a-m3', 'run-a', 'meter', '2026-10-01 01:08:00+00', 1, 3, 'active-b', NULL, NULL, 40, 0.8, 38, NULL, NULL),
                    ('a-m2', 'run-a', 'meter', '2026-10-01 01:10:00+00', 1, 2, 'active-a', NULL, NULL, 50, 1.2, 55, NULL, NULL),
                    ('b-price', 'run-b', 'price_update', '2026-10-02 00:00:00+00', 1, NULL, NULL, 0.9, NULL, NULL, NULL, NULL, NULL, NULL),
                    ('b-start', 'run-b', 'session_start', '2026-10-02 00:01:00+00', 1, 1, 'ended-b', 0.9, 'EV C', NULL, NULL, NULL, NULL, NULL),
                    ('b-end', 'run-b', 'session_end', '2026-10-02 01:00:00+00', 1, 1, 'ended-b', 0.9, NULL, NULL, 3.0, NULL, 59, 2.7);
            """)

    def test_selected_run_replays_its_own_state_despite_latest_state_overwrite(self):
        events = load_dashboard_snapshot(self.db_path, "run-a").events
        self.assertEqual(events.run_id, "run-a")
        self.assertEqual(set(events.run_ids), {"run-a", "run-b"})
        self.assertEqual(events.active_session_count, 2)
        self.assertEqual(events.completed_sessions, 1)
        self.assertEqual(events.average_price_per_kwh, 0.0)
        self.assertEqual([session.key for session in events.active_sessions], [(1, 2, "active-a"), (1, 3, "active-b")])
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 2, "active-a")]],[0.5, 1.2])
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 3, "active-b")]],[0.8])
        # A completed session remains independently selectable with its exact
        # immutable meter series; it is never mixed with either active connector.
        completed = events.completed_session_records[0]
        self.assertEqual(completed.key, (1, 1, "ended-a"))
        self.assertEqual(events.meter_points.get(completed.key, ()), ())
        self.assertEqual(events.analytics.station_history[1].price_points[0].price_per_kwh, 0.0)

    def test_other_run_does_not_leak_active_sessions_or_prices(self):
        events = load_dashboard_snapshot(self.db_path, "run-b").events
        self.assertEqual(events.run_id, "run-b")
        self.assertEqual(events.active_session_count, 0)
        self.assertEqual(events.completed_sessions, 1)
        self.assertEqual(events.average_price_per_kwh, 0.9)
        self.assertEqual(events.active_sessions, ())
        self.assertEqual(events.meter_points, {})


if __name__ == "__main__":
    unittest.main()
