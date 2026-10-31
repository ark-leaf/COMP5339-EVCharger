from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from config import DB_EVENTS_SCHEMA
from entity.ev_charger_state import EVChargerState
from event.ev_charger_state_event import EVChargerStateEvent
from repository.utils import duckdb_utils

EVENT_TABLES = ("charger_event", "charger_state", "connector_state")

# charger_event stores every payload field in its own column, in this order.
PAYLOAD_COLUMNS = ("price_per_kwh", "wholesale_per_kwh", "vehicle_model", "power_kw", "energy_kwh",
                   "voltage_v", "current_a", "soc_pct", "charge_end_ts", "charge_minutes",
                   "cost_aud", "avg_kw", "peak_kw")
_ENVELOPE_COLUMNS = ("event_id", "run_id", "event_type", "event_ts", "charger_id",
                     "connector_no", "session_id")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_INSERT_EVENT = f"""
    INSERT INTO charger_event ({", ".join(_ENVELOPE_COLUMNS + PAYLOAD_COLUMNS)})
    VALUES ({", ".join("?" * (len(_ENVELOPE_COLUMNS) + len(PAYLOAD_COLUMNS)))})
    ON CONFLICT DO NOTHING
    RETURNING event_id
"""
# Timestamps come back as epoch microseconds, which needs no time zone library. The
# event_type ENUM is declared in EVENT_TYPE_ORDER, so ties sort as the publisher sent them.
_SELECT_EVENT_ROWS = f"""
    SELECT event_id, event_type, epoch_us(event_ts), charger_id, connector_no, session_id,
           {", ".join("epoch_us(charge_end_ts)" if c == "charge_end_ts" else c for c in PAYLOAD_COLUMNS)}
    FROM charger_event
"""
_SELECT_EVENTS = _SELECT_EVENT_ROWS + "WHERE run_id = ? AND charger_id = ? ORDER BY event_ts, event_type"
_SELECT_RUN_EVENTS = _SELECT_EVENT_ROWS + "WHERE run_id = ? ORDER BY event_ts, event_type, charger_id, event_id"
# Runs with stored events, the one reaching the latest simulated time first.
_SELECT_RUN_IDS = "SELECT run_id FROM charger_event GROUP BY run_id ORDER BY max(event_ts) DESC, run_id"
# One row per charger. A price_update (which sets price_updated_ts), or the first event of a
# new run, replaces the price details; other events keep them.
_UPSERT_CHARGER_STATE = """
    INSERT INTO charger_state (run_id, charger_id, price_per_kwh, wholesale_per_kwh, price_updated_ts,
                               active_sessions, last_event_id, last_event_type, last_event_ts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (charger_id) DO UPDATE SET
        run_id = EXCLUDED.run_id,
        price_per_kwh = EXCLUDED.price_per_kwh,
        wholesale_per_kwh = CASE WHEN EXCLUDED.price_updated_ts IS NULL AND EXCLUDED.run_id = charger_state.run_id
                                 THEN charger_state.wholesale_per_kwh ELSE EXCLUDED.wholesale_per_kwh END,
        price_updated_ts = CASE WHEN EXCLUDED.price_updated_ts IS NULL AND EXCLUDED.run_id = charger_state.run_id
                                THEN charger_state.price_updated_ts ELSE EXCLUDED.price_updated_ts END,
        active_sessions = EXCLUDED.active_sessions,
        last_event_id = EXCLUDED.last_event_id,
        last_event_type = EXCLUDED.last_event_type,
        last_event_ts = EXCLUDED.last_event_ts
"""
_UPSERT_CONNECTOR_STATE = """
    INSERT OR REPLACE INTO connector_state (run_id, charger_id, connector_no, status, session_id,
                                            session_start_ts, session_price_per_kwh, vehicle_model,
                                            power_kw, energy_kwh, soc_pct,
                                            last_event_id, last_event_type, last_event_ts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _timestamp(epoch_us: int) -> datetime:
    return _EPOCH + timedelta(microseconds=epoch_us)


def _event(run_id: str, row) -> EVChargerStateEvent:
    """Rebuild a stored event from one _SELECT_EVENT_ROWS row."""
    event_id, kind, ts_us, charger_id, connector, session, *values = row
    payload = {}
    for column, value in zip(PAYLOAD_COLUMNS, values):
        if value is not None:
            payload[column] = (_timestamp(value) if column == "charge_end_ts" else
                               float(value) if isinstance(value, Decimal) else value)
    return EVChargerStateEvent(
        run_id=run_id, id=event_id.hex, type=kind, ts=_timestamp(ts_us), object_id=str(charger_id),
        connector_id=connector, session_id=session, payload=payload)


class EVChargerEventDAO:
    """charger_event access through the shared DuckDB connection in repository.utils.duckdb_utils."""

    def create_tables(self, schema_path: Path = DB_EVENTS_SCHEMA):
        """Drop and recreate the event tables, deleting every stored event."""
        if not duckdb_utils.table_exists("charger_location"):
            raise RuntimeError("Assignment 1 tables are missing; run `python main_ass_1.py --stage load` first")
        duckdb_utils.run_sql_file(schema_path)

    def ensure_tables(self):
        """Create the event tables if none exist yet; stored events are kept."""
        present = [table for table in EVENT_TABLES if duckdb_utils.table_exists(table)]
        if not present:
            self.create_tables()
        elif len(present) < len(EVENT_TABLES):
            raise RuntimeError(f"Outdated event schema (only {present}). Run {DB_EVENTS_SCHEMA.name} or "
                               "EVChargerEventDAO().create_tables() to recreate it; this deletes stored events.")

    def transaction(self):
        """Commit an event and its latest state together: `with dao.transaction(): ...`."""
        return duckdb_utils.transaction()

    def event_exists(self, event_id: str) -> bool:
        return duckdb_utils.fetch_one(
            "SELECT count(*) FROM charger_event WHERE event_id = CAST(? AS UUID)", [event_id])[0] > 0

    def insert_event(self, event: EVChargerStateEvent) -> bool:
        """Insert one event; False if its event_id is already stored. Unknown chargers violate the FK."""
        payload = event.to_dict()["payload"]  # JSON-ready values, e.g. ISO timestamps
        return bool(duckdb_utils.fetch_all(_INSERT_EVENT, [
            event.id, event.run_id, event.type, event.ts.isoformat(), event.charger_id,
            event.connector_id, event.session_id, *(payload.get(c) for c in PAYLOAD_COLUMNS),
        ]))

    def update_latest_state(self, event: EVChargerStateEvent, state: EVChargerState):
        """Rewrite the charger's latest state, and its connector's for session events.

        state is the charger's EVChargerState after applying event, so the stored rows always
        match the transition that was just validated.
        """
        price_update = event.type == "price_update"
        last_event = [event.id, event.type, event.ts.isoformat()]
        duckdb_utils.execute(_UPSERT_CHARGER_STATE, [
            event.run_id, event.charger_id, state.price_per_kwh,
            event.payload.get("wholesale_per_kwh") if price_update else None,
            event.ts.isoformat() if price_update else None,
            state.active_session_count, *last_event,
        ])
        if event.connector_id is None:
            return
        # The session now on this connector; none after session_end frees it.
        session_id, session = next(((sid, s) for sid, s in state.active_sessions.items()
                                    if s["connector_id"] == event.connector_id), (None, None))
        if session is None:
            row = ["available", None, None, None, None, None, None, None]
        else:
            reading = session["latest_meter"]["payload"] if session["latest_meter"] else {}
            row = ["occupied", session_id, session["start_ts"], session["price_per_kwh"],
                   session["vehicle_model"], reading.get("power_kw"), reading.get("energy_kwh"),
                   reading.get("soc_pct")]
        duckdb_utils.execute(_UPSERT_CONNECTOR_STATE, [
            event.run_id, event.charger_id, event.connector_id, *row, *last_event])

    def list_events(self, run_id: str, charger_id: int) -> list[EVChargerStateEvent]:
        """A charger's stored events for one run, in the order they were published."""
        return [_event(run_id, row) for row in duckdb_utils.fetch_all(_SELECT_EVENTS, [run_id, charger_id])]

    def has_tables(self) -> bool:
        """Whether the event tables exist; ensure_tables() creates them before the first save."""
        return all(duckdb_utils.table_exists(table) for table in EVENT_TABLES)

    def list_run_ids(self) -> tuple[str, ...]:
        """Runs with stored events, the one reaching the latest simulated time first."""
        return tuple(row[0] for row in duckdb_utils.fetch_all(_SELECT_RUN_IDS))

    def list_run_events(self, run_id: str) -> list[EVChargerStateEvent]:
        """Every stored event of one run, in the order they were published."""
        return [_event(run_id, row) for row in duckdb_utils.fetch_all(_SELECT_RUN_EVENTS, [run_id])]
