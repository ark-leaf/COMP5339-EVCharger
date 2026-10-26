# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Static station data; generation defaults belong in the input adapter."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class EVCharger:
    charger_id: int
    source_objectid: int | None = None
    station_name: str | None = None
    station_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    charger_type: str | None = None
    number_of_plugs: int | None = None
    rating_kw: float | None = None
    operator_name: str | None = None

    def __post_init__(self):
        if type(self.charger_id) is not int or self.charger_id <= 0:
            raise ValueError("charger_id must be a positive database integer")

    @property
    def station_id(self) -> str:
        return str(self.charger_id)

    @classmethod
    def from_record(cls, record) -> EVCharger:
        """Map named SQL columns, preserving NULLs and ignoring extra columns."""
        values = {f.name: record[f.name] for f in fields(cls) if f.name in record}
        for name in ("latitude", "longitude", "rating_kw"):
            if values.get(name) is not None:
                values[name] = float(values[name])
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)
