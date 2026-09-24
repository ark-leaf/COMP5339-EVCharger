"""Write audited Task 3 attributes through the team's ColumnCleaner interface.

Source-index alignment was student-designed; checks and field extraction were
completed with AI assistance. Matching decisions remain in the audit stage.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from data_utils.column_cleaner import ColumnCleaner, DFDataType

TEXT_FIELDS = {
    "external_connector_types_normalized": "connector_types_normalized",
    "external_opening_hours": "opening_hours",
    "external_network": "network",
    "external_access_condition": "access_condition",
    "external_operator": "operator",
    "external_usage_cost": "usage_cost",
}
NUMBER_FIELDS = {
    "external_power_kw_max": "power_kw_max",
    "external_power_kw_min": "power_kw_min",
    "external_dc_port_count": "dc_port_count",
    # Task 4's legacy column name; this counts explicit DC ports only, never bays.
    "external_number_of_plugs": "dc_port_count",
}


def _business_value(attributes: dict, field: str, conflicts: set[str]):
    """Expose a scalar only when accepted sources agree on its value."""
    if field in conflicts:
        return None
    values = []
    for key, value in attributes.items():
        if not key.endswith(f"::{field}"):
            continue
        if field in {"power_kw_max", "power_kw_min", "dc_port_count"}:
            if isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(number) and number > 0:
                values.append(number)
        elif field == "is_free":
            if isinstance(value, bool):
                values.append("true" if value else "false")
        elif isinstance(value, str) and value.strip().lower() not in {
            "", "unknown", "n/a", "null", "none",
        }:
            values.append(value.strip())
    if field == "connector_types_normalized":
        return ";".join(sorted({part for value in values for part in value.split(";") if part})) or None
    return values[0] if values and len(set(values)) == 1 else None


def _cleaner(name, values, data_type, default):
    """Create a team ColumnCleaner aligned by the current frame's index."""
    def create(df):
        if not df.index.is_unique:
            raise ValueError("Task 2 source indices must be unique")
        return values.reindex(df.index).fillna(default)
    return ColumnCleaner(
        name, data_type, default_value=default, column_create_function=create,
    )


