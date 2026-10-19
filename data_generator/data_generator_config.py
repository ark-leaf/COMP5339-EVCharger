# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Settings for the generator wrapper; simulation constants stay in the supplied script."""
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from pathlib import Path

from config import DATA_ROOT
from pipeline.data_load.nsw_evc_load_config import DB_DATA

# NEM market time stays on AEST (UTC+10), including during Sydney daylight saving.
NEM_TIME = timezone(timedelta(hours=10))


@dataclass
class GenerationConfig:
    db_path: Path = DB_DATA
    output_dir: Path = DATA_ROOT / "ass2_generated"
    # A completed month is more likely to have a complete AEMO monthly file.
    start: str = field(default_factory=lambda: (
        date.today().replace(day=1) - timedelta(days=1)).replace(day=15).isoformat())
    days: int = 14
    seed: int = 5339
    meter_every: int = 1
    region: str = "NSW1"
    default_site_type: str = "urban"  # Simulation assumption, not a geographic classification.
    sessions_per_connector_day: tuple = (4.0, 3.0)
    mean_idle_min: float = 3.0
    pass_through: float = 1.0
    peak_adder: float = .10
    price_floor: float = .20
    price_cap: float = 1.20
    elasticity: float = -.5

    def __post_init__(self):
        self.db_path, self.output_dir = Path(self.db_path), Path(self.output_dir)
        date.fromisoformat(self.start)
        if self.days < 1 or self.meter_every < 1:
            raise ValueError("days and meter_every must be positive")
