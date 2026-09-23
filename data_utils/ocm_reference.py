"""Existing OCM normalisation and legacy baseline, separated from Task 2."""
from __future__ import annotations

# Data file location
import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from shapely.geometry import Point

try:
    import geopandas as gpd
except ModuleNotFoundError:  # Optional for the Task 3 trial-only path.
    gpd = None
import numpy as np
import pandas as pd

from data_utils.column_cleaner import ColumnCleaner, DFDataType

# 0.1. File Locations
SRC_DATA_FILE_LOCATION = "src_data"
CLEAN_SRC_DATA_FILE_LOCATION = "clean_src_data"
AUG_DATA_FILE_LOCATION = "aug_data"
RESULT_DATA_FILE_LOCATION = "result_data"

# 0.2. APIs
# 0.2.1. NSW EV Charging Locations - NSW Transport Open Data
NSW_TRANSPORT_API_TOKEN = "comp5339-usyd"
NSW_EV_CHARGING_SRC_FILE_URL = "https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv"
NSW_EV_CHARGING_SRC_FILE_NAME = "nsw_ev_charging.csv"
NSW_EV_CHARGING_SRC_FILE = f"{SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}"
# - Outcome of Step 1: Data Cleaning and Integration
NSW_EV_CHARGING_CLEAN_SRC_FILE = f"{CLEAN_SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}"
# - Outcome of Step 2: Data Augmentation
NSW_EV_CHARGING_AUG_FILE = f"{AUG_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}"

# 0.2.2. ABS ASGS Statistical Area Level 4
AUS_ASGS_LV4_URL = "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files/SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_ZIP_FILE_NAME = "SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_FILE = f"{SRC_DATA_FILE_LOCATION}/{AUS_ASGS_LV4_ZIP_FILE_NAME}"

# 0.2.3. Open Charge Map (OCM)
# The key is read from the local shell and must never be committed.
OCM_ENDPOINT = os.getenv(
    "OCM_ENDPOINT", "https://api.openchargemap.io/v3/poi/"
)
OCM_API_KEY = os.getenv("OCM_API_KEY", "")
OCM_USER_AGENT = os.getenv(
    "OCM_USER_AGENT", "COMP5339-EVCharger-ass1/0.1"
)
OCM_REFRESH_SNAPSHOT = os.getenv("OCM_REFRESH_SNAPSHOT", "0") == "1"
OCM_SNAPSHOT_FILE = Path(
    os.getenv(
        "OCM_SNAPSHOT_FILE",
        f"{RESULT_DATA_FILE_LOCATION}/ocm_ev_charging_snapshot.json",
    )
)
OCM_SNAPSHOT_METADATA_FILE = Path(
    os.getenv(
        "OCM_SNAPSHOT_METADATA_FILE",
        f"{RESULT_DATA_FILE_LOCATION}/ocm_ev_charging_snapshot_metadata.json",
    )
)
TASK3_FINAL_AUDIT_FILE = Path(
    os.getenv(
        "TASK3_FINAL_AUDIT_FILE",
        f"{RESULT_DATA_FILE_LOCATION}/task3_final_multisource_output/task3_multisource_final_audit.csv",
    )
)

# 0.2.4. OpenStreetMap API
OSM_API_PROD = "https://api.openstreetmap.org/api/"
OSM_API_SANDBOX = "https://master.apis.dev.openstreetmap.org/"

