"""Combine OCM with OSM-derived and Charge@Large candidates.

This is a new, non-destructive Task 3 trial.  It reads the existing OCM and
Charge@Large snapshots and writes only files with ``multisource`` names.

Matching rule for comparison with the group estimate:

    coordinate distance <= 500 m OR fuzzy address score >= 0.85

Distances are recalculated locally in metres.  OSM data is loaded from the
previously downloaded NSW OSM-derived public mirror pages when available;
the script can fetch those pages if the temporary files are absent.  Direct
Overpass was not used here because the public instances timed out during the
earlier data acquisition attempt.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

import task3_ocm_relaxed_match_trial as relaxed
import task3_ocm_fuzzy_address_trial as ocm_loader


ROOT = Path(__file__).resolve().parent
RESULT_DIR = ROOT / "result_data"
SOURCE_FILE = ROOT / "clean_src_data" / "nsw_ev_charging.csv"
OCM_SNAPSHOT = RESULT_DIR / "task3_ocm_tiled_snapshot.json"
CHARGELARGE_RAW = RESULT_DIR / "task3_chargelarge_raw.json"
CHARGELARGE_NSW = RESULT_DIR / "task3_chargelarge_nsw.csv"
OSM_SNAPSHOT = RESULT_DIR / "task3_osm_nsw_snapshot_for_multisource.json"
OUTPUT_FILE = RESULT_DIR / "task3_multisource_matches.csv"
SUMMARY_FILE = RESULT_DIR / "task3_multisource_summary.json"

OSM_ENDPOINT = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/osm-australia-charging-station/records"
OSM_PAGE_SIZE = 100
COORDINATE_THRESHOLD_M = 500.0
ADDRESS_THRESHOLD = 0.85


def as_bool(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_osm_pages() -> list[dict]:
    local_pages = sorted(Path("/tmp").glob("osm_nsw_*.json"))
    records = []
    if local_pages:
        for page in local_pages:
            payload = json.loads(page.read_text(encoding="utf-8"))
            records.extend(payload.get("results", []))
        return records

    offset = 0
    while True:
        params = {
            "limit": OSM_PAGE_SIZE,
            "offset": offset,
            "where": "meta_name_state='New South Wales'",
        }
        url = f"{OSM_ENDPOINT}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "COMP5339-EVCharger-ass1/0.1"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        batch = payload.get("results", [])
        records.extend(batch)
        if len(batch) < OSM_PAGE_SIZE:
            break
        offset += OSM_PAGE_SIZE
    return records


def load_osm_candidates() -> tuple[list[dict], str]:
    if OSM_SNAPSHOT.exists():
        records = json.loads(OSM_SNAPSHOT.read_text(encoding="utf-8"))
        return records, "OSM-derived public mirror snapshot"

    records = fetch_osm_pages()
    deduped = {}
    for record in records:
        osm_id = str(record.get("meta_osm_id") or "")
        if osm_id:
            deduped[osm_id] = record
    records = list(deduped.values())
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    OSM_SNAPSHOT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records, "OSM-derived public mirror snapshot"


def load_ocm_candidates() -> list[dict]:
    ocm_loader.SNAPSHOT_FILE = OCM_SNAPSHOT
    records, _ = ocm_loader.load_nsw_ocm_records()
    candidates = []
    for record in records:
        candidates.append(
            {
                "source": "OCM",
                "id": str(record.get("ev_station_id", "")),
                "latitude": as_float(record.get("latitude")),
                "longitude": as_float(record.get("longitude")),
                "address": record.get("station_address", ""),
                "postcode": record.get("postcode", ""),
                "operator": record.get("operator", ""),
                "station_name": record.get("station_name", ""),
                "attributes": {
                    "operator": record.get("operator", ""),
                    "number_of_plugs": record.get("number_of_plugs"),
                    "charger_capacities": record.get("charger_capacities", ""),
                    "plug_types": record.get("plug_types", ""),
                },
            }
        )
    return [candidate for candidate in candidates if candidate["latitude"] is not None]


def load_osm_candidate_records(records: list[dict]) -> list[dict]:
    candidates = []
    for record in records:
        point = record.get("meta_geo_point") or {}
        latitude = as_float(point.get("lat"))
        longitude = as_float(point.get("lon"))
        if latitude is None or longitude is None:
            continue
        connectors = []
        for field, label in (
            ("has_socket_combo_ccs", "CCS"),
            ("has_socket_chademo", "CHAdeMO"),
            ("has_socket_type2", "Type2"),
            ("has_socket_ef", "Schuko/EF"),
        ):
            if as_bool(record.get(field)):
                connectors.append(label)
        power = as_float(record.get("max_power_kw"))
        fast = bool({"CCS", "CHAdeMO"} & set(connectors)) or (power is not None and power >= 40)
        candidates.append(
            {
                "source": "OSM",
                "id": str(record.get("meta_osm_id", "")),
                "latitude": latitude,
                "longitude": longitude,
                "address": "",  # This normalized OSM dataset exposes no street address.
                "postcode": "",
                "operator": record.get("operator_name") or "",
                "station_name": record.get("station_name") or "",
                "fast_dc": fast,
                "attributes": {
                    "operator": record.get("operator_name") or "",
                    "number_of_plugs": record.get("charge_points_count"),
                    "charger_capacities": record.get("max_power_kw"),
                    "plug_types": "|".join(connectors),
                    "opening_hours": record.get("opening_hours") or "",
                    "access_condition": record.get("access_condition") or "",
                    "osm_last_updated": record.get("meta_last_update") or "",
                },
            }
        )
    return candidates


def load_chargelarge_candidates() -> list[dict]:
    if CHARGELARGE_NSW.exists():
        frame = pd.read_csv(CHARGELARGE_NSW)
        records = frame.to_dict("records")
    else:
        payload = json.loads(CHARGELARGE_RAW.read_text(encoding="utf-8"))
        records = []
        for record in payload:
            coordinate = record.get("coordinate") or {}
            ports = [
                port
                for charge_point in record.get("chargePoints") or []
                for port in charge_point.get("ports") or []
            ]
            powers = [as_float(port.get("powerKilowatts")) for port in ports]
            powers = [value for value in powers if value is not None]
            connectors = sorted({str(value) for port in ports for value in port.get("connectorTypes") or []})
            records.append(
                {
                    "chargelarge_id": record.get("id", ""),
                    "name": record.get("name", ""),
                    "address": record.get("address", ""),
                    "latitude": coordinate.get("latitude"),
                    "longitude": coordinate.get("longitude"),
                    "connector_types": "|".join(connectors),
                    "max_power_kw": max(powers) if powers else None,
                    "fast_dc_indicator": bool(any(value >= 40 for value in powers) or {value.upper() for value in connectors} & {"CCS2", "CCS1", "CHADEMO"}),
                    "port_count": len(ports),
                    "status_counts": "",
                }
            )
    candidates = []
    for record in records:
        latitude = as_float(record.get("latitude"))
        longitude = as_float(record.get("longitude"))
        if latitude is None or longitude is None:
            continue
        candidates.append(
            {
                "source": "Charge@Large",
                "id": str(record.get("chargelarge_id", "")),
                "latitude": latitude,
                "longitude": longitude,
                "address": record.get("address", ""),
                "postcode": "",
                "operator": "",
                "station_name": record.get("name", ""),
                "fast_dc": as_bool(record.get("fast_dc_indicator")),
                "attributes": {
                    "operator": "",
                    "number_of_plugs": record.get("port_count"),
                    "charger_capacities": record.get("max_power_kw"),
                    "plug_types": record.get("connector_types", ""),
                    "status_counts": record.get("status_counts", ""),
                },
            }
        )
    return candidates


def source_row_candidates(source: pd.DataFrame, candidates: list[dict]) -> pd.DataFrame:
    rows = []
    for source_index, row in source.iterrows():
        source_address = relaxed.address_parts(row.get("Station_address"), row.get("PCODE"))
        scored = []
        for candidate in candidates:
            distance = relaxed.distance_metres(
                row.get("Latitude"), row.get("Longitude"),
                candidate["latitude"], candidate["longitude"],
            )
            candidate_address = relaxed.address_parts(candidate.get("address"), candidate.get("postcode"))
            score = relaxed.address_score(source_address, candidate_address)
            address_ok = bool(candidate.get("address")) and score >= ADDRESS_THRESHOLD and relaxed.address_accepted(source_address, candidate_address, score)
            coordinate_ok = distance <= COORDINATE_THRESHOLD_M
            if coordinate_ok or address_ok:
                scored.append(
                    {
                        "candidate": candidate,
                        "distance": distance,
                        "address_score": score,
                        "coordinate_ok": coordinate_ok,
                        "address_ok": address_ok,
                    }
                )
        scored.sort(
            key=lambda item: (
                not (item["coordinate_ok"] and item["address_ok"]),
                not item["coordinate_ok"],
                item["distance"],
                -item["address_score"],
            )
        )
        best = scored[0] if scored else None
        candidate = best["candidate"] if best else {}
        rows.append(
            {
                "source_index": source_index,
                "source_station_address": row.get("Station_address", ""),
                "source_operator": row.get("Operator", ""),
                "match_status": "accepted" if best else "unmatched",
                "match_method": (
                    "coordinate_and_fuzzy_address" if best and best["coordinate_ok"] and best["address_ok"]
                    else "coordinate_500m" if best and best["coordinate_ok"]
                    else "fuzzy_address_only" if best else "unmatched"
                ),
                "match_distance_m": best["distance"] if best else None,
                "address_score": best["address_score"] if best else None,
                "candidate_count": len(scored),
                "matched_id": candidate.get("id", ""),
                "matched_station_name": candidate.get("station_name", ""),
                "matched_address": candidate.get("address", ""),
                "matched_operator": candidate.get("operator", ""),
                "matched_fast_dc_indicator": candidate.get("fast_dc", ""),
                "matched_attributes": json.dumps(candidate.get("attributes", {}), ensure_ascii=False, sort_keys=True),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    source = pd.read_csv(SOURCE_FILE)
    source = source[source["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")].copy()

    osm_raw, osm_provider = load_osm_candidates()
    ocm = load_ocm_candidates()
    osm = load_osm_candidate_records(osm_raw)
    chargelarge = load_chargelarge_candidates()

    per_source = {
        "OCM": source_row_candidates(source, ocm),
        "OSM_all": source_row_candidates(source, osm),
        "OSM_fast_dc": source_row_candidates(source, [c for c in osm if c.get("fast_dc")]),
        "ChargeLarge_all": source_row_candidates(source, chargelarge),
        "ChargeLarge_fast_dc": source_row_candidates(source, [c for c in chargelarge if c.get("fast_dc")]),
    }

    # Reset the output index so it has the same 0..N-1 row identity as the
    # per-source frames. Preserve the original cleaned-source index explicitly.
    original_source_index = source.index.to_list()
    output = source[["Station_name", "Station_address", "Operator", "Number_of_plugs", "Charger_Type", "Charger_rating", "Latitude", "Longitude", "LGANAME", "PCODE", "Source"]].reset_index(drop=True).copy()
    output.insert(0, "source_index", original_source_index)
    for label, frame in per_source.items():
        prefix = label.lower()
        output[f"{prefix}_status"] = frame["match_status"].values
        output[f"{prefix}_method"] = frame["match_method"].values
        output[f"{prefix}_distance_m"] = frame["match_distance_m"].values
        output[f"{prefix}_address_score"] = frame["address_score"].values
        output[f"{prefix}_id"] = frame["matched_id"].values
        output[f"{prefix}_address"] = frame["matched_address"].values
        output[f"{prefix}_attributes"] = frame["matched_attributes"].values

    accepted_sets = {
        label: set(frame.index[frame["match_status"].eq("accepted")])
        for label, frame in per_source.items()
    }
    broad_union = accepted_sets["OCM"] | accepted_sets["OSM_all"] | accepted_sets["ChargeLarge_all"]
    dc_union = accepted_sets["OCM"] | accepted_sets["OSM_fast_dc"] | accepted_sets["ChargeLarge_fast_dc"]
    output["combined_broad_status"] = ["accepted" if index in broad_union else "unmatched" for index in output.index]
    output["combined_dc_indicated_status"] = ["accepted" if index in dc_union else "unmatched" for index in output.index]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_FILE, index=False)
    summary = {
        "source_dc_rows": len(source),
        "osm_provider": osm_provider,
        "candidate_counts": {
            "ocm_nsw": len(ocm),
            "osm_nsw": len(osm),
            "osm_fast_dc": sum(bool(c.get("fast_dc")) for c in osm),
            "chargelarge_nsw": len(chargelarge),
            "chargelarge_fast_dc": sum(bool(c.get("fast_dc")) for c in chargelarge),
        },
        "rules": {
            "coordinate_or_fuzzy_address": True,
            "coordinate_threshold_m": COORDINATE_THRESHOLD_M,
            "address_threshold": ADDRESS_THRESHOLD,
            "distance_calculation": "local Haversine metres",
            "one_to_one_enforced": False,
        },
        "accepted_counts": {
            label: int(frame["match_status"].eq("accepted").sum())
            for label, frame in per_source.items()
        },
        "accepted_coverages": {
            label: float(frame["match_status"].eq("accepted").mean())
            for label, frame in per_source.items()
        },
        "combined_broad_count": len(broad_union),
        "combined_broad_coverage": len(broad_union) / len(source),
        "combined_dc_indicated_count": len(dc_union),
        "combined_dc_indicated_coverage": len(dc_union) / len(source),
        "output_file": str(OUTPUT_FILE.relative_to(ROOT)),
        "osm_snapshot_file": str(OSM_SNAPSHOT.relative_to(ROOT)),
    }
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
