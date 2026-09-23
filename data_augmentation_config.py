"""Task 3 configuration and the team's reserved ColumnCleaner interfaces.

Task 2 owns nsw_evc_cleaning_config.py. This module only consumes its CSV
contract; importing it never runs cleaning, matching, or network requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
COORDINATE_THRESHOLD_M = 500.0
AUTO_COORDINATE_THRESHOLD_M = 100.0
MIN_NEAREST_GAP_M = 20.0
ADDRESS_THRESHOLD = 0.85
STREET_THRESHOLD = 0.75
FULL_ADDRESS_THRESHOLD = 0.88
NEW_EXTERNAL_ATTRIBUTE_NAMES = frozenset({
    "plug_types", "connector_types_normalized", "opening_hours", "access_condition",
    "accessibility", "network", "status_counts", "status", "is_operational",
    "operational_status", "usage_cost", "general_comments", "is_free",
    "allows_card_payment", "allows_reservation", "pricing_info", "power_kw_min",
    "power_kw_max", "dc_port_count", "total_port_count",
})


@dataclass(frozen=True)
class Task3Config:
    input_file: Path = ROOT / "clean_src_data/nsw_ev_charging.csv"
    output_file: Path = ROOT / "aug_data/nsw_ev_charging.csv"
    result_dir: Path = ROOT / "result_data"
    snapshot_dir: Path = ROOT / "result_data"
    web_review_dir: Path = ROOT / "result_data/task3_final_multisource_output"
    raw_file: Path | None = ROOT / "src_data/nsw_ev_charging.csv"
    boundary_file: Path = ROOT / "src_data/SA4_2026_AUST_SHP_GDA2020.zip"

    @property
    def matches_file(self) -> Path:
        return self.result_dir / "task3_multisource_matches.csv"

    @property
    def audit_dir(self) -> Path:
        return self.result_dir / "task3_final_multisource_output"

    @property
    def audit_file(self) -> Path:
        return self.audit_dir / "task3_multisource_final_audit.csv"


TASK3_FINAL_AUDIT_FILE = Task3Config().audit_file


def display_path(path: Path) -> str:
    """Use portable repository paths, or an absolute path for custom inputs."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(Path(path).resolve())


def read_task2_output(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={
        "PCODE": "string", "PCODE_ORIGINAL": "string", "SA4_CODE26": "string",
    })
    required = {
        "Station_name", "Station_address", "Operator", "Number_of_plugs",
        "Charger_Type", "Charger_rating", "Latitude", "Longitude",
        "LGANAME", "PCODE", "Source",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Task 2 output is missing columns: {sorted(missing)}")
    dc = frame["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")
    if not dc.any():
        raise ValueError("Task 2 output contains no DC records.")
    coordinates = frame.loc[dc, ["Latitude", "Longitude"]].apply(pd.to_numeric, errors="coerce")
    if not (coordinates["Latitude"].between(-90, 90) & coordinates["Longitude"].between(-180, 180)).all():
        raise ValueError("Task 2 DC coordinates must be finite WGS84 latitude/longitude values.")
    return frame


def matching_input(settings: Task3Config) -> pd.DataFrame:
    """Keep postcode-repair evidence even for the teammate's older CSV schema.

    Optional raw provenance is used only after verifying row order by coordinates
    and charger type. It is not required for matching or attribute enrichment.
    The Task 2 file and its fields are never modified.
    """
    frame = read_task2_output(settings.input_file)
    if "PCODE_ORIGINAL" not in frame and settings.raw_file and settings.raw_file.exists():
        raw = pd.read_csv(settings.raw_file, dtype={"PCODE": "string"})
        aligned = len(raw) == len(frame)
        if aligned:
            for column in ("Latitude", "Longitude", "Charger_Type"):
                aligned = aligned and raw[column].equals(frame[column])
        if aligned:
            original = raw["PCODE"].str.extract(r"(\d{4})", expand=False).fillna("")
            frame["PCODE_ORIGINAL"] = original
            frame["PCODE_REPAIRED_FROM_ADDRESS"] = original.ne(frame["PCODE"].fillna(""))
    return frame


def GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE(aug_df, audit_file=None):
    from data_utils.multisource_augmentation import augmentation_cleaners
    return augmentation_cleaners(aug_df, Path(audit_file) if audit_file else TASK3_FINAL_AUDIT_FILE)


def GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df, audit_file=None):
    """The originally reserved interface now supplies accepted multi-source fields."""
    return GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE(aug_df, audit_file)


def get_ocm_details(fact_df):
    """Retained OCM-only baseline interface; not the final multi-source pipeline."""
    from data_utils.ocm_reference import get_ocm_details as ocm_details
    return ocm_details(fact_df)
