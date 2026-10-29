"""Step 1 dashboard data adapter tests; no browser or MQTT broker required."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import duckdb

from view.dashboard_app import _marker_id_from_event
from view.dashboard_data import database_guidance, load_dashboard_snapshot


class DashboardDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db_path = Path(self.temporary.name) / "stations.duckdb"
        with duckdb.connect(str(self.db_path)) as connection:
            connection.execute("""
                CREATE TABLE operator (operator_id INTEGER PRIMARY KEY, operator_name VARCHAR);
                CREATE TABLE charger_location (
                    charger_id INTEGER PRIMARY KEY, source_objectid BIGINT, station_name VARCHAR,
                    station_address VARCHAR, operator_id INTEGER, latitude DOUBLE, longitude DOUBLE
                );
                CREATE TABLE charger_characteristic (
                    charger_id INTEGER PRIMARY KEY, charger_type VARCHAR,
                    number_of_plugs INTEGER, rating_kw DOUBLE
                );
                CREATE TABLE charger_connector (
                    charger_connector_id INTEGER PRIMARY KEY, charger_id INTEGER, connector_type VARCHAR
                );
                INSERT INTO operator VALUES (1, 'Example Network');
                INSERT INTO charger_location VALUES
                    (1, 1001, 'Mapped station', '1 Main St', 1, -33.8688, 151.2093),
                    (2, 1002, 'No coordinate station', '2 Main St', 1, NULL, NULL);
                INSERT INTO charger_characteristic VALUES (1, 'DC', 4, 150), (2, 'AC', 2, 22);
                INSERT INTO charger_connector VALUES (1, 1, 'CCS2'), (2, 1, 'CHAdeMO');
            """)

    def test_snapshot_uses_real_station_fields_and_assignment_1_connectors(self):
        snapshot = load_dashboard_snapshot(self.db_path)
        self.assertEqual(snapshot.total_chargers, 2)
        self.assertFalse(snapshot.events.has_event_data)
        self.assertEqual(len(snapshot.stations), 2)
        self.assertEqual(len(snapshot.mappable_stations), 1)
        station = snapshot.mappable_stations[0]
        self.assertEqual(station.charger.station_name, "Mapped station")
        self.assertEqual(station.connector_types, ("CCS2", "CHAdeMO"))
        self.assertEqual(station.charger.rating_kw, 150.0)

        # Marker selection uses the exact NiceGUI GenericLayer id extracted by
        # browser-side JavaScript, rather than matching lat/lon values. This also
        # remains unambiguous if two real stations share coordinates.
        self.assertEqual(_marker_id_from_event(SimpleNamespace(args={"marker_id": "layer-123"})), "layer-123")
        self.assertEqual(_marker_id_from_event(SimpleNamespace(args="layer-456")), "layer-456")
        self.assertIsNone(_marker_id_from_event(SimpleNamespace(args={"latlng": {"lat": -33.8688}})))

    def test_missing_database_is_not_silently_replaced(self):
        missing = self.db_path.parent / "missing.db"
        with self.assertRaises(FileNotFoundError):
            load_dashboard_snapshot(missing)
        self.assertIn("main_ass_1.py --stage load", database_guidance(missing))


if __name__ == "__main__":
    unittest.main()