# 0.2.5. Legacy Peclet snapshot retained only for comparison with the first
# trial. The current Task 3 source is OCM when OCM_API_KEY is configured.
PECLET_REFERENCE_FILE = (
    Path("/Users/caodengjie/Desktop/26S2/5339/ass1")
    / "drive-download-20260915T070916Z-1-001"
    / "ev-charging-stations.json"
)
TASK3_COORDINATE_PRECISION = 6
TASK3_MAX_NEAR_DISTANCE_METRES = 5.0
TASK3_MIN_NEAREST_GAP_METRES = 20.0
# Task 3 keeps the existing snapshot/matching interfaces, but retrieves OCM
# records with one coordinate query per DC source row.  These are deliberately
# internal implementation constants rather than new public configuration.
TASK3_OCM_SEARCH_RADIUS_KM = 5
TASK3_OCM_SEARCH_MAXRESULTS = 100
TASK3_OCM_REQUEST_DELAY_SECONDS = 0.1
# Full NSW retrieval is the address-stage replacement: OCM's AddressInfo is
# matched locally after the complete regional snapshot is available.
TASK3_OCM_NSW_BOUNDING_BOX = "(-37.6,140.8),(-27.9,154.3)"

TASK3_STREET_TYPE_ALIASES = {
    "alley": "aly", "aly": "aly", "avenue": "ave", "ave": "ave",
    "boulevard": "bvd", "bvd": "bvd", "circuit": "cct", "cct": "cct",
    "close": "cl", "cl": "cl", "crescent": "cres", "cres": "cres",
    "drive": "dr", "dr": "dr", "esplanade": "esp", "esp": "esp",
    "highway": "hwy", "hwy": "hwy", "lane": "ln", "ln": "ln",
    "parade": "pde", "pde": "pde", "place": "pl", "pl": "pl",
    "road": "rd", "rd": "rd", "street": "st", "st": "st",
    "terrace": "tce", "tce": "tce", "way": "way", "wy": "way",
}
TASK3_NUMBER_RE = re.compile(r"^\d+[a-z]?(?:[-/]\d+[a-z]?)?$")

