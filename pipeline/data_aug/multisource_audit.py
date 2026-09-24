"""Audit Task 3 matches and export traceable external attributes.

Core flow adapted from an AI reference by the student; helpers, integration
checks and tests were completed with AI assistance.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd


from pipeline.data_aug.nsw_evc_aug_config import (
    Task3Config, display_path, matching_input, NEW_EXTERNAL_ATTRIBUTE_NAMES,
)
from pipeline.data_aug.provenance import snapshot_metadata
from pipeline.data_aug.charging_match_rules import address_parts


SOURCE_CONFIG = {
    "ocm": {"label": "OCM", "id": "ocm_id", "status": "ocm_status", "method": "ocm_method", "distance": "ocm_distance_m", "address": "ocm_address", "address_score": "ocm_address_score", "gap": "ocm_nearest_coordinate_gap_m"},
    "osm_fast_dc": {"label": "OSM", "id": "osm_fast_dc_id", "status": "osm_fast_dc_status", "method": "osm_fast_dc_method", "distance": "osm_fast_dc_distance_m", "address": "osm_fast_dc_address", "address_score": "osm_fast_dc_address_score", "gap": "osm_fast_dc_nearest_coordinate_gap_m"},
    "chargelarge_fast_dc": {"label": "Charge@Large", "id": "chargelarge_fast_dc_id", "status": "chargelarge_fast_dc_status", "method": "chargelarge_fast_dc_method", "distance": "chargelarge_fast_dc_distance_m", "address": "chargelarge_fast_dc_address", "address_score": "chargelarge_fast_dc_address_score", "gap": "chargelarge_fast_dc_nearest_coordinate_gap_m"},
}


def text(value: Any) -> str:
    """Convert a missing scalar to empty text without changing identifiers."""
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def numeric(value: Any) -> float | None:
    """Return only a finite numeric value; booleans are not measurements."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def identifier(value: Any) -> str:
    """Preserve source IDs as strings, including leading zeroes."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return text(value)


def parse_attributes(value: Any) -> dict[str, Any]:
    """Parse an accepted source's JSON object or reject malformed evidence."""
    if isinstance(value, dict):
        return value
    raw = text(value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed matched attributes JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Matched attributes must be a JSON object")
    return parsed


def actual_value(value: Any) -> bool:
    """Distinguish missing data from explicit false and zero values."""
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, str):
        return value.strip().lower() not in {"", "unknown", "n/a", "null", "none"}
    if isinstance(value, (list, dict)):
        return bool(value)
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return True


def new_attribute_count(attributes: dict) -> int:
    """Count distinct, meaningful external business attributes."""
    names = set()

    # TfNSW already has plug count and charger rating. Keep external
    # power/count details in the audit, but do not use them alone to
    # satisfy the "new attribute" coverage requirement.
    existing_information = {
        "power_kw_min", "power_kw_max",
        "dc_port_count", "total_port_count",
        "operator", "power_scope",
    }

    for full_name, value in attributes.items():
        name = str(full_name).rsplit("::", 1)[-1]

        if name not in NEW_EXTERNAL_ATTRIBUTE_NAMES:
            continue
        if name in existing_information:
            continue
        if not actual_value(value):
            continue

        # False is useful information when the provider explicitly
        # reported it, e.g. is_free=False.
        names.add(name)

    return len(names)


def duplicate_external_id_rows(output: pd.DataFrame) -> pd.DataFrame:
    """Find external records assigned to multiple TfNSW DC rows."""
    found = []

    for prefix, config in SOURCE_CONFIG.items():
        accepted = output.loc[
            output[config["status"]].map(text).eq("accepted")
        ].copy()

        if accepted.empty:
            continue

        accepted["_external_id"] = accepted[config["id"]].map(identifier)
        accepted = accepted.loc[accepted["_external_id"].ne("")]

        for external_id, group in accepted.groupby("_external_id"):
            source_indices = group["source_index"].astype(int).tolist()

            if len(set(source_indices)) < 2:
                continue

            found.append({
                "source": config["label"],
                "external_id": external_id,
                "tfnsw_row_count": len(source_indices),
                "source_indices": ";".join(map(str, source_indices)),
                "tfnsw_addresses": " || ".join(
                    group["Station_address"].map(text)
                ),
                "match_distances_m": ";".join(
                    group[config["distance"]].map(text)
                ),
            })

    columns = [
        "source", "external_id", "tfnsw_row_count",
        "source_indices", "tfnsw_addresses", "match_distances_m",
    ]
    return pd.DataFrame(found, columns=columns)


