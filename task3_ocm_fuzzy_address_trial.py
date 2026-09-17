"""Offline Task 3 trial with structured fuzzy address matching.

This experiment does not call OCM and does not modify the main pipeline. It
uses the existing OCM snapshot and Task 2 cleaned source data. Coordinate
matches are kept as the strongest evidence; fuzzy address matches are
reported as medium-confidence candidates requiring manual review.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from config import _task3_coordinate_key, _task3_distance_metres, _task3_normalise_ocm_record


ROOT = Path(__file__).resolve().parent
SOURCE_FILE = ROOT / "clean_src_data" / "nsw_ev_charging.csv"
SNAPSHOT_FILE = ROOT / "result_data" / "task3_ocm_standalone_snapshot.json"
BOUNDARY_FILE = ROOT / "src_data" / "SA4_2026_AUST_SHP_GDA2020.zip"
OUTPUT_FILE = ROOT / "result_data" / "task3_ocm_fuzzy_address_trial.csv"
SUMMARY_FILE = ROOT / "result_data" / "task3_ocm_fuzzy_address_trial_summary.json"

ADDRESS_DISTANCE_METRES = 500.0
COORDINATE_DISTANCE_METRES = 50.0
MIN_NEAREST_GAP_METRES = 20.0
MIN_ADDRESS_SCORE = 0.85
MIN_ADDRESS_SCORE_GAP = 0.05

POSTCODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
NUMBER_RE = re.compile(r"(?<![A-Za-z])(\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)?)(?!\d)")
STREET_ALIASES = {
    "street": "st", "st": "st", "road": "rd", "rd": "rd",
    "avenue": "ave", "ave": "ave", "drive": "dr", "dr": "dr",
    "highway": "hwy", "hwy": "hwy", "lane": "ln", "ln": "ln",
    "place": "pl", "pl": "pl", "parade": "pde", "pde": "pde",
    "crescent": "cres", "cres": "cres", "boulevard": "bvd", "bvd": "bvd",
    "terrace": "tce", "tce": "tce", "close": "cl", "cl": "cl",
    "way": "way", "wy": "way",
}


def text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def postcode(value) -> str:
    matches = POSTCODE_RE.findall(text(value))
    return matches[-1] if matches else ""


def normalised_tokens(value) -> list[str]:
    value = unicodedata.normalize("NFKC", text(value)).lower()
    value = value.replace("new south wales", " ")
    value = value.replace("australia", " ")
    value = POSTCODE_RE.sub(" ", value)
    value = re.sub(r"[^a-z0-9/,-]+", " ", value)
    return [STREET_ALIASES.get(token, token) for token in value.split()]


def normalised_segments(value) -> list[list[str]]:
    raw = unicodedata.normalize("NFKC", text(value)).lower()
    raw = raw.replace("new south wales", " ")
    raw = raw.replace("australia", " ")
    segments = re.split(r"[,;\n]+", raw)
    result = []
    for segment in segments:
        segment = POSTCODE_RE.sub(" ", segment)
        segment = re.sub(r"[^a-z0-9/ -]+", " ", segment)
        tokens = [STREET_ALIASES.get(token, token) for token in segment.split()]
        if tokens:
            result.append(tokens)
    return result


def house_number(value) -> str:
    match = NUMBER_RE.search(text(value))
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1)).lower()


def street_core(value) -> str:
    number = house_number(value)
    if not number:
        return ""

    street_types = set(STREET_ALIASES.values())
    for tokens in normalised_segments(value):
        try:
            number_index = next(index for index, token in enumerate(tokens) if token == number)
        except StopIteration:
            continue
        street_type_index = next(
            (
                index
                for index in range(number_index + 1, len(tokens))
                if tokens[index] in street_types
            ),
            None,
        )
        if street_type_index is not None:
            return " ".join(tokens[number_index + 1 : street_type_index + 1])
        return " ".join(tokens[number_index + 1 : number_index + 5])
    return ""


def address_parts(address, postcode_value="") -> dict:
    return {
        "postcode": postcode(postcode_value) or postcode(address),
        "house_number": house_number(address),
        "street_core": street_core(address),
    }


def address_key(parts: dict) -> tuple[str, str, str]:
    return parts["postcode"], parts["house_number"], parts["street_core"]


def address_score(source_parts: dict, ocm_parts: dict) -> float:
    if not source_parts["postcode"] or source_parts["postcode"] != ocm_parts["postcode"]:
        return 0.0
    if not source_parts["house_number"] or source_parts["house_number"] != ocm_parts["house_number"]:
        return 0.0
    source_street = source_parts["street_core"]
    ocm_street = ocm_parts["street_core"]
    if not source_street or not ocm_street:
        return 0.0
    sequence_score = difflib.SequenceMatcher(None, source_street, ocm_street).ratio()
    source_tokens = set(source_street.split())
    ocm_tokens = set(ocm_street.split())
    overlap_score = len(source_tokens & ocm_tokens) / max(1, min(len(source_tokens), len(ocm_tokens)))
    return 0.65 * sequence_score + 0.35 * overlap_score


def load_source() -> pd.DataFrame:
    source = pd.read_csv(SOURCE_FILE)
    return source[
        source["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")
    ].copy()


def load_nsw_ocm_records() -> tuple[list[dict], int]:
    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("The OCM snapshot must contain a JSON list.")

    normalised = [_task3_normalise_ocm_record(poi) for poi in payload if isinstance(poi, dict)]
    points = []
    valid_records = []
    for record in normalised:
        try:
            point = Point(float(record["longitude"]), float(record["latitude"]))
        except (KeyError, TypeError, ValueError):
            continue
        points.append(point)
        valid_records.append(record)

    boundary = gpd.read_file(f"zip://{BOUNDARY_FILE}")
    nsw_geometry = boundary[boundary["STE_NAME26"].eq("New South Wales")].geometry.union_all()
    points_gdf = gpd.GeoDataFrame(valid_records, geometry=points, crs="EPSG:4326").to_crs(
        boundary.crs
    )
    inside = points_gdf.geometry.intersects(nsw_geometry)
    return points_gdf.loc[inside].drop(columns=["geometry"]).to_dict("records"), len(normalised)


def match_records(source: pd.DataFrame, records: list[dict]) -> pd.DataFrame:
    entries = []
    coordinate_index: dict[tuple[float, float], list[dict]] = {}
    address_index: dict[tuple[str, str, str], list[dict]] = {}
    fuzzy_index: dict[tuple[str, str], list[dict]] = {}

    for reference_row, record in enumerate(records, start=2):
        coordinate = _task3_coordinate_key(record.get("latitude"), record.get("longitude"))
        parts = address_parts(record.get("station_address"), record.get("postcode"))
        entry = {"reference_row": reference_row, "record": record, "coordinate": coordinate, "parts": parts}
        entries.append(entry)
        if coordinate is not None:
            coordinate_index.setdefault(coordinate, []).append(entry)
        if all(address_key(parts)):
            address_index.setdefault(address_key(parts), []).append(entry)
        if parts["postcode"] and parts["house_number"]:
            fuzzy_index.setdefault((parts["postcode"], parts["house_number"]), []).append(entry)

    output = []
    for source_index, row in source.iterrows():
        source_coordinate = _task3_coordinate_key(row.get("Latitude"), row.get("Longitude"))
        source_parts = address_parts(row.get("Station_address"), row.get("PCODE"))
        distances = []
        if source_coordinate is not None:
            for entry in entries:
                if entry["coordinate"] is None:
                    continue
                distances.append(
                    (
                        _task3_distance_metres(
                            source_coordinate[0], source_coordinate[1],
                            entry["coordinate"][0], entry["coordinate"][1],
                        ),
                        entry,
                    )
                )
            distances.sort(key=lambda item: item[0])

        nearest_distance = distances[0][0] if distances else None
        nearest_gap = distances[1][0] - nearest_distance if len(distances) > 1 else None
        exact_coordinate_candidates = coordinate_index.get(source_coordinate, []) if source_coordinate else []

        selected = None
        status = "review"
        method = "nearest_candidate" if distances else "unmatched"
        confidence = "low"
        manual_review = True
        match_distance = nearest_distance
        address_match_score = None
        review_reason = "nearest candidate needs manual confirmation" if distances else "no OCM candidate"

        if len(exact_coordinate_candidates) == 1:
            selected = exact_coordinate_candidates[0]
            status, method, confidence, manual_review = "accepted", "coordinate_exact", "high", False
            match_distance, review_reason = 0.0, ""
        elif (
            nearest_distance is not None
            and nearest_distance <= COORDINATE_DISTANCE_METRES
            and nearest_gap is not None
            and nearest_gap >= MIN_NEAREST_GAP_METRES
        ):
            selected = distances[0][1]
            status, method, confidence, manual_review = "accepted", "coordinate_near_50m", "high", False
            review_reason = ""
        else:
            exact_address_candidates = address_index.get(address_key(source_parts), [])
            exact_address_candidates = [
                entry for entry in exact_address_candidates
                if next((d for d, candidate in distances if candidate is entry), math.inf) <= ADDRESS_DISTANCE_METRES
            ]
            if len(exact_address_candidates) == 1:
                selected = exact_address_candidates[0]
                match_distance = next(d for d, candidate in distances if candidate is selected)
                status, method, confidence = "review", "address_exact_within_500m", "medium"
                address_match_score, review_reason = 1.0, "address and coordinate evidence require review"
            else:
                fuzzy_candidates = []
                for entry in fuzzy_index.get((source_parts["postcode"], source_parts["house_number"]), []):
                    distance = next((d for d, candidate in distances if candidate is entry), math.inf)
                    if distance > ADDRESS_DISTANCE_METRES:
                        continue
                    score = address_score(source_parts, entry["parts"])
                    if score >= MIN_ADDRESS_SCORE:
                        fuzzy_candidates.append((score, distance, entry))
                fuzzy_candidates.sort(key=lambda item: (-item[0], item[1]))
                if fuzzy_candidates:
                    top = fuzzy_candidates[0]
                    second_score = fuzzy_candidates[1][0] if len(fuzzy_candidates) > 1 else 0.0
                    selected = top[2]
                    match_distance, address_match_score = top[1], top[0]
                    if top[0] - second_score >= MIN_ADDRESS_SCORE_GAP:
                        method, review_reason = "address_fuzzy_within_500m", "fuzzy address candidate requires review"
                    else:
                        method, review_reason = "address_fuzzy_ambiguous", "multiple fuzzy address candidates"
                    status, confidence = "review", "medium"
                elif distances:
                    # Keep the nearest OCM record in the review output.  It is
                    # not an accepted match, but retaining its fields makes
                    # the candidate auditable and allows manual validation.
                    selected = distances[0][1]

        record = selected["record"] if selected else {}
        output.append(
            {
                "source_index": source_index,
                "station_address": text(row.get("Station_address")),
                "source_latitude": row.get("Latitude"),
                "source_longitude": row.get("Longitude"),
                "match_status": status,
                "match_method": method,
                "confidence_band": confidence,
                "manual_review_required": manual_review,
                "match_distance_m": match_distance,
                "nearest_distance_m": nearest_distance,
                "nearest_gap_m": nearest_gap,
                "address_match_score": address_match_score,
                "review_reason": review_reason,
                "ocm_id": record.get("ev_station_id", ""),
                "ocm_station_name": record.get("station_name", ""),
                "ocm_station_address": record.get("station_address", ""),
                "ocm_latitude": record.get("latitude"),
                "ocm_longitude": record.get("longitude"),
            }
        )

    return pd.DataFrame(output)


def main() -> None:
    source = load_source()
    records, raw_count = load_nsw_ocm_records()
    result = match_records(source, records)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)

    method_counts = result["match_method"].value_counts().to_dict()
    status_counts = result["match_status"].value_counts().to_dict()
    high_count = int(result["confidence_band"].eq("high").sum())
    medium_count = int(result["confidence_band"].eq("medium").sum())
    summary = {
        "source_dc_rows": len(source),
        "raw_ocm_snapshot_records": raw_count,
        "nsw_ocm_records_after_sa4_filter": len(records),
        "rules": {
            "coordinate_high_confidence_metres": COORDINATE_DISTANCE_METRES,
            "minimum_nearest_gap_metres": MIN_NEAREST_GAP_METRES,
            "address_distance_metres": ADDRESS_DISTANCE_METRES,
            "minimum_fuzzy_address_score": MIN_ADDRESS_SCORE,
            "minimum_fuzzy_score_gap": MIN_ADDRESS_SCORE_GAP,
        },
        "method_counts": method_counts,
        "status_counts": status_counts,
        "high_confidence_count": high_count,
        "medium_review_candidate_count": medium_count,
        "high_plus_medium_count": high_count + medium_count,
        "high_plus_medium_coverage": (high_count + medium_count) / len(source),
        "output_file": str(OUTPUT_FILE),
    }
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"DC source rows: {len(source)}")
    print(f"Raw OCM records: {raw_count}")
    print(f"OCM records inside NSW SA4 boundary: {len(records)}")
    print("Methods:")
    print(result["match_method"].value_counts().to_string())
    print("Statuses:")
    print(result["match_status"].value_counts().to_string())
    print(f"High confidence: {high_count} / {len(source)} = {high_count / len(source):.1%}")
    print(f"Medium review candidates: {medium_count}")
    print(f"High + medium: {high_count + medium_count} / {len(source)} = {(high_count + medium_count) / len(source):.1%}")
    print(f"Trial output: {OUTPUT_FILE}")
    print(f"Summary: {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
