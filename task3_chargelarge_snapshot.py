"""Fetch and profile the public Charge@Large locations endpoint.

Charge@Large is used here as a supplementary source for Task 3.  The
endpoint provides addresses, coordinates, port-level power, connector types
and current status.  It does not require an API key.  The script keeps the
raw response locally and never sends or stores any credential.

Run from the repository root:

    python task3_chargelarge_snapshot.py
"""

from __future__ import annotations

import csv
import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://chargeatlarge.app/locations"
RAW_FILE = ROOT / "result_data" / "task3_chargelarge_raw.json"
NSW_FILE = ROOT / "result_data" / "task3_chargelarge_nsw.csv"
SUMMARY_FILE = ROOT / "result_data" / "task3_chargelarge_summary.json"
SOURCE_FILE = ROOT / "clean_src_data" / "nsw_ev_charging.csv"
BOUNDARY_FILE = ROOT / "src_data" / "SA4_2026_AUST_SHP_GDA2020.zip"

PARAMS = {
    "powerRangeMin": 0,
    "powerRangeMax": 350,
    "connectorTypes": "",
    "onlyAvailable": "false",
    "onlyAccessible": "false",
    "operatorIds": "",
    "updatedSince": "null",
}


def fetch() -> list[dict]:
    query = urllib.parse.urlencode(PARAMS)
    request = urllib.request.Request(
        f"{ENDPOINT}?{query}",
        headers={"User-Agent": "COMP5339-EVCharger-ass1/0.1"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Charge@Large returned a non-list response")
    return [record for record in payload if isinstance(record, dict)]


def ports(record: dict) -> list[dict]:
    result = []
    for charge_point in record.get("chargePoints") or []:
        result.extend(charge_point.get("ports") or [])
    return [port for port in result if isinstance(port, dict)]


def coordinates(record: dict) -> tuple[float, float] | None:
    coordinate = record.get("coordinate") or {}
    try:
        return float(coordinate["latitude"]), float(coordinate["longitude"])
    except (KeyError, TypeError, ValueError):
        return None


def load_nsw_geometry():
    boundary = gpd.read_file(f"zip://{BOUNDARY_FILE}")
    return boundary[boundary["STE_NAME26"].eq("New South Wales")].geometry.union_all()


def inside_nsw(record: dict, geometry) -> bool:
    point = coordinates(record)
    return point is not None and geometry.intersects(Point(point[1], point[0]))


def text(value) -> str:
    return "" if value is None else str(value).strip()


def flatten(record: dict) -> dict[str, object]:
    record_ports = ports(record)
    power_values = []
    connector_values = []
    status_values = []
    for port in record_ports:
        try:
            power_values.append(float(port["powerKilowatts"]))
        except (KeyError, TypeError, ValueError):
            pass
        connector_values.extend(text(value) for value in port.get("connectorTypes") or [] if text(value))
        if text(port.get("status")):
            status_values.append(text(port["status"]))
    lat_lon = coordinates(record) or (None, None)
    return {
        "chargelarge_id": text(record.get("id")),
        "name": text(record.get("name")),
        "address": text(record.get("address")),
        "latitude": lat_lon[0],
        "longitude": lat_lon[1],
        "power_range": text(record.get("powerRange")),
        "charge_point_count": len(record.get("chargePoints") or []),
        "port_count": len(record_ports),
        "connector_types": "|".join(sorted(set(connector_values))),
        "min_power_kw": min(power_values) if power_values else None,
        "max_power_kw": max(power_values) if power_values else None,
        "status_counts": json.dumps(dict(Counter(status_values)), ensure_ascii=False, sort_keys=True),
        "fast_dc_indicator": bool(
            any(value >= 40 for value in power_values)
            or {value.upper() for value in connector_values} & {"CCS2", "CCS1", "CHADEMO"}
        ),
    }


def distance_metres(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius = 6_371_000.0
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_phi = math.radians(lat_b - lat_a)
    d_lambda = math.radians(lon_b - lon_a)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, value)))


def matching_stats(nsw_records: list[dict]) -> dict[str, object]:
    with SOURCE_FILE.open(newline="", encoding="utf-8-sig") as handle:
        source = [row for row in csv.DictReader(handle) if text(row.get("Charger_Type")).upper() == "DC"]
    targets = []
    for row in source:
        try:
            targets.append((float(row["Latitude"]), float(row["Longitude"])))
        except (KeyError, TypeError, ValueError):
            pass
    candidates = [flatten(record) for record in nsw_records]
    result = {}
    for label, records in {
        "all_nsw_locations": candidates,
        "fast_dc_indicators": [record for record in candidates if record["fast_dc_indicator"]],
    }.items():
        distances = []
        for lat, lon in targets:
            if not records:
                continue
            distances.append(
                min(distance_metres(lat, lon, record["latitude"], record["longitude"]) for record in records)
            )
        result[label] = {
            "candidate_count": len(records),
            "nearest_match_counts": {
                f"within_{threshold}m": sum(distance <= threshold for distance in distances)
                for threshold in (25, 50, 100, 250, 500)
            },
            "target_dc_count": len(targets),
        }
    return result


def main() -> None:
    records = fetch()
    geometry = load_nsw_geometry()
    nsw_records = [record for record in records if inside_nsw(record, geometry)]
    flattened = [flatten(record) for record in nsw_records]

    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    RAW_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    with NSW_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flattened[0]))
        writer.writeheader()
        writer.writerows(flattened)

    summary = {
        "source": "Charge@Large public locations endpoint",
        "endpoint": ENDPOINT,
        "parameters": PARAMS,
        "raw_record_count": len(records),
        "unique_raw_ids": len({text(record.get("id")) for record in records}),
        "nsw_record_count": len(nsw_records),
        "nsw_fast_dc_indicator_count": sum(record["fast_dc_indicator"] for record in flattened),
        "nsw_address_nonempty": sum(bool(record["address"]) for record in flattened),
        "nsw_power_nonempty": sum(record["max_power_kw"] is not None for record in flattened),
        "nsw_connector_nonempty": sum(bool(record["connector_types"]) for record in flattened),
        "nsw_status_nonempty": sum(bool(record["status_counts"] not in ("", "{}")) for record in flattened),
        "matching": matching_stats(nsw_records),
        "raw_file": str(RAW_FILE.relative_to(ROOT)),
        "nsw_file": str(NSW_FILE.relative_to(ROOT)),
    }
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