def attach_web_context(audit: pd.DataFrame, settings: Task3Config) -> None:
    """Keep historical searches as context, never as automatic identity proof."""
    notes = {int(index): [] for index in audit["source_index"]}
    current = audit.set_index("source_index")
    for filename in ("task3_ocm_125_web_confidence.csv", "task3_104_non_ocm_web_verified.csv"):
        path = settings.web_review_dir / filename
        if not path.is_file():
            continue
        for _, old in pd.read_csv(path, keep_default_na=False).iterrows():
            source_index = int(old["source_index"])
            if source_index not in current.index:
                continue
            row = current.loc[source_index]
            old_address = address_parts(old.get("Station_address"))["normalised"]
            address = address_parts(row["Station_address"])["normalised"]
            if not old_address or old_address != address:
                continue
            binding = "source_address_only; external identity not verified"
            if "ocm_id" in old:
                if identifier(old["ocm_id"]) != identifier(row["ocm_id"]):
                    continue
                binding = "same source address and OCM ID; search evidence only"
            notes[source_index].append({
                "file": display_path(path),
                "url": text(old.get("web_evidence_url")),
                "reported_confidence": text(old.get("web_evidence_confidence")),
                "page_opened": text(old.get("web_page_opened")).lower() == "true",
                "conclusion": text(old.get("web_review_conclusion")),
                "binding": binding,
            })
    audit["historical_web_evidence"] = [
        json.dumps(notes[int(index)], ensure_ascii=False, sort_keys=True)
        for index in audit["source_index"]
    ]