def _task3_text(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _task3_coordinate_key(latitude, longitude):
    try:
        return (
            round(float(latitude), TASK3_COORDINATE_PRECISION),
            round(float(longitude), TASK3_COORDINATE_PRECISION),
        )
    except (TypeError, ValueError):
        return None


def _task3_distance_metres(latitude_a, longitude_a, latitude_b, longitude_b):
    """Approximate distance for the small-radius matching rule."""
    lat_a, lon_a, lat_b, lon_b = map(
        float, (latitude_a, longitude_a, latitude_b, longitude_b)
    )
    x = math.radians(lon_b - lon_a) * math.cos(math.radians((lat_a + lat_b) / 2))
    y = math.radians(lat_b - lat_a)
    return 6_371_000 * math.sqrt(x * x + y * y)


def _task3_postcodes(*values) -> set[str]:
    postcodes = set()
    for value in values:
        postcodes.update(re.findall(r"(?<!\d)(\d{4})(?!\d)", _task3_text(value)))
    return postcodes


def _task3_house_number(value: str) -> str:
    value = value.strip(".,")
    if "/" in value:
        value = value.rsplit("/", 1)[-1]

    def clean_part(part: str) -> str:
        match = re.fullmatch(r"(\d+)([a-z]?)", part)
        return f"{int(match.group(1))}{match.group(2)}" if match else part

    if "-" in value:
        return "-".join(clean_part(part) for part in value.split("-"))
    return clean_part(value)


def _task3_address_signatures(value) -> set[str]:
    """Extract comparable house-number/street signatures from messy addresses."""
    raw = unicodedata.normalize("NFKC", _task3_text(value)).lower()
    raw = raw.replace("–", "-").replace("—", "-")
    raw = re.sub(r"\baustralia\b", " ", raw)
    raw = re.sub(r"[^a-z0-9/,-]+", " ", raw)
    signatures = set()

    for segment in re.split(r"[,;\n]+", raw):
        tokens = segment.split()
        for type_index, street_type in enumerate(tokens):
            if street_type not in TASK3_STREET_TYPE_ALIASES:
                continue

            number_index = None
            for index in range(type_index - 1, max(-1, type_index - 9), -1):
                if TASK3_NUMBER_RE.fullmatch(tokens[index].strip(".,")):
                    number_index = index
                    break
            if number_index is None:
                continue

            house_number = _task3_house_number(tokens[number_index])
            if (
                number_index >= 2
                and tokens[number_index - 1] == "-"
                and re.fullmatch(r"\d+[a-z]?", tokens[number_index - 2])
            ):
                house_number = _task3_house_number(
                    f"{tokens[number_index - 2]}-{tokens[number_index]}"
                )

            street_name = [
                token.strip(".,")
                for token in tokens[number_index + 1 : type_index]
                if token != "-"
            ]
            if street_name:
                street_name = [
                    TASK3_STREET_TYPE_ALIASES.get(token, token)
                    for token in street_name
                ]
                signatures.add(
                    f"{house_number}|{' '.join(street_name + [TASK3_STREET_TYPE_ALIASES[street_type]])}"
                )
    return signatures


def _task3_address_keys(address, *postcode_sources) -> set[str]:
    return {
        f"{postcode}|{signature}"
        for postcode in _task3_postcodes(*postcode_sources, address)
        for signature in _task3_address_signatures(address)
    }


def _task3_plug_types(record: dict) -> str:
    explicit_types = _task3_text(record.get("plug_types"))
    if explicit_types:
        return explicit_types

    labels = []
    for field, label in (("tesla", "Tesla"), ("type_2", "Type 2"), ("j_1772", "J-1772")):
        try:
            if record.get(field) is not None and float(record[field]) > 0:
                labels.append(label)
        except (TypeError, ValueError):
            continue
    return "; ".join(labels)


# TODO: 2. Data Augmentation: Enrich NSW EV Charging Locations details


def _task3_ocm_connection_title(connection: dict) -> str:
    connection_type = connection.get("ConnectionType") or {}
    if isinstance(connection_type, dict):
        return _task3_text(connection_type.get("Title"))
    return _task3_text(connection_type)


def _task3_ocm_plug_types(connections: list[dict]) -> str:
    labels = []
    for connection in connections:
        title = _task3_ocm_connection_title(connection)
        if title and title not in labels:
            labels.append(title)
    return "; ".join(labels)


def _task3_ocm_capacity(connections: list[dict]) -> str:
    capacities = []
    for connection in connections:
        power_kw = connection.get("PowerKW")
        if power_kw in (None, ""):
            continue
        value = _task3_text(power_kw)
        if value not in capacities:
            capacities.append(value)
    return "; ".join(f"{value} kW" for value in capacities)


def _task3_ocm_number_of_plugs(poi: dict, connections: list[dict]):
    number_of_points = poi.get("NumberOfPoints")
    try:
        number_of_points = float(number_of_points)
        if number_of_points > 0:
            return int(number_of_points) if number_of_points.is_integer() else number_of_points
    except (AttributeError, TypeError, ValueError):
        pass

    quantities = []
    for connection in connections:
        quantity = connection.get("Quantity")
        try:
            quantity = float(quantity)
            if quantity > 0:
                quantities.append(quantity)
        except (TypeError, ValueError):
            continue
    if not quantities:
        return None
    total = sum(quantities)
    return int(total) if total.is_integer() else total


def _task3_normalise_ocm_record(poi: dict) -> dict:
    address_info = poi.get("AddressInfo") or {}
    connections = poi.get("Connections") or []
    if not isinstance(connections, list):
        connections = []

    address_parts = [
        address_info.get("AddressLine1"),
        address_info.get("AddressLine2"),
        address_info.get("Town"),
        address_info.get("StateOrProvince"),
        address_info.get("Postcode"),
    ]
    station_address = ", ".join(
        _task3_text(value) for value in address_parts if _task3_text(value)
    )

    operator_info = poi.get("OperatorInfo") or {}
    if isinstance(operator_info, dict):
        operator = operator_info.get("Title") or operator_info.get("Name")
    else:
        operator = operator_info

    provider_info = poi.get("DataProvider") or {}
    if isinstance(provider_info, dict):
        provider = provider_info.get("Title") or provider_info.get("Name")
    else:
        provider = provider_info

    status_info = poi.get("StatusType") or {}
    if isinstance(status_info, dict):
        status = status_info.get("Title") or ""
        is_operational = status_info.get("IsOperational")
    else:
        status = _task3_text(status_info)
        is_operational = None

    general_comments = _task3_text(poi.get("GeneralComments"))
    if re.search(r"decommission|decomission|closed|removed", general_comments, re.I):
        is_operational = False

    return {
        "ev_station_id": poi.get("ID", ""),
        "station_name": address_info.get("Title", ""),
        "station_address": station_address,
        "postcode": address_info.get("Postcode", ""),
        "operator": operator or "",
        "data_provider": provider or "",
        "number_of_plugs": _task3_ocm_number_of_plugs(poi, connections),
        "charger_capacities": _task3_ocm_capacity(connections),
        "plug_types": _task3_ocm_plug_types(connections),
        "status": status,
        "is_operational": is_operational,
        "usage_cost": _task3_text(poi.get("UsageCost")),
        "last_verified": _task3_text(poi.get("DateLastVerified")),
        "general_comments": general_comments,
        "access_comments": _task3_text(address_info.get("AccessComments")),
        # OCM does not provide a consistently populated opening-hours field.
        "opening_hours": "",
        "latitude": address_info.get("Latitude"),
        "longitude": address_info.get("Longitude"),
    }


def _task3_ocm_bounding_box(fact_df: pd.DataFrame) -> str:
    latitudes = pd.to_numeric(fact_df.get("Latitude"), errors="coerce").dropna()
    longitudes = pd.to_numeric(fact_df.get("Longitude"), errors="coerce").dropna()
    if latitudes.empty or longitudes.empty:
        raise ValueError("The source data does not contain usable coordinates.")

    # Add a small margin so a station on the edge of the source data is not
    # lost due to rounding. OCM expects (latitude,longitude) pairs.
    latitude_margin = 0.25
    longitude_margin = 0.25
    south = max(-90.0, float(latitudes.min()) - latitude_margin)
    west = max(-180.0, float(longitudes.min()) - longitude_margin)
    north = min(90.0, float(latitudes.max()) + latitude_margin)
    east = min(180.0, float(longitudes.max()) + longitude_margin)
    return f"({south:.6f},{west:.6f}),({north:.6f},{east:.6f})"


def _task3_fetch_ocm_snapshot(fact_df: pd.DataFrame) -> list[dict]:
    """Fetch and cache the OCM reference data used by the existing matcher.

    The public interface is intentionally unchanged for compatibility with the
    teammate's ``_task3_load_ocm_reference_records`` and augmentation cleaners.
    Task 3 is about DC chargers. The complete NSW OCM snapshot is retrieved
    first, then per-record coordinate queries are merged as a supplemental
    pass. Address matching is performed locally against OCM AddressInfo; no
    separate address service is required.
    """
    if not OCM_API_KEY:
        raise RuntimeError(
            "OCM_API_KEY is not set. Run `export OCM_API_KEY='your-key'` "
            "in the same shell before running Task 3."
        )

    if "Charger_Type" in fact_df.columns:
        charger_type = fact_df["Charger_Type"].astype("string").str.strip().str.upper()
        target_df = fact_df.loc[charger_type.eq("DC")]
    else:
        # Keep the helper usable with a small isolated test dataframe while the
        # normal assignment path always supplies Charger_Type.
        target_df = fact_df

    if target_df.empty:
        raise RuntimeError("Task 3 did not find any DC source rows to query.")

    headers = {
        "X-API-Key": OCM_API_KEY,
        "User-Agent": OCM_USER_AGENT,
    }

    merged_records = {}
    full_nsw_query_count = 0
    coordinate_query_count = 0
    skipped_missing_coordinate_count = 0
    full_nsw_result_count = 0
    coordinate_result_counts = []

    def record_key(poi: dict) -> str:
        poi_id = poi.get("ID")
        if poi_id not in (None, ""):
            return f"id:{poi_id}"
        address_info = poi.get("AddressInfo") or {}
        return "fallback:" + "|".join(
            _task3_text(value)
            for value in (
                address_info.get("Title"),
                address_info.get("AddressLine1"),
                address_info.get("Postcode"),
                address_info.get("Latitude"),
                address_info.get("Longitude"),
            )
        )

    def request_json(url: str, request_headers: dict, context: str):
        request = urllib.request.Request(
            url,
            headers=request_headers,
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"Request rejected for {context} with HTTP {error.code}."
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"Request failed for {context}: {error}") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Request returned invalid JSON for {context}.") from error

    def request_ocm_pois(latitude, longitude, context: str) -> list[dict]:
        params = {
            "output": "json",
            "countrycode": "AU",
            "latitude": f"{float(latitude):.6f}",
            "longitude": f"{float(longitude):.6f}",
            "distance": TASK3_OCM_SEARCH_RADIUS_KM,
            "distanceunit": "KM",
            "maxresults": TASK3_OCM_SEARCH_MAXRESULTS,
            "compact": "false",
            "verbose": "false",
        }
        query_string = urllib.parse.urlencode(params)
        separator = "&" if "?" in OCM_ENDPOINT else "?"
        payload = request_json(
            f"{OCM_ENDPOINT}{separator}{query_string}",
            headers,
            context,
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"Open Charge Map returned an unexpected JSON structure for {context}.")
        return payload

    def request_ocm_bounding_box(context: str) -> list[dict]:
        params = {
            "output": "json",
            "countrycode": "AU",
            "boundingbox": TASK3_OCM_NSW_BOUNDING_BOX,
            "maxresults": 100000,
            "compact": "false",
            "verbose": "false",
        }
        query_string = urllib.parse.urlencode(params)
        separator = "&" if "?" in OCM_ENDPOINT else "?"
        payload = request_json(
            f"{OCM_ENDPOINT}{separator}{query_string}",
            headers,
            context,
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"Open Charge Map returned an unexpected JSON structure for {context}.")
        return payload

    def add_pois(query_payload: list[dict]):
        for poi in query_payload:
            if isinstance(poi, dict):
                merged_records[record_key(poi)] = poi

    # Phase 1: retrieve the complete NSW OCM region. This makes the address
    # matching stage local and prevents a source-coordinate error from hiding a
    # station that exists elsewhere in the regional OCM snapshot.
    full_nsw_payload = request_ocm_bounding_box("full NSW bounding-box query")
    full_nsw_query_count = 1
    full_nsw_result_count = len(full_nsw_payload)
    add_pois(full_nsw_payload)

    # Supplemental coordinate retrieval for every DC source row. This preserves
    # the teammate-compatible per-record path and can recover POIs returned by
    # a radius query but not by the regional bounding box.
    for source_index, source_row in target_df.iterrows():
        latitude = pd.to_numeric(source_row.get("Latitude"), errors="coerce")
        longitude = pd.to_numeric(source_row.get("Longitude"), errors="coerce")
        if pd.isna(latitude) or pd.isna(longitude):
            skipped_missing_coordinate_count += 1
            continue

        query_payload = request_ocm_pois(
            latitude,
            longitude,
            f"coordinate source row {source_index}",
        )
        coordinate_query_count += 1
        coordinate_result_counts.append(len(query_payload))
        add_pois(query_payload)

        if TASK3_OCM_REQUEST_DELAY_SECONDS > 0:
            time.sleep(TASK3_OCM_REQUEST_DELAY_SECONDS)

    payload = list(merged_records.values())

    OCM_SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OCM_SNAPSHOT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    metadata = {
        "source": "Open Charge Map API",
        "endpoint": OCM_ENDPOINT,
        "query_mode": "full_nsw_bbox_plus_per_record_coordinate",
        "target_filter": "Charger_Type == DC",
        "target_record_count": int(len(target_df)),
        "full_nsw_bounding_box": TASK3_OCM_NSW_BOUNDING_BOX,
        "full_nsw_query_count": full_nsw_query_count,
        "full_nsw_result_count": full_nsw_result_count,
        "coordinate_query_count": coordinate_query_count,
        "api_query_count": full_nsw_query_count + coordinate_query_count,
        "skipped_missing_coordinate_count": skipped_missing_coordinate_count,
        "unique_record_count": len(payload),
        "search_radius_km": TASK3_OCM_SEARCH_RADIUS_KM,
        "maxresults_per_query": TASK3_OCM_SEARCH_MAXRESULTS,
        "coordinate_result_count_min": min(coordinate_result_counts)
        if coordinate_result_counts else 0,
        "coordinate_result_count_max": max(coordinate_result_counts)
        if coordinate_result_counts else 0,
        "coordinate_result_count_total": sum(coordinate_result_counts),
        "query_result_count_total": full_nsw_result_count + sum(coordinate_result_counts),
        "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "record_count": len(payload),
        "snapshot_file": str(OCM_SNAPSHOT_FILE),
    }
    with OCM_SNAPSHOT_METADATA_FILE.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    return payload


def _task3_load_ocm_reference_records(fact_df: pd.DataFrame) -> list[dict]:
    # Do not silently reuse the old bounding-box snapshot.  It was produced by
    # the earlier trial and has a different retrieval scope; the existing cache
    # path is retained, but it is refreshed once when its metadata is old.
    snapshot_is_per_record = False
    if OCM_SNAPSHOT_METADATA_FILE.exists():
        try:
            with OCM_SNAPSHOT_METADATA_FILE.open("r", encoding="utf-8") as handle:
                snapshot_metadata = json.load(handle)
            snapshot_is_per_record = snapshot_metadata.get("query_mode") in {
                "per_record_coordinate",
                "per_record_coordinate_plus_address_geocode",
                "full_nsw_bbox_plus_per_record_coordinate",
            }
        except (OSError, json.JSONDecodeError, AttributeError):
            snapshot_is_per_record = False

    if OCM_SNAPSHOT_FILE.exists() and not OCM_REFRESH_SNAPSHOT and snapshot_is_per_record:
        with OCM_SNAPSHOT_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = _task3_fetch_ocm_snapshot(fact_df)

    if not isinstance(payload, list):
        raise RuntimeError("The OCM snapshot must contain a JSON list.")
    return [_task3_normalise_ocm_record(poi) for poi in payload if isinstance(poi, dict)]


def get_ocm_details(fact_df: pd.DataFrame) -> pd.DataFrame:
    """Match source locations to an OCM snapshot using the three trial rules."""
    reference_records = _task3_load_ocm_reference_records(fact_df)

    reference_by_coordinate = {}
    reference_by_address = {}
    reference_entries = []
    for reference_row, record in enumerate(reference_records, start=2):
        key = _task3_coordinate_key(record.get("latitude"), record.get("longitude"))
        address_keys = _task3_address_keys(
            record.get("station_address"), record.get("postcode")
        )
        entry = {
            "reference_row": reference_row,
            "record": record,
            "coordinate_key": key,
            "address_keys": address_keys,
        }
        reference_entries.append(entry)
        if key is not None:
            reference_by_coordinate.setdefault(key, []).append(entry)
        for address_key in address_keys:
            reference_by_address.setdefault(address_key, []).append(entry)

    result_rows = []
    for _, fact_row in fact_df.iterrows():
        coordinate = _task3_coordinate_key(
            fact_row.get("Latitude"), fact_row.get("Longitude")
        )
        address_keys = _task3_address_keys(
            fact_row.get("Station_address"), fact_row.get("PCODE")
        )

        distances = []
        if coordinate is not None:
            try:
                for entry in reference_entries:
                    record = entry["record"]
                    distance = _task3_distance_metres(
                        fact_row.get("Latitude"),
                        fact_row.get("Longitude"),
                        record.get("latitude"),
                        record.get("longitude"),
                    )
                    distances.append((distance, entry))
                distances.sort(key=lambda item: item[0])
            except (TypeError, ValueError):
                distances = []

        nearest_distance = distances[0][0] if distances else None
        second_distance = distances[1][0] if len(distances) > 1 else None
        nearest_gap = (
            second_distance - nearest_distance
            if nearest_distance is not None and second_distance is not None
            else None
        )

        coordinate_candidates = (
            reference_by_coordinate.get(coordinate, []) if coordinate else []
        )
        address_candidates = sorted(
            {
                id(entry): entry
                for address_key in address_keys
                for entry in reference_by_address.get(address_key, [])
            }.values(),
            key=lambda entry: entry["reference_row"],
        )

        selected_entry = None
        if len(coordinate_candidates) == 1:
            selected_entry = coordinate_candidates[0]
            status, method, confidence, manual_review = (
                "accepted", "coordinate_exact", 1.0, False
            )
            match_distance = 0.0
        elif len(coordinate_candidates) > 1:
            selected_entry = min(
                coordinate_candidates,
                key=lambda entry: next(
                    (distance for distance, candidate in distances if candidate is entry),
                    float("inf"),
                ),
            )
            status, method, confidence, manual_review = (
                "review", "ambiguous_coordinate", 0.5, True
            )
            match_distance = next(
                (
                    distance
                    for distance, candidate in distances
                    if candidate is selected_entry
                ),
                None,
            )
        elif len(address_candidates) == 1:
            selected_entry = address_candidates[0]
            status, method, confidence, manual_review = (
                "accepted", "address_exact_unique", 0.97, False
            )
            match_distance = next(
                (
                    distance
                    for distance, candidate in distances
                    if candidate is selected_entry
                ),
                None,
            )
        elif len(address_candidates) > 1:
            selected_entry = min(
                address_candidates,
                key=lambda entry: next(
                    (distance for distance, candidate in distances if candidate is entry),
                    float("inf"),
                ),
            )
            status, method, confidence, manual_review = (
                "review", "ambiguous_exact_address", 0.5, True
            )
            match_distance = next(
                (
                    distance
                    for distance, candidate in distances
                    if candidate is selected_entry
                ),
                None,
            )
        elif (
            nearest_distance is not None
            and nearest_distance <= TASK3_MAX_NEAR_DISTANCE_METRES
            and nearest_gap is not None
            and nearest_gap >= TASK3_MIN_NEAREST_GAP_METRES
        ):
            selected_entry = distances[0][1]
            status, method, confidence, manual_review = (
                "accepted", "coordinate_near_clear", 0.90, False
            )
            match_distance = nearest_distance
        elif distances:
            selected_entry = distances[0][1]
            status, method, confidence, manual_review = (
                "review", "coordinate_candidate", 0.5, True
            )
            match_distance = nearest_distance
        else:
            status, method, confidence, manual_review = (
                "unmatched", "none", 0.0, True
            )
            match_distance = None

        if selected_entry is None:
            reference_row, record = None, {}
        else:
            reference_row = selected_entry["reference_row"]
            record = selected_entry["record"]

        if status == "accepted":
            review_reason = ""
        elif method == "coordinate_near_clear":
            review_reason = ""
        elif nearest_distance is not None and nearest_gap is not None:
            review_reason = (
                f"nearest={nearest_distance:.3f}m; gap={nearest_gap:.3f}m; "
                "manual confirmation required"
            )
        else:
            review_reason = "no deterministic match; manual confirmation required"

        result_rows.append(
            {
                "augmentation_match_status": status,
                "augmentation_match_method": method,
                "augmentation_match_confidence": confidence,
                "augmentation_manual_review": manual_review,
                "augmentation_reference_row": reference_row,
                "augmentation_match_distance_m": match_distance,
                "augmentation_nearest_distance_m": nearest_distance,
                "augmentation_nearest_gap_m": nearest_gap,
                "external_source": "Open Charge Map API snapshot",
                "external_data_provider": record.get("data_provider", ""),
                "external_station_id": record.get("ev_station_id", ""),
                "external_station_name": record.get("station_name", ""),
                "external_station_address": record.get("station_address", ""),
                "external_operator": record.get("operator", ""),
                "external_plug_types": _task3_plug_types(record),
                "external_number_of_plugs": record.get("number_of_plugs"),
                "external_charger_capacity": record.get("charger_capacities", ""),
                "external_status": record.get("status", ""),
                "external_operational_status": (
                    "operational" if record.get("is_operational") is True
                    else "not_operational" if record.get("is_operational") is False
                    else "unknown"
                ),
                "external_usage_cost": record.get("usage_cost", ""),
                "external_last_verified": record.get("last_verified", ""),
                "external_comments": record.get("general_comments", ""),
                "external_opening_hours": record.get("opening_hours", ""),
                "external_latitude": record.get("latitude"),
                "external_longitude": record.get("longitude"),
                "augmentation_review_reason": review_reason,
            }
        )

    return pd.DataFrame(result_rows, index=fact_df.index)


# TODO: 2.2. Column (feature) creation function for new features

# TODO: 2.3. ColumnCleaners for NSW EV data augmentation:
def GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df) -> list[ColumnCleaner]:
    """Return Task 3 cleaners backed by the cached OCM matching result."""
    ocm_df = get_ocm_details(aug_df)

    def create_column(column_name):
        # The augmentation result is indexed from the same fact dataframe.
        # MANUAL TODO: preserve this alignment when the final matcher is added.
        return lambda current_df: ocm_df.reindex(current_df.index)[column_name]

    return [
        # Keep external fields separate from the original NSW source fields.
        ColumnCleaner(
            "augmentation_match_status", DFDataType.STR,
            default_value="unmatched",
            column_create_function=create_column("augmentation_match_status"),
        ),
        ColumnCleaner(
            "augmentation_match_method", DFDataType.STR,
            default_value="none",
            column_create_function=create_column("augmentation_match_method"),
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
            "augmentation_reference_row", DFDataType.FLOAT,
            column_create_function=create_column("augmentation_reference_row"),
        ),
        ColumnCleaner(
            "augmentation_match_distance_m", DFDataType.FLOAT,
            column_create_function=create_column("augmentation_match_distance_m"),
        ),
        ColumnCleaner(
            "augmentation_nearest_distance_m", DFDataType.FLOAT,
            column_create_function=create_column("augmentation_nearest_distance_m"),
        ),
        ColumnCleaner(
            "augmentation_nearest_gap_m", DFDataType.FLOAT,
            column_create_function=create_column("augmentation_nearest_gap_m"),
        ),
        ColumnCleaner(
            "external_source", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_source"),
        ),
        ColumnCleaner(
            "external_data_provider", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_data_provider"),
        ),
        ColumnCleaner(
            "external_station_id", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_station_id"),
        ),
        ColumnCleaner(
            "external_station_name", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_station_name"),
        ),
        ColumnCleaner(
            "external_station_address", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_station_address"),
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
            "external_number_of_plugs", DFDataType.FLOAT,
            column_create_function=create_column("external_number_of_plugs"),
        ),
        ColumnCleaner(
            "external_charger_capacity", DFDataType.STR,
            default_value="",
            column_create_function=create_column("external_charger_capacity"),
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
            "augmentation_review_reason", DFDataType.STR,
            default_value="",
            column_create_function=create_column("augmentation_review_reason"),
        ),
    ]
def load_nsw_ocm_records(snapshot_file: Path, boundary_file: Path) -> tuple[list[dict], int]:
    payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
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

    boundary = gpd.read_file(f"zip://{boundary_file}")
    nsw_geometry = boundary[boundary["STE_NAME26"].eq("New South Wales")].geometry.union_all()
    points_gdf = gpd.GeoDataFrame(valid_records, geometry=points, crs="EPSG:4326").to_crs(
        boundary.crs
    )
    inside = points_gdf.geometry.intersects(nsw_geometry)
    return points_gdf.loc[inside].drop(columns=["geometry"]).to_dict("records"), len(normalised)
