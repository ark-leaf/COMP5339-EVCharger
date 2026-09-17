"""Relaxed, auditable OCM matching trial for Task 3.

Rules requested for comparison with the group estimate:

* accept a candidate when either the nearest coordinate is within 500 metres,
  or the structured address has a strong fuzzy match;
* use metres calculated locally, so OCM's distance-unit default cannot affect
  the final rule;
* preserve house numbers and only remove the final postcode from addresses;
* report both row-level candidate coverage and a one-to-one coverage check.

This is an isolated trial.  It does not change the main pipeline.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import unicodedata
from pathlib import Path

import pandas as pd

import task3_ocm_fuzzy_address_trial as strict_trial


ROOT = Path(__file__).resolve().parent
SOURCE_FILE = ROOT / "clean_src_data" / "nsw_ev_charging.csv"
SNAPSHOT_FILE = ROOT / "result_data" / "task3_ocm_tiled_snapshot.json"
OUTPUT_FILE = ROOT / "result_data" / "task3_ocm_relaxed_matches.csv"
SUMMARY_FILE = ROOT / "result_data" / "task3_ocm_relaxed_match_summary.json"

COORDINATE_THRESHOLD_M = 500.0
ADDRESS_THRESHOLD = 0.85
STREET_THRESHOLD = 0.75
FULL_ADDRESS_THRESHOLD = 0.88

STREET_TYPES = {
    "street": "st", "st": "st", "road": "rd", "rd": "rd",
    "avenue": "ave", "ave": "ave", "drive": "dr", "dr": "dr",
    "highway": "hwy", "hwy": "hwy", "lane": "ln", "ln": "ln",
    "place": "pl", "pl": "pl", "parade": "pde", "pde": "pde",
    "crescent": "cres", "cres": "cres", "boulevard": "bvd", "bvd": "bvd",
    "terrace": "tce", "tce": "tce", "close": "cl", "cl": "cl",
    "circuit": "cct", "cct": "cct", "esplanade": "esp", "esp": "esp",
    "way": "way", "wy": "way",
}
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+[A-Za-z]?(?:\s*[-/]\s*\d+[A-Za-z]?)?(?![A-Za-z0-9])")
POSTCODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def clean_number(value: str) -> str:
    value = re.sub(r"\s+", "", value.lower())
    return value.replace("–", "-").replace("—", "-")


def address_parts(address, postcode_value="") -> dict[str, str]:
    raw = unicodedata.normalize("NFKC", text(address)).lower()
    raw = raw.replace("new south wales", " ").replace("australia", " ")
    raw = re.sub(r"\bnsw\b", " ", raw)

    postcode_candidates = POSTCODE_RE.findall(text(postcode_value))
    if postcode_candidates:
        postcode = postcode_candidates[-1]
    else:
        address_postcodes = POSTCODE_RE.findall(raw)
        postcode = address_postcodes[-1] if address_postcodes else ""
        if postcode:
            # Remove only the final postcode, not every four-digit number.
            raw = re.sub(rf"(?<!\d){re.escape(postcode)}(?!\d)\s*$", " ", raw)

    # Turn punctuation such as commas into separators while preserving
    # hyphens/slashes used in Australian address numbers such as 20-22 or
    # 85/91.  Keeping commas attached to tokens would hide street types like
    # ``drive,`` from the alias table.
    raw = re.sub(r"[^a-z0-9/-]+", " ", raw)
    tokens = [STREET_TYPES.get(token, token) for token in raw.split()]
    number_matches = list(NUMBER_RE.finditer(raw))
    house_number = clean_number(number_matches[0].group(0)) if number_matches else ""

    street_core = ""
    for type_index, token in enumerate(tokens):
        if token not in set(STREET_TYPES.values()):
            continue
        number_index = None
        for index in range(type_index - 1, max(-1, type_index - 8), -1):
            if index >= 0 and NUMBER_RE.fullmatch(tokens[index]):
                number_index = index
                break
        if number_index is not None:
            house_number = clean_number(tokens[number_index])
            street_tokens = tokens[number_index + 1 : type_index]
        else:
            street_tokens = tokens[max(0, type_index - 4) : type_index]
        if street_tokens:
            street_core = " ".join(street_tokens + [token])
            break

    normalised = " ".join(tokens)
    return {
        "postcode": postcode,
        "house_number": house_number,
        "street_core": street_core,
        "normalised": normalised,
    }


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def token_similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return 2 * len(left_tokens & right_tokens) / (len(left_tokens) + len(right_tokens))


def address_score(source: dict[str, str], candidate: dict[str, str]) -> float:
    street = similarity(source["street_core"], candidate["street_core"])
    full = similarity(source["normalised"], candidate["normalised"])
    postcode = float(bool(source["postcode"] and source["postcode"] == candidate["postcode"]))
    house_number = float(
        bool(source["house_number"] and source["house_number"] == candidate["house_number"])
    )
    return 0.55 * street + 0.20 * full + 0.15 * postcode + 0.10 * house_number


def address_accepted(source: dict[str, str], candidate: dict[str, str], score: float) -> bool:
    street = similarity(source["street_core"], candidate["street_core"])
    full = similarity(source["normalised"], candidate["normalised"])
    postcode_match = bool(source["postcode"] and source["postcode"] == candidate["postcode"])
    house_match = bool(source["house_number"] and source["house_number"] == candidate["house_number"])
    return (
        score >= ADDRESS_THRESHOLD
        and (street >= STREET_THRESHOLD or full >= FULL_ADDRESS_THRESHOLD)
        and (postcode_match or house_match)
    )


def distance_metres(lat_a, lon_a, lat_b, lon_b) -> float:
    radius = 6_371_000.0
    phi_a, phi_b = math.radians(float(lat_a)), math.radians(float(lat_b))
    d_phi = math.radians(float(lat_b) - float(lat_a))
    d_lambda = math.radians(float(lon_b) - float(lon_a))
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, value)))


def load_data() -> tuple[pd.DataFrame, list[dict]]:
    source = pd.read_csv(SOURCE_FILE)
    source = source[source["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")].copy()
    strict_trial.SNAPSHOT_FILE = SNAPSHOT_FILE
    records, _ = strict_trial.load_nsw_ocm_records()
    return source, records


def make_matches(source: pd.DataFrame, records: list[dict]) -> pd.DataFrame:
    candidates = []
    for index, record in enumerate(records):
        try:
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        candidates.append(
            {
                "index": index,
                "record": record,
                "latitude": latitude,
                "longitude": longitude,
                "address": address_parts(record.get("station_address"), record.get("postcode")),
            }
        )

    rows = []
    for source_index, row in source.iterrows():
        source_address = address_parts(row.get("Station_address"), row.get("PCODE"))
        distance_candidates = []
        address_candidates = []
        for candidate in candidates:
            distance = distance_metres(
                row.get("Latitude"), row.get("Longitude"),
                candidate["latitude"], candidate["longitude"],
            )
            score = address_score(source_address, candidate["address"])
            distance_candidates.append((distance, candidate))
            if address_accepted(source_address, candidate["address"], score):
                address_candidates.append((score, distance, candidate))

        distance_candidates.sort(key=lambda item: item[0])
        address_candidates.sort(key=lambda item: (-item[0], item[1]))
        nearest_distance, nearest = distance_candidates[0]
        coordinate_ok = nearest_distance <= COORDINATE_THRESHOLD_M
        address_best = address_candidates[0] if address_candidates else None
        address_ok = address_best is not None

        selected = None
        method = "unmatched"
        if coordinate_ok and address_ok and address_best[2]["index"] == nearest["index"]:
            selected = nearest
            method = "coordinate_and_fuzzy_address"
        elif coordinate_ok and address_ok:
            # Prefer the address candidate only when it is also nearby; this
            # prevents a strong but unrelated address from overriding a clear
            # coordinate match.
            if address_best[1] <= COORDINATE_THRESHOLD_M:
                selected = address_best[2]
                method = "coordinate_and_fuzzy_address"
            else:
                selected = nearest
                method = "coordinate_500m"
        elif address_ok:
            selected = address_best[2]
            method = "fuzzy_address_only"
        elif coordinate_ok:
            selected = nearest
            method = "coordinate_500m"

        selected_record = selected["record"] if selected else {}
        selected_distance = (
            distance_metres(row.get("Latitude"), row.get("Longitude"), selected["latitude"], selected["longitude"])
            if selected else None
        )
        selected_score = (
            address_score(source_address, selected["address"]) if selected else None
        )
        if not selected:
            confidence = "none"
            manual_review = True
        elif method == "fuzzy_address_only":
            # The user-requested OR rule permits address-only enrichment, but
            # an address without coordinate confirmation remains review-only.
            confidence = "medium"
            manual_review = True
        else:
            confidence = "high"
            manual_review = False
        rows.append(
            {
                "source_index": source_index,
                "station_address": text(row.get("Station_address")),
                "source_operator": text(row.get("Operator")),
                "source_latitude": row.get("Latitude"),
                "source_longitude": row.get("Longitude"),
                "match_status": "accepted" if selected else "unmatched",
                "match_method": method,
                "match_confidence": confidence,
                "manual_review_required": manual_review,
                "match_distance_m": selected_distance,
                "nearest_distance_m": nearest_distance,
                "address_score": selected_score,
                "address_candidate_count": len(address_candidates),
                "ocm_id": selected_record.get("ev_station_id", ""),
                "ocm_station_name": selected_record.get("station_name", ""),
                "ocm_station_address": selected_record.get("station_address", ""),
                "ocm_operator": selected_record.get("operator", ""),
                "ocm_number_of_plugs": selected_record.get("number_of_plugs"),
                "ocm_charger_capacities": selected_record.get("charger_capacities", ""),
                "ocm_plug_types": selected_record.get("plug_types", ""),
                "ocm_latitude": selected_record.get("latitude"),
                "ocm_longitude": selected_record.get("longitude"),
            }
        )
    return pd.DataFrame(rows)


def one_to_one_count(matches: pd.DataFrame) -> int:
    accepted = matches[matches["match_status"].eq("accepted")].copy()
    method_priority = {
        "coordinate_and_fuzzy_address": 0,
        "fuzzy_address_only": 1,
        "coordinate_500m": 2,
    }
    accepted["priority"] = accepted["match_method"].map(method_priority).fillna(9)
    accepted = accepted.sort_values(
        ["priority", "match_distance_m", "address_score"],
        ascending=[True, True, False],
        na_position="last",
    )
    used = set()
    count = 0
    for value in accepted["ocm_id"].astype("string"):
        if not value or value in used:
            continue
        used.add(value)
        count += 1
    return count


def main() -> None:
    source, records = load_data()
    matches = make_matches(source, records)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    matches.to_csv(OUTPUT_FILE, index=False)

    accepted = matches["match_status"].eq("accepted")
    summary = {
        "source_dc_rows": len(source),
        "ocm_nsw_records": len(records),
        "rules": {
            "coordinate_or_address": True,
            "coordinate_threshold_m": COORDINATE_THRESHOLD_M,
            "address_score_threshold": ADDRESS_THRESHOLD,
            "street_similarity_threshold": STREET_THRESHOLD,
            "full_address_similarity_threshold": FULL_ADDRESS_THRESHOLD,
            "local_distance_calculation": "haversine metres",
            "ocm_api_distance_unit": "not used during offline matching; API queries must explicitly use distanceunit=km",
        },
        "match_method_counts": matches["match_method"].value_counts().to_dict(),
        "match_confidence_counts": matches["match_confidence"].value_counts().to_dict(),
        "accepted_count": int(accepted.sum()),
        "accepted_coverage": float(accepted.mean()),
        "high_confidence_count": int(matches["match_confidence"].eq("high").sum()),
        "medium_address_only_count": int(matches["match_confidence"].eq("medium").sum()),
        "one_to_one_accepted_count": one_to_one_count(matches),
        "one_to_one_accepted_coverage": one_to_one_count(matches) / len(source),
        "output_file": str(OUTPUT_FILE),
    }
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
