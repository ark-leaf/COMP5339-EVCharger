"""Station reads against a small on-disk DuckDB, without external data.

AI assistance acknowledgement: OpenAI Codex assisted in creating these tests.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from repository.duckdb_repo import DuckDBRepository
from repository.entity.ev_charger import EVCharger
from repository.evc_info_dao import EVChargerInfoDAO
from repository.repo_config import duckdb_config


class StationRepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "stations.duckdb"
        with duckdb.connect(str(self.db_path)) as connection:
            connection.execute("""
                CREATE TABLE operator (
                    operator_id INTEGER PRIMARY KEY, operator_name VARCHAR
                );
                CREATE TABLE charger_location (
                    charger_id INTEGER PRIMARY KEY, source_objectid BIGINT,
                    station_name VARCHAR, station_address VARCHAR,
                    operator_id INTEGER, latitude DOUBLE, longitude DOUBLE
                );
                CREATE TABLE charger_characteristic (
                    charger_id INTEGER PRIMARY KEY, charger_type VARCHAR,
                    number_of_plugs INTEGER, rating_kw DOUBLE
                );
                INSERT INTO operator VALUES (1, 'Example Network');
                INSERT INTO charger_location VALUES
                    (42, 9042, 'DC Station', '42 Main St', 1, -33.86, 151.20),
                    (7, 9007, 'AC Station', '7 Main St', 1, -33.87, 151.21),
                    (900, 9900, NULL, NULL, 99, NULL, NULL);
                INSERT INTO charger_characteristic VALUES
                    (42, 'DC', 4, 150.0), (7, 'AC', NULL, 22.0);
            """)

    def test_lists_every_location_in_original_id_order_as_entities(self):
        with DuckDBRepository(self.db_path) as repository:
            dao = EVChargerInfoDAO(repository)
            stations = dao.list_chargers()
            self.assertEqual(dao.count_chargers(), 3)
        self.assertEqual([s.charger_id for s in stations], [7, 42, 900])
        self.assertTrue(all(isinstance(s, EVCharger) for s in stations))
        self.assertEqual([s.charger_type for s in stations[:2]], ["AC", "DC"])
        self.assertEqual(stations[1].charger_id, 42)
        self.assertEqual(stations[1].source_objectid, 9042)
        self.assertEqual(stations[1].operator_name, "Example Network")
        self.assertEqual(stations[1].rating_kw, 150.0)
        self.assertEqual(stations[1].number_of_plugs, 4)
        self.assertEqual(stations[1].latitude, -33.86)

    def test_focus_selection_uses_augmentation_and_region_without_duplicates(self):
        with duckdb.connect(str(self.db_path)) as db:
            db.execute("""
                CREATE TABLE charger (charger_id INTEGER);
                CREATE TABLE sa4_region (sa4_code VARCHAR, sa4_name VARCHAR);
                ALTER TABLE charger_location ADD COLUMN sa4_code VARCHAR;
                INSERT INTO charger VALUES (42), (42), (7);
                INSERT INTO sa4_region VALUES ('1', 'Sydney - City'), ('2', 'Newcastle');
                UPDATE charger_location SET sa4_code = CASE WHEN charger_id=42 THEN '1' ELSE '2' END;
            """)
        with DuckDBRepository(self.db_path) as repo:
            dao = EVChargerInfoDAO(repo)
            self.assertEqual(dao.list_augmented_charger_ids('Sydney'), (42,))
            self.assertEqual(dao.list_augmented_charger_ids('Newcastle'), (7,))
            self.assertEqual(dao.list_augmented_charger_ids('Missing'), ())

    def test_generation_requires_both_records_and_a_positive_operational_port_count(self):
        with duckdb.connect(str(self.db_path)) as db:
            db.execute("""
                CREATE TABLE charger (charger_id INTEGER);
                CREATE TABLE charger_connector (charger_id INTEGER, connector_type VARCHAR);
                INSERT INTO charger VALUES (42), (42), (7), (900);
                INSERT INTO charger_connector VALUES (42, 'CCS'), (42, 'CHAdeMO'), (900, 'CCS');
                UPDATE charger_characteristic SET number_of_plugs=2 WHERE charger_id=7;
                INSERT INTO charger_characteristic VALUES (900, 'DC', 2, 50);
            """)
        def selected():
            with DuckDBRepository(self.db_path) as repo:
                return [c.charger_id for c in EVChargerInfoDAO(repo).list_generation_chargers()]
        self.assertEqual(selected(), [42, 900])  # Multiple type rows do not duplicate a station.
        with duckdb.connect(str(self.db_path)) as db:
            db.execute('DELETE FROM charger WHERE charger_id=900')
        self.assertEqual(selected(), [42])  # Connector metadata alone is insufficient.
        for value in [None, 0, -1]:
            with self.subTest(plugs=value):
                with duckdb.connect(str(self.db_path)) as db:
                    db.execute('UPDATE charger_characteristic SET number_of_plugs=? WHERE charger_id=42', [value])
                self.assertEqual(selected(), [])
        with duckdb.connect(str(self.db_path)) as db:
            db.execute("UPDATE charger_characteristic SET number_of_plugs=2,charger_type='Upcoming' WHERE charger_id=42")
        self.assertEqual(selected(), [])

    def test_missing_attributes_and_unmatched_joins_preserve_station(self):
        with DuckDBRepository(self.db_path) as repository:
            dao = EVChargerInfoDAO(repository)
            self.assertIsNone(dao.get_charger(7).number_of_plugs)
            station = dao.get_charger(900)
            self.assertEqual(station.charger_id, 900)
            for field in ("station_name", "latitude", "operator_name",
                          "charger_type", "number_of_plugs", "rating_kw"):
                with self.subTest(field=field):
                    self.assertIsNone(getattr(station, field))
            self.assertIsNone(dao.get_charger(12345))

    def test_query_returns_named_columns_and_binds_values(self):
        with DuckDBRepository(self.db_path) as repository:
            rows = repository.fetch_all(
                "SELECT charger_id, ? AS label FROM charger_location "
                "WHERE charger_id = ?", ["driver's station", 42],
            )
            self.assertEqual(rows, [{"charger_id": 42, "label": "driver's station"}])
            self.assertEqual(repository.fetch_all(
                "SELECT charger_id FROM charger_location WHERE charger_id = ?", [-1]
            ), [])

    def test_connection_lifecycle_is_explicit_and_context_closes(self):
        repository = DuckDBRepository(self.db_path)
        self.addCleanup(repository.close)
        with self.assertRaises(RuntimeError):
            repository.fetch_all("SELECT 1")
        self.assertIs(repository.connect(), repository)
        self.assertIs(repository.connect(), repository)
        repository.close()
        repository.close()
        with repository as connected:
            self.assertIs(connected, repository)
            self.assertEqual(repository.fetch_all("SELECT 1 AS result"), [{"result": 1}])
        with self.assertRaises(RuntimeError):
            repository.fetch_all("SELECT 1")

    def test_default_connection_cannot_modify_base_snapshot(self):
        self.assertFalse(duckdb_config()["read_only"])
        self.assertIn("spatial", duckdb_config()["extensions"])
        with DuckDBRepository(self.db_path) as repository:
            with self.assertRaises(duckdb.Error):
                repository.fetch_all("DELETE FROM charger_location")
            self.assertEqual(EVChargerInfoDAO(repository).count_chargers(), 3)

    def test_explicit_writer_can_persist_events_in_existing_database(self):
        with DuckDBRepository(self.db_path, read_only=False) as repository:
            repository.fetch_all("CREATE TABLE test_events (event_id VARCHAR PRIMARY KEY)")
            repository.fetch_all("INSERT INTO test_events VALUES (?)", ["event-1"])
        with DuckDBRepository(self.db_path) as repository:
            self.assertEqual(repository.fetch_all("SELECT * FROM test_events"),
                             [{"event_id": "event-1"}])
            self.assertEqual(EVChargerInfoDAO(repository).count_chargers(), 3)

    def test_default_path_uses_shared_database_config(self):
        settings = {"database": self.db_path, "read_only": True}
        with patch("repository.duckdb_repo.duckdb_config", return_value=settings):
            with DuckDBRepository() as repository:
                self.assertEqual(EVChargerInfoDAO(repository).count_chargers(), 3)
                with self.assertRaises(duckdb.Error):
                    repository.fetch_all("DELETE FROM charger_location")

    def test_missing_path_never_creates_an_empty_database(self):
        missing_path = self.db_path.parent / "missing.duckdb"
        for read_only in (True, False):
            with self.subTest(read_only=read_only):
                with self.assertRaises(FileNotFoundError):
                    with DuckDBRepository(missing_path, read_only=read_only):
                        pass
                self.assertFalse(missing_path.exists())


if __name__ == "__main__":
    unittest.main()