def run_audit(settings: Task3Config = Task3Config()) -> dict:
    """Audit current DC matches and write traceable augmentation evidence."""
    clean = matching_input(settings)
    dc_mask = (
        clean["Charger_Type"]
        .astype("string")
        .str.strip()
        .str.upper()
        .eq("DC")
        .fillna(False)
    )
    dc_rows = clean.loc[dc_mask]
    expected_indices = set(dc_rows.index)

    id_types = {"PCODE": "string", "PCODE_ORIGINAL": "string"}
    for config in SOURCE_CONFIG.values():
        id_types[config["id"]] = "string"

    matches = pd.read_csv(
        settings.matches_file,
        dtype=id_types,
        keep_default_na=False,
    )

    indices = pd.to_numeric(matches["source_index"], errors="raise")
    if (
        indices.isna().any()
        or not indices.eq(indices.astype(int)).all()
        or indices.duplicated().any()
        or len(matches) != len(dc_rows)
        or set(indices.astype(int)) != expected_indices
    ):
        raise ValueError("Matches do not cover current Task 2 DC rows exactly once")
    matches["source_index"] = indices.astype(int)

    # Reject a stale matching file instead of attaching old evidence
    # to newly cleaned or reordered Task 2 records.
    for _, row in matches.iterrows():
        current = dc_rows.loc[int(row["source_index"])]

        for column in (
            "Station_name", "Station_address", "Operator", "Charger_Type",
            "Charger_rating", "LGANAME", "PCODE", "Source", "PCODE_ORIGINAL",
        ):
            if column in matches and text(row[column]) != text(current[column]):
                raise ValueError(f"Stale matching input: {column}")

        for column in ("Number_of_plugs", "Latitude", "Longitude"):
            matched_value = numeric(row[column])
            current_value = numeric(current[column])
            if (matched_value is None) != (current_value is None):
                raise ValueError(f"Stale matching input: {column}")
            if (matched_value is not None and
                    abs(matched_value - current_value) > 1e-6):
                raise ValueError(f"Stale matching input: {column}")

    audit_rows = []
    numeric_fields = {
        "power_kw_min", "power_kw_max",
        "dc_port_count", "total_port_count",
    }

    for _, row in matches.iterrows():
        accepted_sources = []
        review_sources = []
        external_ids = []
        quality_reasons = []
        review_reasons = []
        observed_attributes = {}
        export_attributes = {}
        numeric_values = {name: set() for name in numeric_fields}

        for prefix, config in SOURCE_CONFIG.items():
            status = text(row[config["status"]])
            label = config["label"]

            if status == "accepted":
                accepted_sources.append(label)

                external_id = identifier(row[config["id"]])
                if external_id:
                    external_ids.append(f"{label}:{external_id}")

                warning = text(row.get(f"{prefix}_quality_flags"))
                if warning:
                    quality_reasons.append(f"{label}: {warning}")

                attributes = parse_attributes(
                    row.get(f"{prefix}_attributes", "{}")
                )

                for name, value in attributes.items():
                    if not actual_value(value):
                        continue

                    full_name = f"{label}::{name}"
                    observed_attributes[full_name] = value

                    number = numeric(value) if name in numeric_fields else None
                    valid_quantity = name not in numeric_fields or (
                        number is not None and number > 0
                    )
                    if name in NEW_EXTERNAL_ATTRIBUTE_NAMES and valid_quantity:
                        export_attributes[full_name] = value

                    if number is not None and number > 0:
                        numeric_values[name].add(round(number, 6))

            elif status == "review":
                review_sources.append(label)
                reason = text(row.get(f"{prefix}_review_reason"))
                review_reasons.append(
                    f"{label}: {reason or 'candidate needs review'}"
                )

        # Do not turn conflicting source values into one certain scalar.
        conflicts = [
            name for name, values in numeric_values.items()
            if len(values) > 1
        ]
        if conflicts:
            quality_reasons.append(
                "External numeric values disagree: " + ", ".join(conflicts)
            )
            export_attributes = {
                name: value
                for name, value in export_attributes.items()
                if name.rsplit("::", 1)[-1] not in conflicts
            }

        if accepted_sources:
            final_status = "accepted"
        elif review_sources:
            final_status = "review"
        else:
            final_status = "unmatched"

        # Review-only candidates never contribute confirmed attributes.
        if final_status != "accepted":
            export_attributes = {}
        elif new_attribute_count(export_attributes) == 0:
            final_status = "review"
            review_reasons.append("Matched source supplies no genuinely new attribute")
            export_attributes = {}

        audit_rows.append({
            "final_audit_status": final_status,
            "matched_source": ";".join(accepted_sources),
            "matched_external_ids": ";".join(external_ids),
            "review_candidate_source": ";".join(review_sources),
            "manual_review_reason": "; ".join(review_reasons),
            "quality_review_reason": "; ".join(quality_reasons),
            "quality_review_required": "yes" if quality_reasons else "no",
            "augmentation_conflict_flags": ";".join(conflicts),
            "accepted_source_attributes": json.dumps(
                observed_attributes, ensure_ascii=False, sort_keys=True
            ),
            "augmented_attributes": json.dumps(
                export_attributes, ensure_ascii=False, sort_keys=True
            ),
            "new_attribute_count": new_attribute_count(export_attributes),
        })

    audit = matches.copy()
    details = pd.DataFrame(audit_rows, index=audit.index)
    for column in details.columns:
        audit[column] = details[column]

    attach_web_context(audit, settings)

    duplicates = duplicate_external_id_rows(audit)
    for _, duplicate in duplicates.iterrows():
        # One external object can legitimately describe multiple chargers at
        # a site, but it must never become an unflagged identity assertion.
        warning = (
            f"{duplicate['source']}:{duplicate['external_id']} is linked "
            "to multiple TfNSW rows"
        )
        for source_index in duplicate["source_indices"].split(";"):
            mask = audit["source_index"].eq(int(source_index))
            for row_index in audit.index[mask]:
                current = audit.at[row_index, "quality_review_reason"]
                audit.at[row_index, "quality_review_reason"] = (
                    f"{current}; {warning}" if current else warning
                )
                audit.at[row_index, "quality_review_required"] = "yes"

    accepted = audit["final_audit_status"].eq("accepted")
    review_only = audit["final_audit_status"].eq("review")
    quality_flagged = (
        accepted & audit["quality_review_required"].eq("yes")
    )
    enriched = accepted & audit["new_attribute_count"].gt(0)

    required_rows = math.ceil(len(dc_rows) * 0.5)
    assignment_check = {
        "required_share": 0.5,
        "required_rows": required_rows,
        "accepted_rows_with_new_attributes": int(enriched.sum()),
        "accepted_row_coverage": (
            float(enriched.sum() / len(dc_rows)) if len(dc_rows) else 0.0
        ),
        "target_met": bool(enriched.sum() >= required_rows),
    }

    settings.audit_dir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(settings.audit_file, index=False)
    audit.loc[review_only].to_csv(
        settings.audit_dir / "task3_multisource_manual_review_queue.csv",
        index=False,
    )
    audit.loc[quality_flagged].to_csv(
        settings.audit_dir / "task3_multisource_accepted_quality_flags.csv",
        index=False,
    )
    duplicates.to_csv(
        settings.audit_dir / "task3_duplicate_external_id_report.csv",
        index=False,
    )

    # Record the files actually used. A missing retrieval timestamp
    # stays unknown; the file modification time is not API evidence.
    sources = []
    for label, filename, metadata_name in (
        ("OCM", "task3_ocm_tiled_snapshot.json",
         "task3_ocm_tiled_snapshot_metadata.json"),
        ("OSM-derived", "task3_osm_nsw_snapshot_for_multisource.json",
         "task3_osm_snapshot_metadata.json"),
        ("Charge@Large", "task3_chargelarge_raw.json",
         "task3_chargelarge_metadata.json"),
    ):
        path = settings.snapshot_dir / filename
        metadata_path = (
            settings.snapshot_dir / metadata_name
            if metadata_name else None
        )
        if label == "Charge@Large" and not metadata_path.is_file():
            metadata_path = settings.snapshot_dir / "task3_chargelarge_summary.json"
        sources.append({
            "source": label,
            "local_snapshot": display_path(path),
            **snapshot_metadata(path, metadata_path),
        })

    (settings.audit_dir / "task3_source_manifest.json").write_text(
        json.dumps({"sources": sources}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        "tfnsw_dc_rows": len(dc_rows),
        "accepted_rows": int(accepted.sum()),
        "accepted_with_new_attributes_rows": int(enriched.sum()),
        "manual_review_only_rows": int(review_only.sum()),
        "accepted_quality_flag_rows": int(quality_flagged.sum()),
        "ocm_osm_only_union_rows": int((
            audit["ocm_status"].eq("accepted")
            | audit["osm_fast_dc_status"].eq("accepted")
        ).sum()),
        "duplicate_external_id_groups": len(duplicates),
        "historical_web_context_rows": int(audit["historical_web_evidence"].ne("[]").sum()),
        "unique_dc_coordinate_locations": len(dc_rows[["Latitude", "Longitude"]].drop_duplicates()),
        "accepted_unique_coordinate_locations": len(audit.loc[enriched, ["Latitude", "Longitude"]].drop_duplicates()),
        "accepted_attribute_nonempty_counts": {
            name: int(sum(any(key.rsplit("::", 1)[-1] == name and actual_value(value)
                             for key, value in json.loads(raw).items())
                         for raw in audit.loc[enriched, "augmented_attributes"]))
            for name in sorted(NEW_EXTERNAL_ATTRIBUTE_NAMES)
        },
        "assignment_check": assignment_check,
    }
    (settings.audit_dir / "task3_multisource_final_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary
