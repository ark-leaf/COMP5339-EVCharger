"""Build a transparent, one-row-per-TfNSW-record Task 3 audit CSV.

This consumes the team's existing OCM/OSM/Charge@Large matching snapshot and
adds source provenance, a stable TfNSW row key, review state, and a clear split
between coordinate-supported automatic candidates and address-only candidates.
It does not modify the raw TfNSW data or the team's source matching output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parent
RAW_TFNSW = ROOT / "src_data" / "nsw_ev_charging.csv"
CLEAN_TFNSW = ROOT / "clean_src_data" / "nsw_ev_charging.csv"
MATCHES = ROOT / "result_data" / "task3_multisource_matches.csv"
OCM_METADATA = ROOT / "result_data" / "task3_ocm_tiled_snapshot_metadata.json"
OSM_SNAPSHOT = ROOT / "result_data" / "task3_osm_nsw_snapshot_for_multisource.json"
CHARGELARGE_SUMMARY = ROOT / "result_data" / "task3_chargelarge_summary.json"
OUTPUT_DIR = ROOT / "result_data" / "task3_final_multisource_output"
OCM_WEB_CONFIDENCE = OUTPUT_DIR / "task3_ocm_125_web_confidence.csv"
NON_OCM_WEB_VERIFIED = OUTPUT_DIR / "task3_104_non_ocm_web_verified.csv"

SOURCE_CONFIG = {
    "ocm": {"label": "OCM", "id": "ocm_id", "status": "ocm_status", "method": "ocm_method", "distance": "ocm_distance_m", "address": "ocm_address", "address_score": "ocm_address_score", "gap": "ocm_nearest_coordinate_gap_m"},
    "osm_fast_dc": {"label": "OSM", "id": "osm_fast_dc_id", "status": "osm_fast_dc_status", "method": "osm_fast_dc_method", "distance": "osm_fast_dc_distance_m", "address": "osm_fast_dc_address", "address_score": "osm_fast_dc_address_score", "gap": "osm_fast_dc_nearest_coordinate_gap_m"},
    "chargelarge_fast_dc": {"label": "Charge@Large", "id": "chargelarge_fast_dc_id", "status": "chargelarge_fast_dc_status", "method": "chargelarge_fast_dc_method", "distance": "chargelarge_fast_dc_distance_m", "address": "chargelarge_fast_dc_address", "address_score": "chargelarge_fast_dc_address_score", "gap": "chargelarge_fast_dc_nearest_coordinate_gap_m"},
}


def text(value: Any) -> str:
    if value is None:
        return ""
    try:
        missing = pd.isna(value)
        if getattr(missing, "ndim", 0) == 0 and bool(missing):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def numeric(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def identifier(value: Any) -> str:
    """Keep identifiers as text and remove CSV-induced numeric suffixes."""
    value = text(value)
    if re.fullmatch(r"\d+\.0", value):
        return value[:-2]
    return value


def parse_attributes(value: Any) -> dict[str, Any]:
    raw = text(value)
    if not raw or raw == "{}":
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def is_coordinate_supported(row: pd.Series, config: dict[str, str]) -> bool:
    if text(row[config["status"]]) != "accepted":
        return False
    method = text(row[config["method"]])
    distance = numeric(row[config["distance"]])
    return "coordinate" in method and distance is not None and distance <= 100.0


def is_accepted(row: pd.Series, config: dict[str, str]) -> bool:
    return text(row[config["status"]]) == "accepted"


def join_unique(values: list[str]) -> str:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return ";".join(result)


def load_web_rows(path: Path) -> dict[int, dict[str, str]]:
    """Load an existing web-review CSV without making web evidence mandatory."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    rows: dict[int, dict[str, str]] = {}
    for _, row in frame.iterrows():
        try:
            source_index = int(row["source_index"])
        except (KeyError, TypeError, ValueError):
            continue
        rows[source_index] = {
            "ocm_id": identifier(row.get("ocm_id")),
            "matched_source": text(row.get("matched_source")),
            "matched_external_addresses": text(row.get("matched_external_addresses")),
            "confidence": text(row.get("web_evidence_confidence")),
            "url": text(row.get("web_evidence_url")),
            "decision": text(row.get("match_identity_decision")),
            "reason": text(row.get("web_evidence_confidence_reason")),
        }
    return rows


def actual_value(value: Any) -> bool:
    """Do not count empty collections or descriptive metadata as new facts."""
    return value is not None and value != "" and value != [] and value != {}


def explicit_negative(decision: str) -> bool:
    decision = decision.lower()
    return any(token in decision for token in ("negative", "do not accept", "not the same", "reject", "incorrect"))


def duplicate_external_id_rows(output: pd.DataFrame) -> pd.DataFrame:
    """Return all external IDs assigned to more than one TfNSW row."""
    duplicate_rows: list[dict[str, Any]] = []
    for key, config in SOURCE_CONFIG.items():
        accepted = output[config["status"]].map(text).eq("accepted")
        ids = output.loc[accepted, config["id"]].map(text)
        for external_id, positions in ids.groupby(ids):
            if not external_id or len(positions) < 2:
                continue
            source_rows = output.loc[positions.index, "tfnsw_unique_id"].map(text).tolist()
            duplicate_rows.append(
                {
                    "source": config["label"],
                    "external_id": external_id,
                    "tfnsw_row_count": len(source_rows),
                    "tfnsw_unique_ids": ";".join(source_rows),
                }
            )
    return pd.DataFrame(
        duplicate_rows,
        columns=["source", "external_id", "tfnsw_row_count", "tfnsw_unique_ids"],
    ).sort_values(["source", "external_id"]).reset_index(drop=True)


def main() -> None:
    raw = pd.read_csv(RAW_TFNSW, dtype={"PCODE": "string"}, keep_default_na=False)
    clean = pd.read_csv(CLEAN_TFNSW, dtype={"PCODE": "string"}, keep_default_na=False)
    matches = pd.read_csv(
        MATCHES,
        dtype={
            "PCODE": "string",
            "ocm_id": "string",
            "osm_all_id": "string",
            "osm_fast_dc_id": "string",
            "chargelarge_all_id": "string",
            "chargelarge_fast_dc_id": "string",
        },
        keep_default_na=False,
    )
    matches = matches.sort_values("source_index").reset_index(drop=True)
    for column in (
        "ocm_id", "osm_all_id", "osm_fast_dc_id",
        "chargelarge_all_id", "chargelarge_fast_dc_id",
    ):
        if column in matches.columns:
            matches[column] = matches[column].map(identifier)

    # source_index is the original zero-based row index in the cleaned TfNSW
    # file. The raw and cleaned files retain the same 1,958-row order.
    raw_dc = raw.loc[matches["source_index"].astype(int)].reset_index(drop=True)
    clean_dc = clean.loc[matches["source_index"].astype(int)].reset_index(drop=True)
    output = matches.copy()
    output.insert(0, "tfnsw_unique_id", [f"TFNSW-{int(i) + 2:04d}" for i in matches["source_index"]])
    output.insert(1, "tfnsw_table_row", matches["source_index"].astype(int) + 2)
    output.insert(2, "tfnsw_raw_station_address", raw_dc["Station_address"])
    output.insert(3, "tfnsw_cleaned_station_address", clean_dc["Station_address"])
    output.insert(4, "tfnsw_raw_postcode", raw_dc["PCODE"])
    output.insert(5, "tfnsw_cleaned_postcode", clean_dc["PCODE"])

    source_statuses: list[str] = []
    source_methods: list[str] = []
    source_ids: list[str] = []
    source_addresses: list[str] = []
    coordinate_sources: list[str] = []
    review_sources: list[str] = []
    review_ids: list[str] = []
    distances: list[float] = []
    nearest_gaps: list[float] = []
    selected_attributes: list[str] = []
    attribute_counts: list[int] = []
    review_reasons: list[str] = []
    source_count: list[int] = []
    coordinate_count: list[int] = []
    aggregate_address_scores: list[float] = []
    conflict_flags: list[str] = []

    for _, row in output.iterrows():
        accepted = []
        coordinate = []
        review = []
        row_ids = []
        row_addresses = []
        row_review_ids = []
        row_distances = []
        row_gaps = []
        row_attrs: dict[str, Any] = {}
        row_review_reasons = []
        numeric_values: dict[str, set[float]] = {"number_of_plugs": set(), "power_kw_max": set()}
        for key, config in SOURCE_CONFIG.items():
            if is_accepted(row, config):
                accepted.append(config["label"])
                if text(row[config["id"]]):
                    row_ids.append(f"{config['label']}:{text(row[config['id']])}")
                if text(row[config["address"]]):
                    row_addresses.append(f"{config['label']}:{text(row[config['address']])}")
                distance = numeric(row[config["distance"]])
                if distance is not None:
                    row_distances.append(distance)
                gap = numeric(row.get(config["gap"]))
                if gap is not None:
                    row_gaps.append(gap)
                if is_coordinate_supported(row, config):
                    coordinate.append(config["label"])
                attrs = parse_attributes(row.get(f"{key}_attributes", "{}"))
                for attr, value in attrs.items():
                    if actual_value(value):
                        row_attrs[f"{config['label']}::{attr}"] = value
                    if attr in numeric_values:
                        number = numeric(value)
                        if number is not None and number > 0:
                            numeric_values[attr].add(number)
            elif text(row[config["status"]]) == "review":
                review.append(config["label"])
                if text(row[config["id"]]):
                    row_review_ids.append(f"{config['label']}:{text(row[config['id']])}")
                row_review_reasons.append(
                    f"{config['label']}: {text(row.get(f'{key}_review_reason')) or 'candidate requires verification'}"
                )

        conflicts = [name for name, values in numeric_values.items() if len(values) > 1]
        if conflicts:
            row_review_reasons.append("accepted sources disagree on " + ", ".join(conflicts))
        conflict_flags.append(join_unique(conflicts))

        source_statuses.append(join_unique(accepted))
        source_methods.append(join_unique([
            f"{config['label']}:{text(row[config['method']])}"
            for config in SOURCE_CONFIG.values()
            if is_accepted(row, config)
        ]))
        source_ids.append(join_unique(row_ids))
        source_addresses.append(join_unique(row_addresses))
        coordinate_sources.append(join_unique(coordinate))
        review_sources.append(join_unique(review))
        review_ids.append(join_unique(row_review_ids))
        distances.append(min(row_distances) if row_distances else float("nan"))
        nearest_gaps.append(min(row_gaps) if row_gaps else float("nan"))
        selected_attributes.append(json.dumps(row_attrs, ensure_ascii=False, sort_keys=True))
        attribute_counts.append(len(row_attrs))
        review_reasons.append("; ".join(row_review_reasons))
        source_count.append(len(accepted))
        coordinate_count.append(len(coordinate))
        accepted_scores = [
            numeric(row[config["address_score"]])
            for config in SOURCE_CONFIG.values()
            if is_accepted(row, config) and config["address_score"] in row.index
        ]
        accepted_scores = [value for value in accepted_scores if value is not None]
        aggregate_address_scores.append(max(accepted_scores) if accepted_scores else float("nan"))

    output["matched_source"] = source_statuses
    output["matched_source_count"] = source_count
    output["coordinate_supported_source"] = coordinate_sources
    output["coordinate_supported_source_count"] = coordinate_count
    output["review_candidate_source"] = review_sources
    output["review_candidate_external_ids"] = review_ids
    output["address_only_source"] = [join_unique([
        config["label"] for config in SOURCE_CONFIG.values()
        if text(row[config["status"]]) == "review" and text(row[config["method"]]) == "fuzzy_address_only"
    ]) for _, row in output.iterrows()]
    output["matched_external_ids"] = source_ids
    output["matched_external_addresses"] = source_addresses
    output["minimum_match_distance_m"] = distances
    output["augmentation_nearest_distance_m"] = distances
    output["augmentation_nearest_gap_m"] = nearest_gaps
    output["augmentation_attributes_by_source"] = selected_attributes
    output["augmentation_attribute_count"] = attribute_counts
    genuinely_new_attribute_names = {
        "plug_types", "connector_types_normalized", "opening_hours",
        "access_condition", "status_counts", "status",
        "is_operational", "operational_status", "usage_cost", "general_comments",
        "power_kw_min", "power_kw_max",
        "dc_port_count", "total_port_count",
    }
    output["new_attribute_count"] = output["augmentation_attributes_by_source"].map(
        lambda raw: sum(
            key.rsplit("::", 1)[-1] in genuinely_new_attribute_names
            for key, value in parse_attributes(raw).items()
            if actual_value(value)
        )
    )
    output["has_new_attributes"] = output["new_attribute_count"] > 0
    output["match_method_summary"] = source_methods
    output["augmentation_conflict_flags"] = conflict_flags
    output["manual_review_reason"] = review_reasons
    output["manual_review_required"] = ["yes" if value else "no" for value in review_reasons]
    output["manual_review_status"] = [
        "pending" if reason else "not_required_for_initial_auto_rule" if status else "not_matched"
        for status, reason in zip(source_statuses, review_reasons)
    ]
    # Keep the original broad and DC-indicated union fields, then expose the
    # stricter split used by this audit.
    output["final_audit_status"] = [
        "accepted_coordinate_supported" if coordinate else "review_candidate" if review else "unmatched"
        for coordinate, review in zip(coordinate_sources, review_sources)
    ]
    output["final_audit_confidence"] = [
        "medium_review" if reason else "high" if coordinate else "none"
        for coordinate, reason in zip(coordinate_sources, review_reasons)
    ]
    output["manual_review_decision"] = [
        "pending" if reason else "not_required" if status == "accepted_coordinate_supported" else "not_applicable"
        for status, reason in zip(output["final_audit_status"], review_reasons)
    ]

    # Generic fields required by the assignment sit alongside the source-
    # specific columns above. The source-specific values remain authoritative
    # when multiple external sources disagree.
    output["match_source"] = output["matched_source"]
    output["match_method"] = output["match_method_summary"]
    output["external_id"] = output["matched_external_ids"]
    output["external_address"] = output["matched_external_addresses"]
    output["match_distance_m"] = output["minimum_match_distance_m"]
    output["address_score"] = aggregate_address_scores
    output["augmented_attributes"] = output["augmentation_attributes_by_source"]
    output["confidence"] = output["final_audit_confidence"]

    # Historical web notes are bound to the external record they reviewed.
    # The non-OCM file has no external ID, so retain it as context only.
    ocm_web = load_web_rows(OCM_WEB_CONFIDENCE)
    non_ocm_web = load_web_rows(NON_OCM_WEB_VERIFIED)
    web_urls: list[str] = []
    web_confidences: list[str] = []
    web_decisions: list[str] = []
    web_reasons: list[str] = []
    evidence_screened: list[str] = []
    evidence_screened_reasons: list[str] = []
    for _, row in output.iterrows():
        source_index = int(row["source_index"])
        ocm_match = text(row["ocm_status"]) == "accepted"
        ocm_both_rules = ocm_match and text(row["ocm_method"]) == "coordinate_and_fuzzy_address"
        old_ocm = ocm_web.get(source_index)
        review = old_ocm if (ocm_match and old_ocm and old_ocm["ocm_id"] == identifier(row["ocm_id"])) else None
        if not review and not ocm_match:
            old_non_ocm = non_ocm_web.get(source_index)
            if (old_non_ocm and old_non_ocm["matched_source"] == text(row["matched_source"])
                    and old_non_ocm["matched_external_addresses"] == text(row["matched_external_addresses"])):
                review = old_non_ocm
        negative = bool(review and explicit_negative(review["decision"]))
        eligible = text(row["final_audit_status"]) == "accepted_coordinate_supported" and text(row["manual_review_required"]) == "no"
        if ocm_both_rules and eligible and not negative:
            confidence = "local_two_rule_support"
            decision = "local coordinate and fuzzy-address evidence agree"
            reason = "Both local matching rules passed; no individual web search was required by the audit plan."
            screened = True
            screened_reason = "OCM coordinate and fuzzy-address evidence both passed."
        elif review:
            confidence = review["confidence"] or "unreviewed"
            decision = review["decision"]
            reason = review["reason"]
            screened = bool(review is old_ocm and eligible and confidence in {"high", "medium"} and not negative)
            screened_reason = (
                "Current OCM ID has non-negative high/medium historical web evidence."
                if screened
                else "Historical evidence is negative, unbound to an external ID, or needs review."
            )
        else:
            confidence = "unreviewed" if text(row["matched_source"]) else "none"
            decision = ""
            reason = ""
            screened = False
            screened_reason = "No accepted external match or no review bound to the current external record."
        web_urls.append(review["url"] if review else "")
        web_confidences.append(confidence)
        web_decisions.append(decision)
        web_reasons.append(reason)
        evidence_screened.append("provisionally_supported" if screened else "not_screened")
        evidence_screened_reasons.append(screened_reason)

    output["web_evidence_url"] = web_urls
    output["web_evidence_confidence"] = web_confidences
    output["web_evidence_confidence_reason"] = web_reasons
    output["match_identity_decision"] = web_decisions
    output["evidence_screened_status"] = evidence_screened
    output["evidence_screened_reason"] = evidence_screened_reasons

    # Diagnostic URLs are source-level references, not claims that a web page
    # independently validates every matched record.
    output["ocm_evidence_url"] = output["ocm_id"].map(
        lambda value: f"https://openchargemap.org/site/poi/details/{int(float(value))}" if text(value) else ""
    )
    output["osm_evidence_url"] = output["osm_fast_dc_id"].map(
        lambda value: f"https://www.openstreetmap.org/node/{int(float(value))}" if text(value) else ""
    )
    output["chargelarge_evidence_url"] = output["chargelarge_fast_dc_id"].map(
        lambda value: "https://chargeatlarge.app/" if text(value) else ""
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "task3_multisource_final_audit.csv"
    review_path = OUTPUT_DIR / "task3_multisource_manual_review_queue.csv"
    duplicate_path = OUTPUT_DIR / "task3_duplicate_external_id_report.csv"
    output.to_csv(output_path, index=False)
    output[output["manual_review_required"].eq("yes")].to_csv(review_path, index=False)
    duplicates = duplicate_external_id_rows(output)
    duplicates.to_csv(duplicate_path, index=False)

    def counts_for(prefix: str) -> dict[str, Any]:
        status = output[f"{prefix}_status"]
        ids = output.loc[status.eq("accepted"), f"{prefix}_id"].dropna().astype(str)
        ids = ids[ids.ne("")]
        return {
            "accepted_rows": int(status.eq("accepted").sum()),
            "unique_external_ids": int(ids.nunique()),
            "duplicate_row_assignments": int(len(ids) - ids.nunique()),
        }

    summary = {
        "tfnsw_dc_rows": len(output),
        "unique_tfnsw_rows": int(output["tfnsw_unique_id"].nunique()),
        "ocm_only_baseline_rows": int(output["ocm_status"].eq("accepted").sum()),
        "multi_source_candidate_rows": int(output["final_audit_status"].isin(["accepted_coordinate_supported", "review_candidate"]).sum()),
        "multi_source_candidate_coverage": round(float(output["final_audit_status"].isin(["accepted_coordinate_supported", "review_candidate"]).mean()), 4),
        "coordinate_supported_rows": int(output["final_audit_status"].eq("accepted_coordinate_supported").sum()),
        "coordinate_supported_coverage": round(float(output["final_audit_status"].eq("accepted_coordinate_supported").mean()), 4),
        "manual_review_only_rows": int(output["final_audit_status"].eq("review_candidate").sum()),
        "manual_review_only_coverage": round(float(output["final_audit_status"].eq("review_candidate").mean()), 4),
        "manual_review_queue_rows": int(output["manual_review_required"].eq("yes").sum()),
        "accepted_without_review_rows": int((output["final_audit_status"].eq("accepted_coordinate_supported") & output["manual_review_required"].eq("no")).sum()),
        "numeric_conflict_rows": int(output["augmentation_conflict_flags"].ne("").sum()),
        "unmatched_rows": int(output["final_audit_status"].eq("unmatched").sum()),
        "evidence_screened_rows": int(output["evidence_screened_status"].eq("provisionally_supported").sum()),
        "evidence_screened_coverage": round(float(output["evidence_screened_status"].eq("provisionally_supported").mean()), 4),
        "evidence_screened_status_counts": output["evidence_screened_status"].value_counts().to_dict(),
        "source_diagnostics": {key: counts_for(key) for key in ("ocm", "osm_fast_dc", "chargelarge_fast_dc")},
        "duplicate_external_id_groups": int(len(duplicates)),
        "rules_inherited_from_team_trial": {
            "candidate_coordinate_threshold_m": 500,
            "automatic_coordinate_threshold_m": 100,
            "fuzzy_address_threshold": 0.85,
            "one_to_one_enforced": False,
            "union_denominator": "433 unique TfNSW DC rows",
        },
        "audit_policy": {
            "coordinate_supported": "within 100m with no postcode contradiction or close competing coordinate candidate",
            "review_candidate": "500m/address candidate failing automatic safeguards; not exported as accepted attributes",
            "numeric_conflicts": "conflicting accepted-source plug counts/power are flagged and require manual review",
            "unmatched": "no accepted result from the three selected DC-indicated sources",
            "source_provenance": "each source result remains in its own columns; no source values are overwritten",
        },
        "input_files": {
            "raw_tfnsw": str(RAW_TFNSW.relative_to(ROOT)),
            "clean_tfnsw": str(CLEAN_TFNSW.relative_to(ROOT)),
            "existing_multisource_matches": str(MATCHES.relative_to(ROOT)),
            "ocm_metadata": str(OCM_METADATA.relative_to(ROOT)),
            "osm_snapshot": str(OSM_SNAPSHOT.relative_to(ROOT)),
            "chargelarge_summary": str(CHARGELARGE_SUMMARY.relative_to(ROOT)),
        },
        "outputs": {
            "final_audit_csv": str(output_path.relative_to(ROOT)),
            "manual_review_csv": str(review_path.relative_to(ROOT)),
            "duplicate_external_id_csv": str(duplicate_path.relative_to(ROOT)),
        },
        "warning": "The multi_source_candidate_rows value is a row-level candidate count, not a count of unique external stations and not a completed manual validation result.",
    }
    summary_path = OUTPUT_DIR / "task3_multisource_final_audit_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
