from abc import ABC, abstractmethod
from dataclasses import field, dataclass
from datetime import datetime, timezone
import json
from typing import Any, TypeVar

T = TypeVar("T", bound="YEvent")


@dataclass
class YEvent(ABC):
    run_id: str
    id: str
    type: str
    ts: datetime
    object_id: str
    schema_version: int = 1
    session_id: str | None = None
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        self.ts = _timestamp(self.ts)
        self.payload = dict(self.payload)
        if "charge_end_ts" in self.payload:
            self.payload["charge_end_ts"] = _timestamp(self.payload["charge_end_ts"])
        self._validate()

    def _validate(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported schema version")
        if any(not isinstance(v, str) or not v.strip() for v in (self.run_id, self.id, self.object_id)):
            raise ValueError("run_id, id and object_id must be non-empty strings")
        _timestamp(self.ts)

    @abstractmethod
    def to_json(self) -> str:
        pass

    @classmethod
    def from_dict(cls: type[T], message: dict[str, Any]) -> T:
        """Build the subclass this is called on, e.g. EVChargerStateEvent.from_dict(...)."""
        return cls(**message)

    @classmethod
    def from_json(cls: type[T], message: str | bytes) -> T:
        return cls.from_dict(json.loads(message))


def _timestamp(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamps must include an explicit timezone offset")
    return value.astimezone(timezone.utc)
