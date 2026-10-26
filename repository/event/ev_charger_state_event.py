# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Four MQTT event types. The CSV adapter must supply numbers and timezone offsets."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math

# Required and optional payload fields; prices are AUD/kWh, energy is cumulative kWh.
PAYLOAD_FIELDS = {
    "price_update": ({"price_per_kwh"}, {"wholesale_per_kwh"}),
    "session_start": ({"price_per_kwh"}, {"vehicle_model"}),
    "meter": ({"power_kw", "energy_kwh"}, {"voltage_v", "current_a", "soc_pct"}),
    "session_end": ({"charge_end_ts", "charge_minutes", "energy_kwh", "price_per_kwh", "cost_aud"},
                    {"avg_kw", "peak_kw"}),
}


def _timestamp(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamps must include an explicit timezone offset")
    return value.astimezone(timezone.utc)


@dataclass
class EVChargerStateEvent:
    run_id: str
    event_id: str
    type: str
    ts: datetime
    station_id: str
    schema_version: int = 1
    connector_id: int | None = None  # Simulated port number, not charger_connector's PK.
    session_id: str | None = None
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if type(self.station_id) is int and self.station_id > 0:
            self.station_id = str(self.station_id)
        self.ts = _timestamp(self.ts)
        self.payload = dict(self.payload)
        if "charge_end_ts" in self.payload:
            self.payload["charge_end_ts"] = _timestamp(self.payload["charge_end_ts"])
        self.validate()

    def validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1 or self.type not in PAYLOAD_FIELDS:
            raise ValueError("unsupported event type or schema version")
        if any(not isinstance(v, str) or not v.strip() for v in (self.run_id, self.event_id, self.station_id)):
            raise ValueError("run_id, event_id and station_id must be non-empty strings")
        _timestamp(self.ts)
        if self.type == "price_update":
            if self.connector_id is not None or self.session_id is not None:
                raise ValueError("price events are station-level")
        elif (type(self.connector_id) is not int or self.connector_id <= 0
              or not isinstance(self.session_id, str) or not self.session_id.strip()):
            raise ValueError("session events require connector_id and session_id")
        required, optional = PAYLOAD_FIELDS[self.type]
        if not required <= self.payload.keys() or self.payload.keys() - required - optional:
            raise ValueError(f"invalid payload fields for {self.type}")
        for name, value in self.payload.items():
            if name == "charge_end_ts":
                if _timestamp(value) > self.ts:
                    raise ValueError("charging cannot finish after unplugging")
            elif name == "vehicle_model":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("vehicle_model must be a non-empty string")
            elif (type(value) not in (int, float) or not math.isfinite(value)
                  or (name != "wholesale_per_kwh" and value < 0)):
                raise ValueError(f"invalid numeric value for {name}")
        if self.payload.get("soc_pct", 0) > 100:
            raise ValueError("soc_pct cannot exceed 100")

    def to_dict(self) -> dict:
        self.validate()
        result = asdict(self)
        result["ts"] = self.ts.isoformat()
        if "charge_end_ts" in result["payload"]:
            result["payload"]["charge_end_ts"] = _timestamp(result["payload"]["charge_end_ts"]).isoformat()
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, message) -> EVChargerStateEvent:
        return cls(**message)

    @classmethod
    def from_json(cls, message) -> EVChargerStateEvent:
        return cls.from_dict(json.loads(message))
