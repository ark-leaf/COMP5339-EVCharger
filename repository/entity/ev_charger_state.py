# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Current state only. B must store/deduplicate events before applying them here."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..event.ev_charger_state_event import EVChargerStateEvent, _timestamp


@dataclass
class EVChargerState:
    station_id: str
    run_id: str
    price_per_kwh: float | None = field(default=None, init=False)
    last_event_ts: datetime | None = field(default=None, init=False)
    active_sessions: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.station_id = str(self.station_id)

    @property
    def active_session_count(self) -> int:
        """Open sessions include the idle period before unplugging."""
        return len(self.active_sessions)

    @property
    def occupied_connector_ids(self) -> tuple:
        return tuple(sorted(s["connector_id"] for s in self.active_sessions.values()))

    def apply(self, event: EVChargerStateEvent) -> bool:
        """Apply one ordered, deduplicated event; invalid transitions raise ValueError."""
        event.validate()
        if event.station_id != self.station_id or event.run_id != self.run_id:
            raise ValueError("event belongs to another station or run")
        if self.last_event_ts is not None and event.ts < self.last_event_ts:
            raise ValueError("events must be applied in event-time order")
        if event.type == "price_update":
            self.price_per_kwh = event.payload["price_per_kwh"]
        elif event.type == "session_start":
            if event.session_id in self.active_sessions or event.connector_id in self.occupied_connector_ids:
                raise ValueError("session already exists or connector is occupied")
            self.active_sessions[event.session_id] = {
                "connector_id": event.connector_id, "start_ts": event.ts.isoformat(),
                "price_per_kwh": event.payload["price_per_kwh"],
                "vehicle_model": event.payload.get("vehicle_model"), "latest_meter": None,
            }
        else:
            session = self.active_sessions.get(event.session_id)
            if session is None or session["connector_id"] != event.connector_id:
                raise ValueError("unknown session or incorrect connector")
            previous = session["latest_meter"]
            if event.type == "meter":
                if previous and event.payload["energy_kwh"] < previous["payload"]["energy_kwh"]:
                    raise ValueError("cumulative meter energy cannot decrease")
                session["latest_meter"] = event.to_dict()
            else:
                last_reading = previous["ts"] if previous else session["start_ts"]
                if _timestamp(event.payload["charge_end_ts"]) < _timestamp(last_reading):
                    raise ValueError("charging ended before the start or last meter reading")
                del self.active_sessions[event.session_id]
        self.last_event_ts = event.ts
        return True

    def to_dict(self) -> dict:
        result = asdict(self)
        result["last_event_ts"] = self.last_event_ts.isoformat() if self.last_event_ts else None
        result["active_session_count"] = self.active_session_count
        result["occupied_connector_ids"] = list(self.occupied_connector_ids)
        return result
