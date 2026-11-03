"""Step 1 dashboard data adapter tests; no browser or MQTT broker required."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from data_utils.duckdb_repo import SharedDuckDBRepository
from repository.evc_info_dao import EVChargerInfoDAO
from repository.utils import duckdb_utils
from view.dashboard_app import _marker_id_from_event
from view.dashboard_data import load_run, load_stations


class DashboardDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db_path = Path(self.temporary.name) / "stations.duckdb"
        self.use_database(self.db_path)
        duckdb_utils.execute("""
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

    def use_database(self, path):
        """Point the shared connection at path for the rest of the test."""
        duckdb_utils.close_connection()
        patcher = patch.object(duckdb_utils, "duckdb_config", return_value=dict(
            database=path, read_only=False, extensions=()))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(duckdb_utils.close_connection)  # Runs first, releasing the file.

    def test_stations_use_real_station_fields_and_assignment_1_connectors(self):
        stations, total_chargers = load_stations()
        self.assertEqual(total_chargers, 2)
        self.assertEqual(load_run(None, (1, 2)), ((), None))  # no events stored yet
        mappable = [station for station in stations if station.has_valid_coordinates]
        self.assertEqual((len(stations), len(mappable)), (2, 1))
        station = mappable[0]
        self.assertEqual(station.charger.station_name, "Mapped station")
        self.assertEqual(station.connector_types, ("CCS2", "CHAdeMO"))
        self.assertEqual(station.charger.rating_kw, 150.0)

        # Marker selection uses the exact NiceGUI GenericLayer id extracted by
        # browser-side JavaScript, rather than matching lat/lon values. This also
        # remains unambiguous if two real stations share coordinates.
        self.assertEqual(_marker_id_from_event(SimpleNamespace(args={"marker_id": "layer-123"})), "layer-123")
        self.assertEqual(_marker_id_from_event(SimpleNamespace(args="layer-456")), "layer-456")
        self.assertIsNone(_marker_id_from_event(SimpleNamespace(args={"latlng": {"lat": -33.8688}})))

    def test_station_dao_reads_connector_types_and_tolerates_missing_enrichment(self):
        dao = EVChargerInfoDAO(SharedDuckDBRepository())
        self.assertEqual(dao.list_connector_types(), {1: ("CCS2", "CHAdeMO")})
        self.assertEqual(dao.list_station_details(), {})  # no sa4_region or augmentation tables

    def test_missing_database_is_not_silently_replaced(self):
        missing = self.db_path.parent / "missing.db"
        self.use_database(missing)
        with self.assertRaises(FileNotFoundError):
            load_stations()
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
