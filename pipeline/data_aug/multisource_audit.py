# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that I wrote/adapted the initial audit flow using OpenAI Codex
# references. Codex also implemented the historical-web-evidence acceptance
# rule, revised conflict handling, and assisted with corrections and tests.

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
    WEB_EVIDENCE_RADIUS_M, WEB_EVIDENCE_LEVELS, WEB_EVIDENCE_POLICY,
    align_dc_evidence, SOURCE_LABELS,
)
from pipeline.data_aug.provenance import SNAPSHOT_FILES, snapshot_metadata
from pipeline.data_aug.charging_match_rules import address_parts, text, as_float


SOURCE_CONFIG = {
    prefix: {
        "label": label,
        **{field: f"{prefix}_{suffix}" for field, suffix in (
            ("id", "id"), ("status", "status"), ("method", "method"),
            ("distance", "distance_m"), ("address", "address"),
            ("address_score", "address_score"), ("gap", "nearest_coordinate_gap_m"),
        )},
    }
    for prefix, label in SOURCE_LABELS.items()
}


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
    """Bind historical evidence to current rows without claiming identity proof."""
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
                "identity_decision": text(old.get("match_identity_decision")),
                "binding": binding,
            })
    audit["historical_web_evidence"] = [
        json.dumps(notes[int(index)], ensure_ascii=False, sort_keys=True)
        for index in audit["source_index"]
    ]


def apply_web_evidence_policy(matches: pd.DataFrame, enabled: bool = True) -> None:
    """Apply the requested row-level evidence policy after strict matching.

    Only rows without a strict accepted source are eligible. A bound high or
    medium web note supports the source row, not necessarily the selected
    external ID. Select one nearest DC candidate within 500 m, retaining all
    strict conflict warnings. Counts are calculated, never targeted or fixed.
    """
    for prefix in SOURCE_CONFIG:
        matches[f"{prefix}_strict_status"] = matches[f"{prefix}_status"]
        matches[f"{prefix}_strict_method"] = matches[f"{prefix}_method"]
    matches["strict_combined_dc_status"] = matches["combined_dc_indicated_status"]
    matches["acceptance_basis"] = matches["combined_dc_indicated_status"].map(
        {"accepted": "strict_match", "review": "", "unmatched": ""}
    ).fillna("")
    matches["web_rule_selected_source"] = ""
    if not enabled:
        return

    for index, row in matches.iterrows():
        if row["combined_dc_indicated_status"] != "review":
            continue
        notes = json.loads(row["historical_web_evidence"])
        supporting = [note for note in notes
                      if note.get("reported_confidence") in WEB_EVIDENCE_LEVELS
                      and text(note.get("url"))
                      and note.get("conclusion") != "likely_different_station"
                      and "negative" not in text(note.get("identity_decision")).lower()]
        if not supporting:
            continue

        candidates = []
        for order, (prefix, config) in enumerate(SOURCE_CONFIG.items()):
            distance = as_float(row[config["distance"]])
            if (row[config["status"]] != "review"
                    or distance is None or not 0 <= distance <= WEB_EVIDENCE_RADIUS_M
                    or not identifier(row[config["id"]])
                    or text(row.get(f"{prefix}_fast_dc_indicator")).lower() != "true"):
                continue
            attributes = parse_attributes(row.get(f"{prefix}_attributes"))
            if (attributes.get("is_operational") is False
                    or new_attribute_count(attributes) == 0):
                continue
            # Source order OCM, OSM, Charge@Large is the deterministic tie-break.
            candidates.append((distance, order, prefix))
        if not candidates:
            continue

        _, _, prefix = min(candidates)
        warning = (
            "Accepted by 500 m and historical high/medium web-evidence policy; "
            "not independently identity-verified; strict rejection retained"
        )
        reasons = [text(row.get(f"{prefix}_quality_flags")),
                   text(row.get(f"{prefix}_review_reason")), warning]
        matches.at[index, f"{prefix}_status"] = "accepted"
        matches.at[index, f"{prefix}_method"] = WEB_EVIDENCE_POLICY
        matches.at[index, f"{prefix}_quality_flags"] = "; ".join(r for r in reasons if r)
        matches.at[index, "combined_dc_indicated_status"] = "accepted"
        matches.at[index, "acceptance_basis"] = WEB_EVIDENCE_POLICY
        matches.at[index, "web_rule_selected_source"] = prefix


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

    id_types = {"PCODE": "string", "PCODE_ORIGINAL": "string"}
    for config in SOURCE_CONFIG.values():
        id_types[config["id"]] = "string"

    matches = pd.read_csv(
        settings.matches_file,
        dtype=id_types,
        keep_default_na=False,
    )

    matches = align_dc_evidence(clean, matches, "matching").reset_index()

    attach_web_context(matches, settings)
    apply_web_evidence_policy(matches, settings.accept_historical_web_candidates)
    audit_rows = []
    # Stable order keeps conflict warnings and CSV hashes identical across runs.
    numeric_fields = ("dc_port_count", "power_kw_max", "power_kw_min", "total_port_count")

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

                    number = as_float(value) if name in numeric_fields else None
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
            "acceptance_basis": row["acceptance_basis"] if final_status == "accepted" else "",
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
    web_accepted = enriched & audit["acceptance_basis"].eq(WEB_EVIDENCE_POLICY)
    strict_accepted = enriched & audit["acceptance_basis"].eq("strict_match")

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
    audit.loc[web_accepted].to_csv(
        settings.audit_dir / "task3_web_rule_accepted.csv", index=False,
    )
    duplicates.to_csv(
        settings.audit_dir / "task3_duplicate_external_id_report.csv",
        index=False,
    )

    # Record the files actually used. A missing retrieval timestamp
    # stays unknown; the file modification time is not API evidence.
    sources = []
    for label, filename, metadata_name in SNAPSHOT_FILES.values():
        path = settings.snapshot_dir / filename
        metadata_path = settings.snapshot_dir / metadata_name
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
        "strict_accepted_rows": int(strict_accepted.sum()),
        "web_rule_accepted_rows": int(web_accepted.sum()),
        "strict_accepted_coverage": float(strict_accepted.mean()),
        "web_evidence_policy": {
            "enabled": settings.accept_historical_web_candidates,
            "method": WEB_EVIDENCE_POLICY,
            "maximum_distance_m": WEB_EVIDENCE_RADIUS_M,
            "historical_evidence_levels": sorted(WEB_EVIDENCE_LEVELS),
            "candidate_selection": "one nearest DC candidate with a new attribute; OCM/OSM/Charge@Large tie-break",
            "scope": "source-row evidence, not verified external identity",
            "strict_conflicts": "retained as warnings, not vetoes under this policy",
            "manual_identity_verification": False,
        },
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
