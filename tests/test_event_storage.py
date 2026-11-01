"""Task 4 event storage against a temporary Assignment 1 database. Claude (Anthropic) assisted these tests."""
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import duckdb

from config import DB_SCHEMA
from repository.evc_event_dao import PAYLOAD_COLUMNS, EVChargerEventDAO
from event.ev_charger_state_event import EVENT_TYPE_ORDER, PAYLOAD_FIELDS, EVChargerStateEvent
from repository.utils import duckdb_utils
from transaction_scripts.stateful_event_storage import save_subscribed_data
from transaction_scripts.stateful_event_storage.save_subscribed_data import prepare_event_storage, save_event


def event(n, kind, minute, payload, charger="42", session="s1", connector=1, run_id="run-1"):
    station_level = kind == "price_update"
    return EVChargerStateEvent(
        run_id=run_id, id=uuid.UUID(int=n).hex, type=kind, ts=f"2026-09-15T10:{minute:02d}:00+10:00",
        object_id=charger, connector_id=None if station_level else connector,
        session_id=None if station_level else session, payload=payload)


def one_session():
    """Price, a session with two meter readings, then unplugging two minutes after charging stopped."""
    return [
        event(1, "price_update", 0, {"price_per_kwh": 0.6, "wholesale_per_kwh": -0.02}),
        event(2, "session_start", 1, {"price_per_kwh": 0.6, "vehicle_model": "Example EV"}),
        event(3, "meter", 2, {"power_kw": 50.0, "energy_kwh": 0.8, "soc_pct": 40.0}),
        event(4, "meter", 3, {"power_kw": 48.0, "energy_kwh": 1.6, "voltage_v": 400.0,
                              "current_a": 120.0, "soc_pct": 42.0}),
        event(5, "session_end", 5, {"charge_end_ts": "2026-09-15T10:03:00+10:00", "charge_minutes": 2.0,
                                    "energy_kwh": 1.6, "price_per_kwh": 0.6, "cost_aud": 0.96,
                                    "avg_kw": 48.0, "peak_kw": 50.0}),
    ]


def same_time_handover():
    """At 10:05 the price changes, s1's final reading and unplug happen, and s2 starts on its connector."""
    return [
        event(21, "session_start", 1, {"price_per_kwh": 0.6}),
        event(22, "meter", 3, {"power_kw": 7.0, "energy_kwh": 0.2}),
        event(23, "price_update", 5, {"price_per_kwh": 0.7}),
        event(24, "meter", 5, {"power_kw": 7.0, "energy_kwh": 0.5}),
        event(25, "session_end", 5, {"charge_end_ts": "2026-09-15T10:05:00+10:00", "charge_minutes": 4.0,
                                     "energy_kwh": 0.5, "price_per_kwh": 0.6, "cost_aud": 0.3}),
        event(26, "session_start", 5, {"price_per_kwh": 0.7}, session="s2"),
    ]


class EventStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "nsw_evc.db"
        patcher = patch.object(duckdb_utils, "duckdb_config", return_value=dict(
            database=self.db_path, read_only=False, extensions=("spatial",)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(duckdb_utils.close_connection)  # Runs first, releasing the file.
        duckdb_utils.run_sql_file(DB_SCHEMA)
        duckdb_utils.execute("INSERT INTO operator VALUES (1, 'Example Operator', 'example operator')")
        duckdb_utils.execute("INSERT INTO charger_location (charger_id, station_name, operator_id) "
                             "VALUES (42, 'Test Station', 1), (7, 'Other Station', 1)")
        prepare_event_storage()
        self.dao = EVChargerEventDAO()

    def count(self):
        return duckdb_utils.fetch_one("SELECT count(*) FROM charger_event")[0]

    def test_payload_columns_cover_every_event_field(self):
        fields = set().union(*(required | optional for required, optional in PAYLOAD_FIELDS.values()))
        self.assertEqual(set(PAYLOAD_COLUMNS), fields)

    def test_each_event_is_one_row_with_typed_columns_linked_to_its_charger(self):
        self.assertTrue(all(save_event(e) for e in one_session()))
        self.assertEqual(self.count(), 5)
        self.assertEqual(duckdb_utils.fetch_all(
            "SELECT e.event_type, l.station_name, e.price_per_kwh, e.energy_kwh, e.cost_aud, "
            "date_diff('second', e.charge_end_ts, e.event_ts) / 60 "
            "FROM charger_event AS e JOIN charger_location AS l USING (charger_id) "
            "ORDER BY e.event_ts, e.event_type"), [
            ("price_update", "Test Station", Decimal("0.6000"), None, None, None),
            ("session_start", "Test Station", Decimal("0.6000"), None, None, None),
            ("meter", "Test Station", None, 0.8, None, None),
            ("meter", "Test Station", None, 1.6, None, None),
            ("session_end", "Test Station", Decimal("0.6000"), 1.6, Decimal("0.96"), 2.0),
        ])

    def test_stored_events_read_back_unchanged(self):
        for e in one_session():
            save_event(e)
        self.assertEqual([e.to_dict() for e in self.dao.list_events("run-1", 42)],
                         [e.to_dict() for e in one_session()])

    def test_replay_skips_duplicates(self):
        self.assertEqual([save_event(e) for e in one_session()], [True] * 5)
        self.assertEqual([save_event(e) for e in one_session()], [False] * 5)
        self.assertEqual(self.count(), 5)

    def test_unlinked_charger_or_invalid_transition_stores_nothing(self):
        with self.assertRaises(duckdb.ConstraintException):  # not an Assignment 1 charger_id
            save_event(event(9, "price_update", 0, {"price_per_kwh": 0.5}, charger="999"))
        with self.assertRaises(ValueError):  # meter for a session that never started
            save_event(event(10, "meter", 2, {"power_kw": 5.0, "energy_kwh": 0.1}, session="ghost"))
        self.assertEqual(self.count(), 0)
        self.assertTrue(all(save_event(e) for e in one_session()))

    def test_restart_rebuilds_state_from_stored_events(self):
        events = one_session()
        for e in events[:3]:
            save_event(e)
        duckdb_utils.close_connection()
        prepare_event_storage()  # Empty memory, as after a process restart.
        self.assertFalse(save_event(events[0]))
        self.assertTrue(save_event(events[3]))
        self.assertTrue(save_event(events[4]))  # Would fail against an empty EVChargerState.
        self.assertEqual(self.charger_state()[2], 0)  # active sessions

    def test_event_type_enum_is_declared_in_the_publishers_order(self):
        self.assertEqual(tuple(duckdb_utils.fetch_one("SELECT enum_range(NULL::charger_event_type)")[0]),
                         EVENT_TYPE_ORDER)

    def test_same_time_events_read_back_in_publisher_order(self):
        handover = same_time_handover()
        for e in reversed(handover):  # Stored out of order on purpose; the query must sort them.
            self.dao.insert_event(e)
        self.assertEqual([e.id for e in self.dao.list_events("run-1", 42)], [e.id for e in handover])

    def test_restart_rebuilds_a_same_time_connector_handover(self):
        handover = same_time_handover()
        self.assertTrue(all(save_event(e) for e in handover))
        duckdb_utils.close_connection()
        prepare_event_storage()
        # Rebuilt correctly, s1 has ended and s2 holds connector 1, so s2's next reading is accepted.
        self.assertTrue(save_event(event(30, "meter", 6, {"power_kw": 7.0, "energy_kwh": 0.1}, session="s2")))
        self.assertEqual(self.charger_state()[2], 1)  # active sessions

    def charger_state(self):
        row = duckdb_utils.fetch_one(
            "SELECT price_per_kwh, wholesale_per_kwh, active_sessions, last_event_id, last_event_type "
            "FROM charger_state WHERE run_id = 'run-1' AND charger_id = 42")
        return row and (*row[:3], row[3].hex, row[4])

    def connector_states(self):
        return [(*row[:5], row[5].hex, row[6]) for row in duckdb_utils.fetch_all(
            "SELECT connector_no, status, session_id, power_kw, energy_kwh, last_event_id, last_event_type "
            "FROM connector_state WHERE run_id = 'run-1' AND charger_id = 42 ORDER BY connector_no")]

    def test_latest_charger_and_connector_state_follow_each_event(self):
        price, start, meter1, meter2, end = one_session()
        save_event(price)
        self.assertEqual(self.charger_state(), (Decimal("0.6000"), -0.02, 0, price.id, "price_update"))
        self.assertEqual(self.connector_states(), [])  # Price events are charger-level.
        save_event(start)
        self.assertEqual(self.charger_state(), (Decimal("0.6000"), -0.02, 1, start.id, "session_start"))
        self.assertEqual(self.connector_states(), [(1, "occupied", "s1", None, None, start.id, "session_start")])
        save_event(meter1)
        save_event(meter2)
        self.assertEqual(self.connector_states(), [(1, "occupied", "s1", 48.0, 1.6, meter2.id, "meter")])
        self.assertEqual(self.charger_state()[2:], (1, meter2.id, "meter"))
        save_event(end)
        self.assertEqual(self.charger_state(), (Decimal("0.6000"), -0.02, 0, end.id, "session_end"))
        self.assertEqual(self.connector_states(), [(1, "available", None, None, None, end.id, "session_end")])
        # Both state rows link to the Assignment 1 charger and to their latest stored event.
        self.assertEqual(duckdb_utils.fetch_all(
            "SELECT l.station_name, e.event_type FROM connector_state AS s "
            "JOIN charger_location AS l ON l.charger_id = s.charger_id "
            "JOIN charger_event AS e ON e.event_id = s.last_event_id"), [("Test Station", "session_end")])

    def test_each_connector_keeps_its_own_state(self):
        for e in (event(41, "session_start", 1, {"price_per_kwh": 0.6}, session="a", connector=1),
                  event(42, "session_start", 1, {"price_per_kwh": 0.6}, session="b", connector=2),
                  event(43, "meter", 2, {"power_kw": 11.0, "energy_kwh": 0.2}, session="b", connector=2),
                  event(44, "session_end", 3, {"charge_end_ts": "2026-09-15T10:03:00+10:00", "charge_minutes": 2.0,
                                                "energy_kwh": 0.3, "price_per_kwh": 0.6, "cost_aud": 0.18},
                        session="a", connector=1)):
            self.assertTrue(save_event(e))
        self.assertEqual(self.connector_states(), [
            (1, "available", None, None, None, uuid.UUID(int=44).hex, "session_end"),
            (2, "occupied", "b", 11.0, 0.2, uuid.UUID(int=43).hex, "meter"),
        ])
        self.assertEqual(self.charger_state()[2:], (1, uuid.UUID(int=44).hex, "session_end"))

    def test_schema_keys_and_indexes(self):
        primary_keys = dict(duckdb_utils.fetch_all(
            "SELECT table_name, constraint_column_names FROM duckdb_constraints() "
            "WHERE constraint_type = 'PRIMARY KEY' AND table_name IN ('charger_state', 'connector_state')"))
        self.assertEqual(primary_keys, {"charger_state": ["charger_id"],
                                        "connector_state": ["charger_id", "connector_no"]})
        self.assertEqual(sorted(duckdb_utils.fetch_all(
            "SELECT table_name, trim(expressions, '[]') FROM duckdb_indexes() WHERE table_name IN "
            "('charger_event', 'charger_state', 'connector_state')")), sorted([
            ("charger_event", "event_type"), ("charger_event", "event_ts"), ("charger_event", "charger_id"),
            ("charger_event", "connector_no"), ("charger_state", "price_updated_ts"),
            ("connector_state", "charger_id"), ("connector_state", "run_id"),
            ("connector_state", "session_start_ts"), ("connector_state", "status"),
        ]))

    def test_a_new_run_takes_over_the_one_row_per_charger(self):
        save_event(one_session()[0])  # run-1 price 0.6
        save_event(event(50, "session_start", 1, {"price_per_kwh": 0.7}, run_id="run-2"))
        self.assertEqual(duckdb_utils.fetch_all(
            "SELECT run_id, price_per_kwh, wholesale_per_kwh, price_updated_ts IS NULL, active_sessions "
            "FROM charger_state"), [("run-2", None, None, True, 1)])  # run-1's price is not carried over
        self.assertEqual(duckdb_utils.fetch_all("SELECT run_id, charger_id, connector_no, status FROM connector_state"),
                         [("run-2", 42, 1, "occupied")])

    def test_the_same_connector_number_on_two_chargers_is_two_rows(self):
        save_event(event(60, "session_start", 1, {"price_per_kwh": 0.6}, session="a"))
        save_event(event(61, "session_start", 1, {"price_per_kwh": 0.6}, session="b", charger="7"))
        self.assertEqual(duckdb_utils.fetch_all(
            "SELECT charger_id, connector_no, session_id FROM connector_state ORDER BY charger_id"),
            [(7, 1, "b"), (42, 1, "a")])

    def test_duplicates_and_rejected_events_leave_the_state_unchanged(self):
        for e in one_session()[:3]:
            save_event(e)
        before = (self.charger_state(), self.connector_states())
        self.assertFalse(any(save_event(e) for e in one_session()[:3]))
        with self.assertRaises(ValueError):
            save_event(event(10, "meter", 4, {"power_kw": 5.0, "energy_kwh": 0.1}, session="ghost"))
        self.assertEqual((self.charger_state(), self.connector_states()), before)

    def test_event_and_state_commit_together(self):
        with patch.object(EVChargerEventDAO, "update_latest_state", side_effect=RuntimeError("disk full")), \
                self.assertRaisesRegex(RuntimeError, "disk full"):
            save_event(one_session()[0])
        self.assertEqual(self.count(), 0)  # The event insert was rolled back with the failed update.
        self.assertTrue(all(save_event(e) for e in one_session()))
        self.assertEqual(self.charger_state()[3:], (uuid.UUID(int=5).hex, "session_end"))

    def test_ensure_refuses_an_outdated_event_schema(self):
        save_event(one_session()[0])
        duckdb_utils.execute("DROP TABLE connector_state")
        with self.assertRaisesRegex(RuntimeError, "Outdated event schema"):
            EVChargerEventDAO().ensure_tables()
        self.assertEqual(self.count(), 1)  # Nothing was dropped.

    def test_ensure_keeps_events_but_create_resets_them(self):
        save_event(one_session()[0])
        self.dao.ensure_tables()
        self.assertEqual(self.count(), 1)
        self.dao.create_tables()
        self.assertEqual(self.count(), 0)

    def test_missing_assignment1_tables_give_a_clear_error(self):
        duckdb_utils.close_connection()
        self.db_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "main_ass_1.py"):
            prepare_event_storage()

    def test_assignment1_loader_refuses_a_database_with_event_tables(self):
        from pipeline import data_load_script
        save_event(one_session()[0])
        duckdb_utils.close_connection()
        with patch.object(data_load_script, "DB_DATA", self.db_path), \
                self.assertRaisesRegex(RuntimeError, "Assignment 2 tables"):
            data_load_script.nsw_evc_load()
        reopened = duckdb.connect(str(self.db_path), read_only=True)  # Nothing was dropped.
        self.assertEqual(reopened.execute("SELECT count(*) FROM charger_event").fetchone()[0], 1)
        reopened.close()


class SubscriberCallbackTests(unittest.TestCase):
    """sub_database_update, the database-update subscriber's callback; save_event is replaced."""

    def test_each_outcome_is_logged(self):
        with patch.object(save_subscribed_data, "save_event", side_effect=[True, False]), \
                redirect_stdout(io.StringIO()) as stdout:
            for _ in range(2):
                save_subscribed_data.sub_database_update(one_session()[0])
        self.assertEqual([line.split()[1] for line in stdout.getvalue().splitlines()], ["stored", "duplicate"])

    def test_a_failure_is_reported_and_ends_the_subscriber(self):
        failures = []
        with patch.object(save_subscribed_data, "save_event", side_effect=RuntimeError("disk full")), \
                redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                save_subscribed_data.sub_database_update(one_session()[0], on_failure=lambda: failures.append(1))
        self.assertEqual(failures, [1])
        self.assertIn("FATAL persistence failure", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
