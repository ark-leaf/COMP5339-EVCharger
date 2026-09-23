"""Map accepted multi-source audit values through the team ColumnCleaners."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from data_utils.column_cleaner import ColumnCleaner, DFDataType
from pipeline.data_aug.ocm_reference import _task3_text

def augmentation_cleaners(aug_df, audit_file: Path) -> list[ColumnCleaner]:
    """Return the existing ColumnCleaner interface backed by the final audit.

    The multi-source matcher writes one row per DC source record.  This adapter
    aligns that audit back to the full cleaned dataframe by ``source_index`` so
    the team's original DataCleaner pipeline can still write one complete
    augmented CSV without replacing the raw TfNSW fields.
    """
    if not audit_file.exists():
        raise FileNotFoundError(
            "The final multi-source audit is missing. Run "
            "task3_final_multisource_audit.py before using the multi-source "
            "augmentation adapter."
        )

    audit = pd.read_csv(audit_file, keep_default_na=False)
    if "source_index" not in audit.columns:
        raise ValueError("The Task 3 audit must contain source_index.")
    if audit["source_index"].duplicated().any():
        raise ValueError("The Task 3 audit contains duplicate source_index values.")
    audit_by_index = {
        int(row["source_index"]): row
        for _, row in audit.iterrows()
    }
    dc_indices = set(aug_df.index[aug_df["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")])
    if set(audit_by_index) != dc_indices:
        raise ValueError("The Task 3 audit does not match the current cleaned DC row indices; rerun matching and audit.")
    for index, row in audit_by_index.items():
        current = aug_df.loc[index]
        for column in ("Station_address", "PCODE", "PCODE_ORIGINAL"):
            if column not in aug_df.columns:
                continue
            if _task3_text(row.get(column)) != _task3_text(current.get(column)):
                raise ValueError(f"Task 3 audit source row {index} has stale {column}; rerun matching and audit.")
        for column in ("Latitude", "Longitude"):
            if abs(float(row[column]) - float(current[column])) > 1e-6:
                raise ValueError(f"Task 3 audit source row {index} has stale {column}; rerun matching and audit.")

    def parse_attributes(value) -> dict:
        try:
            parsed = json.loads(_task3_text(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def values_for(row: dict, attribute: str) -> list:
        attributes = parse_attributes(row.get("augmented_attributes", "{}"))
        values = []
        for key, value in attributes.items():
            if key.rsplit("::", 1)[-1] != attribute:
                continue
            if value not in (None, "", "{}") and value not in values:
                values.append(value)
        return values

    def joined(values: list) -> str:
        flattened = []
        for value in values:
            if isinstance(value, list):
                flattened.extend(value)
            else:
                flattened.append(value)
        labels = []
        for value in flattened:
            label = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, dict)
                else _task3_text(value)
            )
            if label and label not in labels:
                labels.append(label)
        return "; ".join(labels)

    def joined_connectors(values: list) -> str:
        labels = []
        for value in values:
            tokens = value if isinstance(value, list) else str(value).replace("|", ";").split(";")
            for token in tokens:
                token = _task3_text(token)
                if token and token not in labels:
                    labels.append(token)
        return "; ".join(labels)

    def first_number(values: list):
        numbers = set()
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                numbers.add(number)
        if len(numbers) != 1:
            return np.nan
        number = numbers.pop()
        return int(number) if number.is_integer() else number

    def first_coordinate(values: list):
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
        return np.nan

    def make_values(column_name: str) -> pd.Series:
        result = []
        for index in aug_df.index:
            row = audit_by_index.get(int(index), {})
            final_status = _task3_text(row.get("final_audit_status"))
            if column_name == "augmentation_match_status":
                value = (
                    "accepted" if final_status == "accepted_coordinate_supported"
                    else "review" if final_status == "review_candidate"
                    else "unmatched"
                )
            elif column_name == "augmentation_match_confidence":
                value = (
                    1.0 if final_status == "accepted_coordinate_supported"
                    else 0.5 if final_status == "review_candidate"
                    else 0.0
                )
            elif column_name == "augmentation_manual_review":
                value = _task3_text(row.get("identity_review_required", row.get("manual_review_required"))) == "yes"
            elif column_name == "augmentation_quality_review":
                value = _task3_text(row.get("quality_review_required")) == "yes"
            elif column_name == "augmentation_alternative_candidate_warning":
                value = _task3_text(row.get("alternative_candidate_present")) == "yes"
            elif column_name == "augmentation_attribute_review":
                value = _task3_text(row.get("attribute_review_required")) == "yes"
            elif column_name in {
                "augmentation_reference_row", "nearest_distance_m", "nearest_gap_m",
            }:
                source_name = {
                    "augmentation_reference_row": "tfnsw_table_row",
                    "nearest_distance_m": "augmentation_nearest_distance_m",
                    "nearest_gap_m": "augmentation_nearest_gap_m",
                }[column_name]
                raw_value = row.get(source_name, "")
                value = raw_value if _task3_text(raw_value) else np.nan
            elif column_name == "external_number_of_plugs":
                value = first_number(values_for(row, "number_of_plugs"))
            elif column_name == "external_numeric_conflict_flags":
                value = _task3_text(row.get("augmentation_conflict_flags"))
            elif column_name == "external_data_provider":
                value = joined(values_for(row, "data_provider"))
            elif column_name == "external_station_name":
                value = joined(values_for(row, "station_name"))
            elif column_name == "external_operator":
                value = joined(values_for(row, "operator"))
            elif column_name == "external_charger_capacity":
                value = joined(values_for(row, "charger_capacities"))
            elif column_name == "external_plug_types":
                value = joined(values_for(row, "plug_types"))
            elif column_name == "external_connector_types_normalized":
                value = joined_connectors(values_for(row, "connector_types_normalized"))
            elif column_name == "external_status":
                value = joined(values_for(row, "status"))
            elif column_name == "external_operational_status":
                value = joined(values_for(row, "operational_status")) or (
                    "unknown" if _task3_text(row.get("matched_source")) else ""
                )
            elif column_name == "external_usage_cost":
                value = joined(values_for(row, "usage_cost"))
            elif column_name == "external_network":
                value = joined(values_for(row, "network"))
            elif column_name == "external_access_condition":
                value = joined(values_for(row, "access_condition"))
            elif column_name == "external_accessibility":
                value = joined(values_for(row, "accessibility"))
            elif column_name == "external_is_free":
                value = joined(values_for(row, "is_free"))
            elif column_name == "external_allows_card_payment":
                value = joined(values_for(row, "allows_card_payment"))
            elif column_name == "external_allows_reservation":
                value = joined(values_for(row, "allows_reservation"))
            elif column_name == "external_pricing_info":
                value = joined(values_for(row, "pricing_info"))
            elif column_name == "external_status_counts":
                value = joined(values_for(row, "status_counts"))
            elif column_name == "external_dc_port_count":
                value = first_number(values_for(row, "dc_port_count"))
            elif column_name == "external_total_port_count":
                value = first_number(values_for(row, "total_port_count"))
            elif column_name == "external_osm_last_updated":
                value = joined(values_for(row, "osm_last_updated"))
            elif column_name == "external_last_verified":
                value = joined(values_for(row, "last_verified"))
            elif column_name == "external_comments":
                value = joined(values_for(row, "general_comments"))
            elif column_name == "external_number_of_plugs_quality":
                value = joined(values_for(row, "number_of_plugs_quality"))
            elif column_name == "external_number_of_plugs_semantics":
                value = joined(values_for(row, "number_of_plugs_semantics"))
            elif column_name == "external_power_kw_values":
                value = joined(values_for(row, "power_kw_values"))
            elif column_name == "external_power_kw_min":
                value = first_number(values_for(row, "power_kw_min"))
            elif column_name == "external_power_kw_max":
                value = first_number(values_for(row, "power_kw_max"))
            elif column_name == "external_opening_hours":
                value = joined(values_for(row, "opening_hours"))
            elif column_name == "external_latitude":
                value = first_coordinate(values_for(row, "latitude"))
            elif column_name == "external_longitude":
                value = first_coordinate(values_for(row, "longitude"))
            elif column_name == "external_attributes_json":
                raw_attributes = _task3_text(row.get("augmented_attributes"))
                # Keep the final augmented table semantically clean: an empty
                # JSON object from an unmatched/review-only row is not an
                # external attribute and should remain blank.  Candidate
                # details are still available in the audit diagnostics.
                value = (
                    raw_attributes
                    if final_status == "accepted_coordinate_supported"
                    and raw_attributes not in {"", "{}"}
                    else ""
                )
            elif column_name in {"match_distance_m", "address_score"}:
                raw_value = row.get(column_name, "")
                value = raw_value if _task3_text(raw_value) else np.nan
            else:
                value = row.get(column_name, "")
            result.append(value)
        return pd.Series(result, index=aug_df.index)

    def create_column(column_name):
        return lambda current_df: make_values(column_name).reindex(current_df.index)

    return [
        ColumnCleaner(
            "augmentation_match_status", DFDataType.STR,
            default_value="unmatched",
            column_create_function=create_column("augmentation_match_status"),
        ),
        ColumnCleaner(
            "augmentation_match_method", DFDataType.STR,
            default_value="none",
            column_create_function=create_column("match_method"),
        ),
        ColumnCleaner(
            "augmentation_match_confidence", DFDataType.FLOAT,
            default_value=0.0,
            column_create_function=create_column("augmentation_match_confidence"),
        ),
        ColumnCleaner(
            "augmentation_manual_review", DFDataType.BOOL,
            default_value=False,
            column_create_function=create_column("augmentation_manual_review"),
        ),
        ColumnCleaner(
            "augmentation_quality_review", DFDataType.BOOL,
            default_value=False,
            column_create_function=create_column("augmentation_quality_review"),
        ),
        ColumnCleaner(
            "augmentation_alternative_candidate_warning", DFDataType.BOOL,
            default_value=False,
            column_create_function=create_column("augmentation_alternative_candidate_warning"),
        ),
        ColumnCleaner(
            "augmentation_attribute_review", DFDataType.BOOL,
            default_value=False,
            column_create_function=create_column("augmentation_attribute_review"),
        ),
        ColumnCleaner(
            "augmentation_reference_row", DFDataType.FLOAT,
            column_create_function=create_column("augmentation_reference_row"),
        ),
        ColumnCleaner(
            "augmentation_match_distance_m", DFDataType.FLOAT,
            column_create_function=create_column("match_distance_m"),
        ),
        ColumnCleaner(
            "augmentation_nearest_distance_m", DFDataType.FLOAT,
            column_create_function=create_column("nearest_distance_m"),
        ),
        ColumnCleaner(
            "augmentation_nearest_gap_m", DFDataType.FLOAT,
            column_create_function=create_column("nearest_gap_m"),
        ),
        ColumnCleaner(
            "external_source", DFDataType.STR,
            default_value="",
            column_create_function=create_column("match_source"),
        ),
        ColumnCleaner(
            "external_data_provider", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_data_provider"),
        ),
        ColumnCleaner(
            "external_station_id", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_id"),
        ),
        ColumnCleaner(
            "external_station_name", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_station_name"),
        ),
        ColumnCleaner(
            "external_station_address", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_address"),
        ),
        ColumnCleaner(
            "external_operator", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_operator"),
        ),
        ColumnCleaner(
            "external_plug_types", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_plug_types"),
        ),
        ColumnCleaner(
            "external_connector_types_normalized", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_connector_types_normalized"),
        ),
        ColumnCleaner(
            "external_number_of_plugs", DFDataType.FLOAT,
            column_create_function=create_column("external_number_of_plugs"),
        ),
        ColumnCleaner(
            "external_numeric_conflict_flags", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_numeric_conflict_flags"),
        ),
        ColumnCleaner(
            "external_number_of_plugs_quality", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_number_of_plugs_quality"),
        ),
        ColumnCleaner(
            "external_number_of_plugs_semantics", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_number_of_plugs_semantics"),
        ),
        ColumnCleaner(
            "external_charger_capacity", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_charger_capacity"),
        ),
        ColumnCleaner(
            "external_power_kw_values", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_power_kw_values"),
        ),
        ColumnCleaner(
            "external_power_kw_min", DFDataType.FLOAT,
            column_create_function=create_column("external_power_kw_min"),
        ),
        ColumnCleaner(
            "external_power_kw_max", DFDataType.FLOAT,
            column_create_function=create_column("external_power_kw_max"),
        ),
        ColumnCleaner(
            "external_status", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_status"),
        ),
        ColumnCleaner(
            "external_operational_status", DFDataType.STR,
            default_value="unknown",
            column_create_function=create_column("external_operational_status"),
        ),
        ColumnCleaner(
            "external_usage_cost", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_usage_cost"),
        ),
        ColumnCleaner(
            "external_network", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_network"),
        ),
        ColumnCleaner(
            "external_access_condition", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_access_condition"),
        ),
        ColumnCleaner(
            "external_accessibility", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_accessibility"),
        ),
        ColumnCleaner(
            "external_is_free", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_is_free"),
        ),
        ColumnCleaner(
            "external_allows_card_payment", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_allows_card_payment"),
        ),
        ColumnCleaner(
            "external_allows_reservation", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_allows_reservation"),
        ),
        ColumnCleaner(
            "external_pricing_info", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_pricing_info"),
        ),
        ColumnCleaner(
            "external_status_counts", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_status_counts"),
        ),
        ColumnCleaner(
            "external_dc_port_count", DFDataType.FLOAT,
            column_create_function=create_column("external_dc_port_count"),
        ),
        ColumnCleaner(
            "external_total_port_count", DFDataType.FLOAT,
            column_create_function=create_column("external_total_port_count"),
        ),
        ColumnCleaner(
            "external_osm_last_updated", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_osm_last_updated"),
        ),
        ColumnCleaner(
            "external_last_verified", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_last_verified"),
        ),
        ColumnCleaner(
            "external_comments", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_comments"),
        ),
        ColumnCleaner(
            "external_opening_hours", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_opening_hours"),
        ),
        ColumnCleaner(
            "external_latitude", DFDataType.FLOAT,
            column_create_function=create_column("external_latitude"),
        ),
        ColumnCleaner(
            "external_longitude", DFDataType.FLOAT,
            column_create_function=create_column("external_longitude"),
        ),
        ColumnCleaner(
            "external_attributes_json", DFDataType.STR,
            default_value="{}",
            column_create_function=create_column("external_attributes_json"),
        ),
        ColumnCleaner(
            "augmentation_review_reason", DFDataType.STR,
            default_value="",
            column_create_function=create_column("identity_review_reason"),
        ),
        ColumnCleaner(
            "augmentation_quality_review_reason", DFDataType.STR,
            default_value="",
            column_create_function=create_column("quality_review_reason"),
        ),
    ]
