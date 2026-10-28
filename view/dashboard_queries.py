"""Read-only, run-isolated Assignment 2 queries for the NiceGUI dashboard."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

EVENT_TABLES = frozenset(("charger_event", "charger_state", "connector_state"))


@dataclass(frozen=True)
class MeterPoint:
    event_ts: datetime
    energy_kwh: float


@dataclass(frozen=True)
class PricePoint:
    event_ts: datetime
    price_per_kwh: float


@dataclass(frozen=True)
class ActiveSession:
    charger_id: int
    connector_no: int
    session_id: str
    session_start_ts: datetime | None
    price_per_kwh: float | None
    energy_kwh: float | None
    soc_pct: float | None
    vehicle_model: str | None = None
    power_kw: float | None = None
    last_event_ts: datetime | None = None
    session_end_ts: datetime | None = None
    delivered_energy_kwh: float | None = None
    recorded_cost_aud: float | None = None
    duration_minutes: float | None = None

    @property
    def key(self) -> tuple[int, int, str]:
        return self.charger_id, self.connector_no, self.session_id


@dataclass(frozen=True)
class ChargerLiveState:
    price_per_kwh: float | None
    active_sessions: int
    last_event_ts: datetime | None
    price_updated_ts: datetime | None = None

    @property
    def status(self) -> str:
        return "Charging" if self.active_sessions else "Available"


@dataclass(frozen=True)
class StationHistory:
    completed_sessions: int = 0
    delivered_energy_kwh: float | None = None
    recorded_cost_aud: float | None = None
    average_duration_minutes: float | None = None
    total_events: int = 0
    price_points: tuple[PricePoint, ...] = ()


@dataclass(frozen=True)
class DashboardAnalytics:
    total_events: int | None = None
    stations_with_event_data: int | None = None
    event_type_counts: dict[str, int] = field(default_factory=dict)
    top_station_sessions: tuple[tuple[int, int], ...] = ()
    delivered_energy_kwh: float | None = None
    recorded_cost_aud: float | None = None
    average_duration_minutes: float | None = None
    station_history: dict[int, StationHistory] = field(default_factory=dict)


@dataclass(frozen=True)
class DashboardEventSnapshot:
    run_ids: tuple[str, ...]
    run_id: str | None
    live_states: dict[int, ChargerLiveState]
    active_sessions: tuple[ActiveSession, ...]
    meter_points: dict[tuple[int, int, str], tuple[MeterPoint, ...]]
    completed_sessions: int | None
    active_session_count: int | None
    average_price_per_kwh: float | None
    last_event_ts: datetime | None
    analytics: DashboardAnalytics = field(default_factory=DashboardAnalytics)
    completed_session_records: tuple[ActiveSession, ...] = ()

    @property
    def has_event_data(self) -> bool:
        return self.run_id is not None

    @classmethod
    def no_event_data(cls) -> "DashboardEventSnapshot":
        return cls((), None, {}, (), {}, None, None, None, None)


class DashboardQueryService:
    """Queries only through the caller-owned read connection; never writes schema/data."""
    def __init__(self, repository): self.repository = repository

    def has_complete_event_schema(self) -> bool:
        return EVENT_TABLES <= {row["table_name"] for row in self.repository.fetch_all("SELECT table_name FROM duckdb_tables()")}

    def list_run_ids(self) -> tuple[str, ...]:
        # Yeh's state tables deliberately retain only the latest run per
        # charger/connector. The immutable event log is the only correct
        # source for historical Run selection.
        rows = self.repository.fetch_all("SELECT run_id, max(event_ts) AS last_event_ts FROM charger_event GROUP BY run_id ORDER BY last_event_ts DESC, run_id")
        return tuple(row["run_id"] for row in rows)

    def load_snapshot(self, requested_run_id: str | None = None) -> DashboardEventSnapshot:
        if not self.has_complete_event_schema(): return DashboardEventSnapshot.no_event_data()
        run_ids = self.list_run_ids(); run_id = requested_run_id if requested_run_id in run_ids else (run_ids[0] if run_ids else None)
        if run_id is None: return DashboardEventSnapshot(run_ids, None, {}, (), {}, 0, 0, None, None, DashboardAnalytics(0, 0))
        rows = self.repository.fetch_all("""SELECT event_id, event_type, event_ts, charger_id, connector_no,
            session_id, price_per_kwh, vehicle_model, power_kw, energy_kwh, soc_pct,
            charge_minutes, cost_aud
            FROM charger_event WHERE run_id=? ORDER BY event_ts, event_type, event_id""", [run_id])

        # Replaying the selected immutable event stream is intentional. Yeh's
        # current state PK is charger/connector only, so those mutable rows
        # cannot represent an older run when runs share a charger.
        prices: dict[int, tuple[float, datetime]] = {}
        latest_event: dict[int, datetime] = {}
        active: dict[tuple[int, int, str], dict] = {}
        completed_records: list[ActiveSession] = []
        meter_points: dict[tuple[int, int, str], list[MeterPoint]] = {}
        histories: dict[int, dict] = {}
        counts: dict[str, int] = {}
        for row in rows:
            charger_id, event_type, ts = int(row["charger_id"]), row["event_type"], row["event_ts"]
            latest_event[charger_id] = ts
            counts[event_type] = counts.get(event_type, 0) + 1
            history = histories.setdefault(charger_id, dict(completed=0, energy=[], cost=[], duration=[], total=0, prices=[]))
            history["total"] += 1
            if event_type == "price_update" and row["price_per_kwh"] is not None:
                value = float(row["price_per_kwh"])
                prices[charger_id] = value, ts
                history["prices"].append(PricePoint(ts, value))
            if event_type == "session_start":
                key = charger_id, int(row["connector_no"]), row["session_id"]
                active[key] = dict(start=ts, price=row["price_per_kwh"], vehicle=row.get("vehicle_model"),
                                   power=None, energy=None, soc=None, last=ts)
                meter_points[key] = []
            elif event_type == "meter":
                key = charger_id, int(row["connector_no"]), row["session_id"]
                session = active.get(key)
                if session is not None:
                    session.update(power=row["power_kw"], energy=row["energy_kwh"], soc=row["soc_pct"], last=ts)
                    if row["energy_kwh"] is not None:
                        meter_points[key].append(MeterPoint(ts, float(row["energy_kwh"])))
            elif event_type == "session_end":
                key = charger_id, int(row["connector_no"]), row["session_id"]
                session = active.pop(key, None)
                # Retain immutable, session-keyed Meter events for historical curves.
                if session is not None:
                    completed_records.append(ActiveSession(
                        charger_id, key[1], key[2], session["start"],
                        None if session["price"] is None else float(session["price"]),
                        None if session["energy"] is None else float(session["energy"]),
                        None if session["soc"] is None else float(session["soc"]), session["vehicle"],
                        None if session["power"] is None else float(session["power"]), ts, ts,
                        None if row["energy_kwh"] is None else float(row["energy_kwh"]),
                        None if row["cost_aud"] is None else float(row["cost_aud"]),
                        None if row["charge_minutes"] is None else float(row["charge_minutes"])))
                if not meter_points.get(key):
                    meter_points.pop(key, None)
                history["completed"] += 1
                for name, column in (("energy", "energy_kwh"), ("cost", "cost_aud"), ("duration", "charge_minutes")):
                    if row[column] is not None:
                        history[name].append(float(row[column]))

        sessions = tuple(ActiveSession(charger_id, connector_no, session_id, value["start"],
                         None if value["price"] is None else float(value["price"]),
                         None if value["energy"] is None else float(value["energy"]),
                         None if value["soc"] is None else float(value["soc"]), value["vehicle"],
                         None if value["power"] is None else float(value["power"]), value["last"])
                         for (charger_id, connector_no, session_id), value in sorted(active.items()))
        active_by_charger: dict[int, int] = {}
        for session in sessions:
            active_by_charger[session.charger_id] = active_by_charger.get(session.charger_id, 0) + 1
        live_states = {charger_id: ChargerLiveState(prices.get(charger_id, (None, None))[0],
                       active_by_charger.get(charger_id, 0), ts,
                       prices.get(charger_id, (None, None))[1])
                       for charger_id, ts in latest_event.items()}
        station_history = {charger_id: StationHistory(values["completed"],
                           sum(values["energy"]) if values["energy"] else None,
                           sum(values["cost"]) if values["cost"] else None,
                           sum(values["duration"]) / len(values["duration"]) if values["duration"] else None,
                           values["total"], tuple(values["prices"]))
                           for charger_id, values in histories.items()}
        completed = sum(values["completed"] for values in histories.values())
        energy_values = [value for values in histories.values() for value in values["energy"]]
        cost_values = [value for values in histories.values() for value in values["cost"]]
        energy = sum(energy_values) if energy_values else None
        costs = sum(cost_values) if cost_values else None
        durations = [duration for values in histories.values() for duration in values["duration"]]
        latest_prices = [state.price_per_kwh for state in live_states.values() if state.price_per_kwh is not None]
        top = tuple(sorted(((charger_id, values["completed"]) for charger_id, values in histories.items() if values["completed"]), key=lambda item: (-item[1], item[0]))[:10])
        analytics = DashboardAnalytics(len(rows), len(latest_event), counts, top, energy, costs,
            sum(durations) / len(durations) if durations else None, station_history)
        return DashboardEventSnapshot(run_ids, run_id, live_states, sessions,
            {key: tuple(points) for key, points in meter_points.items()}, completed, len(sessions),
            sum(latest_prices) / len(latest_prices) if latest_prices else None,
            max(latest_event.values(), default=None), analytics,
            tuple(sorted(completed_records, key=lambda s: s.session_end_ts or s.session_start_ts, reverse=True)))
