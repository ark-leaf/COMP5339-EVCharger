# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that I wrote/adapted the initial input and postcode checks using
# OpenAI Codex references. Codex also revised configuration, evidence alignment
# and pipeline integration, and assisted with corrections and tests.

"""Task 3 configuration and validated Task 2 input helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    PROJECT_ROOT as ROOT,
    NSW_EV_CHARGING_CLEANED_FILE,
    NSW_EV_CHARGING_AUG_FILE,
    RESULT_DATA_FILE_LOCATION,
    NSW_EV_CHARGING_SRC_FILE,
    AUS_ASGS_LV4_FILE,
)

COORDINATE_THRESHOLD_M = 500.0
# Search up to 500 m; a coordinate-only automatic match must be within 100 m.
# Explicit house/postcode conflicts and ambiguous neighbours require review.
AUTO_COORDINATE_THRESHOLD_M = 100.0
MIN_NEAREST_GAP_M = 20.0
ADDRESS_THRESHOLD = 0.85
STREET_THRESHOLD = 0.75
FULL_ADDRESS_THRESHOLD = 0.88
# A separate audit policy accepts previously reviewed rows with historical
# high/medium web evidence and a current DC candidate within this radius.
# This is a heuristic, not manual identity verification or a probability.
WEB_EVIDENCE_RADIUS_M = 500.0
WEB_EVIDENCE_LEVELS = frozenset({"high", "medium"})
WEB_EVIDENCE_POLICY = "coordinate_500m_historical_web_rule"
NEW_EXTERNAL_ATTRIBUTE_NAMES = frozenset({
    "plug_types", "connector_types_normalized", "opening_hours", "access_condition",
    "accessibility", "network", "status_counts", "status", "is_operational",
    "operational_status", "usage_cost", "general_comments", "is_free",
    "allows_card_payment", "allows_reservation", "pricing_info", "power_kw_min",
    "power_kw_max", "dc_port_count", "total_port_count", "operator", "power_scope",
})
SOURCE_TEXT_COLUMNS = (
    "Station_name", "Station_address", "Operator", "Charger_Type",
    "Charger_rating", "LGANAME", "PCODE", "Source",
)
SOURCE_NUMERIC_COLUMNS = ("Number_of_plugs", "Latitude", "Longitude")
SOURCE_LABELS = {
    "ocm": "OCM", "osm_fast_dc": "OSM", "chargelarge_fast_dc": "Charge@Large",
}


@dataclass(frozen=True)
class Task3Config:
    input_file: Path = Path(NSW_EV_CHARGING_CLEANED_FILE)
    output_file: Path = Path(NSW_EV_CHARGING_AUG_FILE)
    result_dir: Path = Path(RESULT_DATA_FILE_LOCATION)
    snapshot_dir: Path = ROOT / "data/reference/task3_live_20260924"
    web_review_dir: Path = ROOT / "data/reference/web_review"
    raw_file: Path | None = Path(NSW_EV_CHARGING_SRC_FILE)
    boundary_file: Path = Path(AUS_ASGS_LV4_FILE)
    task2_geocoding_cache: Path | None = ROOT / "data/result_data/task2_nominatim_cache.json"
    accept_historical_web_candidates: bool = True

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


# Student-developed input validation, with AI-assisted reference and review.
def read_task2_output(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Task 2 output file not found: {path}")

    frame = pd.read_csv(
        path,
        dtype={
            "PCODE": "string",
            "PCODE_ORIGINAL": "string",
            "SA4_CODE26": "string",
        },
    )
    required_info = set(SOURCE_TEXT_COLUMNS + SOURCE_NUMERIC_COLUMNS)
    missing_info = required_info - set(frame.columns)
    if missing_info:
        raise ValueError(f"Task 2 output is missing columns: {sorted(missing_info)}")
    if frame.empty:
        raise ValueError("Task 2 output is empty")

    charger_types = (
        frame["Charger_Type"]
        .astype("string")
        .str.strip()
        .str.upper()
    )
    dc = charger_types.eq("DC").fillna(False)
    if not dc.any():
        raise ValueError("Task 2 output contains no DC chargers")

    # Check a numeric copy of the DC coordinates without changing source columns.
    coordinates = frame.loc[dc, ["Latitude", "Longitude"]].apply(
        pd.to_numeric, errors="coerce"
    )
    valid = (
        coordinates.notna().all(axis=1)
        & coordinates["Latitude"].between(-90, 90)
        & coordinates["Longitude"].between(-180, 180)
    ).fillna(False)

    if not valid.all():
        bad_rows = valid.index[~valid].tolist()
        raise ValueError(
            f"Invalid DC coordinates at source row indices: {bad_rows[:5]}"
        )

    return frame


def align_dc_evidence(source: pd.DataFrame, evidence: pd.DataFrame,
                      stage: str) -> pd.DataFrame:
    """Validate a matching/audit file against Task 2, then index by source row.

    Both stage boundaries use the same contract: every DC row exactly once,
    unchanged source identity, and numeric agreement within CSV precision.
    """
    text_columns = SOURCE_TEXT_COLUMNS + (
        ("PCODE_ORIGINAL",) if "PCODE_ORIGINAL" in source else ()
    )
    required = {"source_index", *text_columns, *SOURCE_NUMERIC_COLUMNS}
    missing = required - set(evidence.columns)
    if missing:
        raise ValueError(f"{stage.capitalize()} is missing columns: {sorted(missing)}")
    if not source.index.is_unique:
        raise ValueError("Task 2 source indices must be unique")

    indices = pd.to_numeric(evidence["source_index"], errors="raise")
    if (not np.isfinite(indices).all() or not indices.mod(1).eq(0).all()
            or indices.duplicated().any()):
        raise ValueError(f"{stage.capitalize()} source indices must be unique integers")
    aligned = evidence.set_index(indices.astype(int).rename("source_index"))
    dc = source["Charger_Type"].astype("string").str.strip().str.upper().eq("DC").fillna(False)
    if set(aligned.index) != set(source.index[dc]):
        raise ValueError(f"{stage.capitalize()} must cover current Task 2 DC rows exactly once")

    for column in text_columns:
        current = source.loc[aligned.index, column].astype("string").fillna("").str.strip()
        recorded = aligned[column].astype("string").fillna("").str.strip()
        if not current.equals(recorded):
            raise ValueError(f"Stale {stage} input: {column}")
    for column in SOURCE_NUMERIC_COLUMNS:
        current = pd.to_numeric(source.loc[aligned.index, column], errors="coerce")
        recorded = pd.to_numeric(aligned[column], errors="coerce")
        if not np.isclose(current.to_numpy(dtype=float), recorded.to_numpy(dtype=float),
                          rtol=0, atol=1e-6, equal_nan=True).all():
            raise ValueError(f"Stale {stage} input: {column}")
    return aligned.drop(columns="source_index")


# Student-developed postcode provenance logic, with AI-assisted safeguards.
def matching_input(settings: Task3Config) -> pd.DataFrame:
    frame = read_task2_output(settings.input_file)
    if "PCODE_ORIGINAL" in frame.columns:
        return frame

    raw_path = settings.raw_file
    if raw_path is None:
        return frame

    raw_path = Path(raw_path)
    if not raw_path.is_file():
        return frame

    raw = pd.read_csv(
        raw_path,
        dtype={"PCODE": "string"},
    )
    keys = ["Latitude", "Longitude", "Charger_Type"]
    required = set(keys) | {"PCODE"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Raw TfNSW data is missing columns: {sorted(missing)}")

    # Task 2 preserves source row order. Confirm it before copying raw postcodes.
    if len(frame) != len(raw):
        raise ValueError("Raw TfNSW data and Task 2 output have different row counts")
    if not frame[keys].equals(raw[keys]):
        raise ValueError(
            "Raw TfNSW data and Task 2 output have different coordinates, "
            "charger types, or row order"
        )

    # A shared coordinate/type with conflicting postcodes has no unique postcode.
    postcode_counts = (
        raw.groupby(keys, dropna=False)["PCODE"]
        .transform(lambda values: values.nunique(dropna=False))
    )
    ambiguous = postcode_counts.gt(1)
    frame["PCODE_ORIGINAL"] = raw["PCODE"].mask(ambiguous)
    return frame


def GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df, audit_file=None):
    """Build cleaners for accepted multi-source augmentation fields."""
    from pipeline.data_aug.multisource_augmentation import augmentation_cleaners

    path = Path(audit_file) if audit_file else TASK3_FINAL_AUDIT_FILE
    return augmentation_cleaners(aug_df, path)


# Both public interfaces reserved by the team use the same audited pipeline.
GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE = GET_NSW_EV_COLUMN_AUGMENTATION_CCS
