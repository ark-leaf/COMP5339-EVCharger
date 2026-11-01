# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Four MQTT event types. The CSV adapter must supply numbers and timezone offsets."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timezone
import json
import math

from event.y_event import YEvent, _timestamp

# Required and optional payload fields; prices are AUD/kWh, energy is cumulative kWh.
PAYLOAD_FIELDS = {
    "price_update": ({"price_per_kwh"}, {"wholesale_per_kwh"}),
    "session_start": ({"price_per_kwh"}, {"vehicle_model"}),
    "meter": ({"power_kw", "energy_kwh"}, {"voltage_v", "current_a", "soc_pct"}),
    "session_end": ({"charge_end_ts", "charge_minutes", "energy_kwh", "price_per_kwh", "cost_aud"},
                    {"avg_kw", "peak_kw"}),
}
# Publisher's order for one charger's events at the same time: final meter readings and
# session ends come before new starts, so a connector is free before it is reused.
EVENT_TYPE_ORDER = ("price_update", "meter", "session_end", "session_start")

@dataclass
class EVChargerStateEvent(YEvent):
    connector_id: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if "charge_end_ts" in self.payload:
            self.payload["charge_end_ts"] = _timestamp(self.payload["charge_end_ts"])
        self._validate_payload()

    @property
    def charger_id(self) -> int:
        """Assignment 1 charger_location.charger_id; YEvent.object_id carries it as text."""
        return int(self.object_id)

    def _validate_payload(self):
        # One canonical text per charger ("42", never "042", " 42" or "+42"), so topics, state
        # and stored rows all agree with charger_id.
        if not (self.object_id.isascii() and self.object_id.isdigit() and self.object_id[0] != "0"):
            raise ValueError(f"object_id must be a charger_id written as a positive integer: {self.object_id!r}")
        if self.type not in PAYLOAD_FIELDS:
            raise ValueError(f"unsupported event type: {self.type}")
        if self.type == "price_update":
            if self.connector_id is not None or self.session_id is not None:
                raise ValueError("price events are charger-level")
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
        self._validate_payload()
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