def augmentation_cleaners(aug_df: pd.DataFrame, audit_file: Path) -> list[ColumnCleaner]:
    """Align P5 audit rows to Task 2 and export accepted attributes only."""
    if not aug_df.index.is_unique or "Charger_Type" not in aug_df:
        raise ValueError("Task 2 input needs unique indices and Charger_Type")

    audit = pd.read_csv(
        audit_file, keep_default_na=False,
        dtype={"PCODE": "string", "PCODE_ORIGINAL": "string"},
    )
    source_text = (
        "Station_name", "Station_address", "Operator", "Charger_Type",
        "Charger_rating", "LGANAME", "PCODE", "Source",
    )
    source_numeric = ("Number_of_plugs", "Latitude", "Longitude")
    required = {
        "source_index", "final_audit_status", "augmented_attributes",
        "quality_review_required", "augmentation_conflict_flags",
        "matched_source", "matched_external_ids",
        *source_text, *source_numeric,
    }
    missing = required - set(audit.columns)
    if missing:
        raise ValueError(f"Audit is missing columns: {sorted(missing)}")

    indices = pd.to_numeric(audit["source_index"], errors="raise")
    if indices.isna().any() or not indices.eq(indices.astype(int)).all():
        raise ValueError("Audit source_index must contain integers")
    audit["source_index"] = indices.astype(int)
    audit = audit.set_index("source_index")
    if not audit.index.is_unique:
        raise ValueError("Audit source indices must be unique")

    dc = (
        aug_df["Charger_Type"].astype("string").str.strip()
        .str.upper().eq("DC").fillna(False)
    )
    if set(audit.index) != set(aug_df.index[dc]):
        raise ValueError("Audit must cover current Task 2 DC rows exactly once")

    # P5 copied source fields; reject an audit from another Task 2 run.
    identity_text = source_text + (("PCODE_ORIGINAL",) if "PCODE_ORIGINAL" in aug_df else ())
    for column in identity_text:
        if column not in aug_df or column not in audit:
            raise ValueError(f"Cannot check audit source column: {column}")
        current = aug_df.loc[audit.index, column].astype("string").fillna("").str.strip()
        recorded = audit[column].astype("string").fillna("").str.strip()
        if not current.equals(recorded):
            raise ValueError(f"Stale audit input: {column}")
    for column in source_numeric:
        current = pd.to_numeric(aug_df.loc[audit.index, column], errors="coerce")
        recorded = pd.to_numeric(audit[column], errors="coerce")
        if not np.isclose(
            current.to_numpy(dtype=float), recorded.to_numpy(dtype=float),
            rtol=0, atol=1e-6, equal_nan=True,
        ).all():
            raise ValueError(f"Stale audit input: {column}")

    status = audit["final_audit_status"]
    if not status.isin({"accepted", "review", "unmatched"}).all():
        raise ValueError("Audit has an unknown final_audit_status")
    if not audit["quality_review_required"].isin({"yes", "no"}).all():
        raise ValueError("Audit has an unknown quality_review_required value")

    fields = {
        "augmentation_match_status": status,
        "external_attributes_json": pd.Series("", index=audit.index, dtype=object),
        "augmentation_quality_review": audit["quality_review_required"].where(
            status.eq("accepted"), ""
        ),
        "external_source": audit["matched_source"].where(status.eq("accepted"), ""),
        "external_station_id": audit["matched_external_ids"].where(status.eq("accepted"), ""),
        "external_is_free": pd.Series("", index=audit.index, dtype=object),
        "augmentation_match_method": pd.Series("", index=audit.index, dtype=object),
        # No calibrated probability is available; preserve Task 4's nullable contract.
        "augmentation_match_confidence": pd.Series(np.nan, index=audit.index, dtype=float),
        "augmentation_quality_review_reason": audit.get(
            "quality_review_reason", pd.Series("", index=audit.index)
        ).where(status.eq("accepted"), ""),
    }
    for name in TEXT_FIELDS:
        fields[name] = pd.Series("", index=audit.index, dtype=object)
    for name in NUMBER_FIELDS:
        fields[name] = pd.Series(np.nan, index=audit.index, dtype=float)

    for source_index, row in audit.loc[status.eq("accepted")].iterrows():
        fields["augmentation_match_method"].at[source_index] = ";".join(
            f"{prefix}:{row.get(prefix + '_method', '')}"
            for prefix in ("ocm", "osm_fast_dc", "chargelarge_fast_dc")
            if row.get(prefix + "_status") == "accepted"
        )
        try:
            attributes = json.loads(row["augmented_attributes"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Malformed augmented_attributes at {source_index}") from exc
        if not isinstance(attributes, dict):
            raise ValueError(f"augmented_attributes must be an object at {source_index}")
        if attributes:
            fields["external_attributes_json"].at[source_index] = json.dumps(
                attributes, ensure_ascii=False, sort_keys=True,
            )
        conflicts = set(str(row["augmentation_conflict_flags"]).split(";"))
        for name, field in {**TEXT_FIELDS, **NUMBER_FIELDS}.items():
            value = _business_value(attributes, field, conflicts)
            if value is not None:
                fields[name].at[source_index] = value
        value = _business_value(attributes, "is_free", conflicts)
        if value is not None:
            fields["external_is_free"].at[source_index] = value

    defaults = {name: np.nan for name in NUMBER_FIELDS}
    defaults["augmentation_match_confidence"] = np.nan
    defaults["augmentation_match_status"] = "not_applicable"
    return [
        _cleaner(
            name, values,
            DFDataType.FLOAT if name in NUMBER_FIELDS or name == "augmentation_match_confidence" else DFDataType.STR,
            defaults.get(name, ""),
        )
        for name, values in fields.items()
    ]
