"""Dashboard view models, and the per-run model that keeps a page's view models current.

A page builds a DashboardRunModel from one run's stored events (read through
EVChargerEventDAO) and then applies that run's MQTT events to it. Both go through
apply(), so stored and live events are rendered the same way.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from entity.ev_charger_state import EVChargerState
from event.ev_charger_state_event import EVChargerStateEvent


@dataclass(frozen=True)
class MeterPoint:
    event_ts: datetime
    energy_kwh: float
    power_kw: float | None = None
    soc_pct: float | None = None


@dataclass(frozen=True)
class PricePoint:
    event_ts: datetime
    price_per_kwh: float
    wholesale_per_kwh: float | None = None


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
    charge_end_ts: datetime | None = None  # When charging stopped; session_end_ts is the unplug time.

    @property
    def key(self) -> tuple[int, int, str]:
        return self.charger_id, self.connector_no, self.session_id

    @property
    def span_end_ts(self) -> datetime | None:
        """The unplug time or, for a session still plugged in, its latest event."""
        return self.session_end_ts or self.last_event_ts or self.session_start_ts


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
class ConnectorView:
    """One connector of a charger in a run: its current session and every session it has had."""
    charger_id: int
    connector_no: int
    sessions: tuple[ActiveSession, ...] = ()  # Oldest first, completed and active.
    meter_points: dict[str, tuple[MeterPoint, ...]] = field(default_factory=dict)  # By session_id.
    has_event_data: bool = False  # The charger has events in the run.

    def event_times(self, session_id: str | None = None) -> tuple[datetime, ...]:
        """When this connector's events happened, oldest first: every session's start, meter
        readings and end, or only those of session_id."""
        times = set()
        for session in self.sessions:
            if session_id is None or session.session_id == session_id:
                times.update(ts for ts in (session.session_start_ts, session.session_end_ts) if ts is not None)
                times.update(point.event_ts for point in self.meter_points.get(session.session_id, ()))
        return tuple(sorted(times))

    @property
    def active(self) -> ActiveSession | None:
        return next((session for session in reversed(self.sessions) if session.session_end_ts is None), None)

    @property
    def completed(self) -> tuple[ActiveSession, ...]:
        return tuple(session for session in self.sessions if session.session_end_ts is not None)

    @property
    def status(self) -> str:
        if not self.has_event_data:
            return "unknown"
        return "charging" if self.active is not None else "available"

    @property
    def last_event_ts(self) -> datetime | None:
        return max((session.last_event_ts for session in self.sessions if session.last_event_ts is not None), default=None)


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

    def connectors(self, charger_id: int, capacity: int | None) -> tuple[ConnectorView, ...]:
        """Connectors 1..capacity of a charger, and any other connector its sessions used, in order."""
        sessions: dict[int, list[ActiveSession]] = {}
        for session in self.completed_session_records + self.active_sessions:
            if session.charger_id == charger_id:
                sessions.setdefault(session.connector_no, []).append(session)
        numbers = set(range(1, capacity + 1)) if isinstance(capacity, int) and capacity > 0 else set()
        has_event_data = charger_id in self.live_states
        views = []
        for number in sorted(numbers | sessions.keys()):
            history = tuple(sorted(sessions.get(number, ()), key=_session_order))
            views.append(ConnectorView(charger_id, number, history,
                                       {session.session_id: self.meter_points.get(session.key, ()) for session in history},
                                       has_event_data))
        return tuple(views)


def _session_order(session: ActiveSession):
    """Sessions by start time; one without a start time sorts first."""
    start = session.session_start_ts
    return start is not None, start


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


def _event_key(event_id: str) -> str:
    """Stored ids come back as UUID hex, while MQTT ids may be hyphenated."""
    try:
        return uuid.UUID(event_id).hex
    except ValueError:
        return event_id


class DashboardRunModel:
    """One run's live state and history, built from stored events and advanced by MQTT events.

    Every event must pass the EVChargerState transition rules the event store applies, so a
    page never shows a transition that storage rejects. Repeated deliveries are ignored by
    event id, and so are chargers outside the page's stations, which the database rejects too.
    """

    def __init__(self, run_id: str, charger_ids: Iterable[int] | None = None):
        self.run_id = run_id
        self._charger_ids = None if charger_ids is None else frozenset(charger_ids)
        self._event_ids: set[str] = set()
        self._states: dict[int, EVChargerState] = {}
        self._prices: dict[int, tuple[float, datetime]] = {}
        self._latest_event: dict[int, datetime] = {}
        self._active: dict[tuple[int, int, str], dict] = {}
        self._completed: list[ActiveSession] = []
        self._meter_points: dict[tuple[int, int, str], list[MeterPoint]] = {}
        self._histories: dict[int, dict] = {}
        self._counts: dict[str, int] = {}

    def apply(self, event: EVChargerStateEvent) -> bool:
        """Advance the model by one event; False if it is for another run, repeated or rejected."""
        event_key, charger_id = _event_key(event.id), event.charger_id
        if (event.run_id != self.run_id or event_key in self._event_ids
                or (self._charger_ids is not None and charger_id not in self._charger_ids)):
            return False
        state = self._states.get(charger_id) or EVChargerState(charger_id, event.run_id)
        try:
            state.apply(event)
        except ValueError:
            return False
        self._states[charger_id] = state
        self._event_ids.add(event_key)
        self._record(event)
        return True

    def _record(self, event: EVChargerStateEvent) -> None:
        charger_id, ts, payload = event.charger_id, event.ts, event.payload
        self._latest_event[charger_id] = ts
        self._counts[event.type] = self._counts.get(event.type, 0) + 1
        history = self._histories.setdefault(charger_id, dict(completed=0, energy=[], cost=[], duration=[], total=0, prices=[]))
        history["total"] += 1
        key = charger_id, event.connector_id, event.session_id
        if event.type == "price_update":
            price = float(payload["price_per_kwh"])
            self._prices[charger_id] = price, ts
            history["prices"].append(PricePoint(ts, price, _optional_float(payload.get("wholesale_per_kwh"))))
        elif event.type == "session_start":
            self._active[key] = dict(start=ts, price=payload["price_per_kwh"], vehicle=payload.get("vehicle_model"),
                                     power=None, energy=None, soc=None, last=ts)
            self._meter_points[key] = []
        elif event.type == "meter":
            session = self._active.get(key)
            if session is not None:
                session.update(power=payload["power_kw"], energy=payload["energy_kwh"], soc=payload.get("soc_pct"), last=ts)
                self._meter_points[key].append(MeterPoint(ts, float(payload["energy_kwh"]), float(payload["power_kw"]),
                                                          _optional_float(payload.get("soc_pct"))))
        else:  # session_end
            session = self._active.pop(key, None)
            if session is not None:
                self._completed.append(ActiveSession(
                    charger_id, event.connector_id, event.session_id, session["start"],
                    _optional_float(session["price"]), _optional_float(session["energy"]),
                    _optional_float(session["soc"]), session["vehicle"], _optional_float(session["power"]), ts, ts,
                    _optional_float(payload.get("energy_kwh")), _optional_float(payload.get("cost_aud")),
                    _optional_float(payload.get("charge_minutes")), payload.get("charge_end_ts")))
            # Retain immutable, session-keyed Meter events for historical curves.
            if not self._meter_points.get(key):
                self._meter_points.pop(key, None)
            history["completed"] += 1
            for name, field_name in (("energy", "energy_kwh"), ("cost", "cost_aud"), ("duration", "charge_minutes")):
                if payload.get(field_name) is not None:
                    history[name].append(float(payload[field_name]))

    def snapshot(self, run_ids: Iterable[str]) -> DashboardEventSnapshot:
        """Render the model; run_ids are the runs the page can select."""
        sessions = tuple(ActiveSession(charger_id, connector_no, session_id, value["start"],
                         _optional_float(value["price"]), _optional_float(value["energy"]),
                         _optional_float(value["soc"]), value["vehicle"], _optional_float(value["power"]), value["last"])
                         for (charger_id, connector_no, session_id), value in sorted(self._active.items()))
        active_by_charger: dict[int, int] = {}
        for session in sessions:
            active_by_charger[session.charger_id] = active_by_charger.get(session.charger_id, 0) + 1
        live_states = {charger_id: ChargerLiveState(self._prices.get(charger_id, (None, None))[0],
                       active_by_charger.get(charger_id, 0), ts,
                       self._prices.get(charger_id, (None, None))[1])
                       for charger_id, ts in self._latest_event.items()}
        histories = self._histories
        station_history = {charger_id: StationHistory(values["completed"],
                           sum(values["energy"]) if values["energy"] else None,
                           sum(values["cost"]) if values["cost"] else None,
                           sum(values["duration"]) / len(values["duration"]) if values["duration"] else None,
                           values["total"], tuple(values["prices"]))
                           for charger_id, values in histories.items()}
        completed = sum(values["completed"] for values in histories.values())
        energy_values = [value for values in histories.values() for value in values["energy"]]
        cost_values = [value for values in histories.values() for value in values["cost"]]
        durations = [duration for values in histories.values() for duration in values["duration"]]
        latest_prices = [state.price_per_kwh for state in live_states.values() if state.price_per_kwh is not None]
        top = tuple(sorted(((charger_id, values["completed"]) for charger_id, values in histories.items() if values["completed"]), key=lambda item: (-item[1], item[0]))[:10])
        analytics = DashboardAnalytics(sum(self._counts.values()), len(self._latest_event), dict(self._counts), top,
            sum(energy_values) if energy_values else None, sum(cost_values) if cost_values else None,
            sum(durations) / len(durations) if durations else None, station_history)
        return DashboardEventSnapshot(tuple(run_ids), self.run_id, live_states, sessions,
            {key: tuple(points) for key, points in self._meter_points.items()}, completed, len(sessions),
            sum(latest_prices) / len(latest_prices) if latest_prices else None,
            max(self._latest_event.values(), default=None), analytics,
            tuple(sorted(self._completed, key=lambda s: s.session_end_ts or s.session_start_ts, reverse=True)))
