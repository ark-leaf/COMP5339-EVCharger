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

# 1. Data Cleaning and Integration
# 1.1. Cleaning and Integration: NSW EV Charging Locations + AUS ASGS Level 4

# 1.1.1. Define the post processors for address columns
def address_processor(addr):
    r"""
    Normalize and standardize Australian address format.

    Args:
        addr: Address string or pandas value

    Returns:
        Normalized address string in format: "Street, Suburb State Postcode"
    """
    if pd.isna(addr):
        return addr

    # Step 1: Clean string and normalize whitespace
    addr = str(addr).replace('\n', ', ').strip()
    addr = re.sub(r'\s+', ' ', addr)

    # Step 2: Remove "Australia" in various formats (verified regex patterns)
    addr = re.sub(r',\s*Australia\s*$', '', addr, flags=re.IGNORECASE)  # ", Australia" at end
    addr = re.sub(r'\s+Australia\s*,', ',', addr, flags=re.IGNORECASE)  # " Australia," pattern
    addr = re.sub(r'\s+Australia\b', '', addr, flags=re.IGNORECASE)     # " Australia" anywhere
    addr = re.sub(r'\s+', ' ', addr).strip()  # Clean up spaces after removal

    # Step 3: Extract postcode (last 4-digit number at end)
    postcode_match = re.search(r'\b(\d{4})\s*$', addr)
    if postcode_match:
        postcode = postcode_match.group(1)
    else:
        # Fallback: look for 4 digits after state name
        postcode_match = re.search(r'\b(NSW|VIC|ACT|QLD|SA|WA|NT|TAS)\s+(\d{4})\b', addr, flags=re.IGNORECASE)
        postcode = postcode_match.group(2) if postcode_match else ''

    # Step 4: Extract state (use LAST occurrence to avoid street name conflicts - VERIFIED)
    state_matches = list(re.finditer(r'\b(NSW|VIC|ACT|QLD|SA|WA|NT|TAS)\b', addr, flags=re.IGNORECASE))
    state = state_matches[-1].group(1).upper() if state_matches else 'NSW'

    # Step 5: Remove state and postcode to isolate street and suburb
    clean_addr = addr
    if postcode:
        # Use re.escape() to safely handle any special regex characters in postcode
        clean_addr = re.sub(r'\b' + re.escape(postcode) + r'\b', '', clean_addr)
    if state:
        # Use re.escape() for safe regex construction with state
        clean_addr = re.sub(r'\b' + re.escape(state) + r'\b', '', clean_addr, flags=re.IGNORECASE)

    parts = [p.strip() for p in clean_addr.split(',') if p.strip()]

    # Step 6: Standardize abbreviations (VERIFIED regex patterns)
    abbreviations = {
        r'\bSt\b': 'Street',
        r'\bRd\b': 'Road',
        r'\bSq\b': 'Square',
        r'\bCt\b': 'Court',
        r'\bLn\b': 'Lane',
        r'\bHwy\b': 'Highway',
        r'\bDr\b': 'Drive',
        r'\bAve\b': 'Avenue',
        r'\bPde\b': 'Parade',
        r'\bPl\b': 'Place',
        r'\bCres\b': 'Crescent',
        r'\bBlvd\b': 'Boulevard',
        r'\bCct\b': 'Circuit',
        r'\bCl\b': 'Close',
        r'\bTer\b': 'Terrace',
        r'\bVic\b': 'Victoria',
    }

    formatted_parts = []
    for part in parts:
        # Apply all abbreviation replacements
        for pattern, replacement in abbreviations.items():
            part = re.sub(pattern, replacement, part, flags=re.IGNORECASE)

        # Title case and uppercase number suffixes (e.g., 1A, 2B)
        part = part.title()
        part = re.sub(r'\b([0-9]+[a-z])\b', lambda x: x.group(0).upper(), part, flags=re.IGNORECASE)
        formatted_parts.append(part)

    # Step 7: Separate street and suburb
    street, suburb = "", ""
    if len(formatted_parts) == 1:
        # Single part: if it has numbers, it's street; otherwise suburb
        street = formatted_parts[0] if re.search(r'\d', formatted_parts[0]) else ""
        suburb = formatted_parts[0] if not street else ""
    elif len(formatted_parts) == 2:
        street, suburb = formatted_parts[0], formatted_parts[1]
    elif len(formatted_parts) > 2:
        # Multiple parts: last is suburb, rest is street
        suburb = formatted_parts[-1]
        street = ', '.join(formatted_parts[:-1])

    # Step 8: Reconstruct final address with proper formatting
    if street and suburb:
        result = f"{street}, {suburb} {state} {postcode}"
    elif street:
        result = f"{street} {state} {postcode}"
    elif suburb:
        result = f"{suburb} {state} {postcode}"
    else:
        result = f"{state} {postcode}"

    # Final cleanup: remove any trailing commas or spaces
    return re.sub(r',\s*$', '', result.strip())

# 1.1.2. Define feature creation functions
# Universal processor
def col_processor(fn):
    return lambda df: df.iloc[:, 0].apply(fn)

def charger_rating_processor(rating):
    if pd.isna(rating):
        return rating
    rating = str(rating).strip()
    # Some ratings are missing their unit (e.g. "22", "50", "7") - append it.
    if re.fullmatch(r'\d+(\.\d+)?', rating):
        return f"{rating} kW"
    return rating


def pcode_processor(pcode):
    if pd.isna(pcode):
        return pcode
    # A few rows store "NSW 2500" instead of the bare postcode - extract the digits.
    match = re.search(r'\d{4}', str(pcode))
    return match.group(0) if match else pcode


def pcode_df_processor(df: pd.DataFrame):
    """Repair PCODE from the cleaned address while retaining the original value.

    Task 1/2 can use the repaired PCODE for downstream geographic enrichment.
    Task 3 still needs the pre-repair value to detect source-data conflicts, so
    both the original identifier and an explicit repair flag are preserved.
    """
    original = df["PCODE"].map(_task3_text)
    df["PCODE_ORIGINAL"] = original
    df["PCODE_REPAIRED_FROM_ADDRESS"] = False
    address_postcode = df["Station_address"].map(
        lambda value: (
            re.search(r"(?<!\d)(\d{4})\s*$", _task3_text(value)).group(1)
            if re.search(r"(?<!\d)(\d{4})\s*$", _task3_text(value))
            else ""
        )
    )
    needs_repair = address_postcode.ne("") & address_postcode.ne(original)
    df.loc[needs_repair, "PCODE"] = address_postcode[needs_repair]
    df.loc[needs_repair, "PCODE_REPAIRED_FROM_ADDRESS"] = True
    return df


def _charger_rating_count(row: pd.Series, multiplier: str) -> int:
    if multiplier:
        return int(multiplier)
    number = pd.to_numeric(row.get("Number_of_plugs"), errors="coerce")
    if pd.isna(number) or number <= 0 or float(number) != int(number):
        return 0
    return int(number)


def _parse_charger_rating(row: pd.Series) -> pd.Series:
    """Convert ratings such as ``2x350kW`` into count-by-power columns."""
    rating = _task3_text(row.get("Charger_rating"))
    pattern = r"(?:(\d+)\s*[xX]\s*)?(\d+(?:\.\d+)?)\s*[kK][wW]"
    counts: dict[str, int] = {}
    for multiplier, power in re.findall(pattern, rating):
        power_label = f"{float(power):g}"
        column = f"Charger_rating.{power_label}kW"
        counts[column] = counts.get(column, 0) + _charger_rating_count(row, multiplier)
    return pd.Series(counts, dtype="int64")


def split_charger_rating_df_processor(df: pd.DataFrame):
    """Add count-by-power columns without removing the original rating field."""
    parsed = df.apply(_parse_charger_rating, axis=1)
    if parsed.empty or len(parsed.columns) == 0:
        return df
    parsed = parsed.fillna(0).astype("int64")
    for column in parsed.columns:
        df[column] = parsed[column].reindex(df.index).fillna(0).astype("int64")
    return df

# 1.1.2. ASGS LV4 Integration Function
def get_sa4_info(src_df: pd.DataFrame, sa4_gdf: gpd.GeoDataFrame):
    """
    Get SA4 features from the ABS SA4 GeoDataFrame.
    :param src_df: A pd.DataFrame contains {Longitude} and {Latitude} columns
    :param sa4_gdf: ABS SA4 GeoDataFrame
    :return: A GeoDataFrame contains two more columns (features): {SA4_NAME26}, {SA4_CODE26}
    """
    crd_df = src_df[['Longitude', 'Latitude']]
    gdf_points = gpd.GeoDataFrame(
        crd_df,
        geometry=gpd.points_from_xy(crd_df['Longitude'], crd_df['Latitude']),
        crs='EPSG:4326', )
    gdf_points = gdf_points.to_crs(sa4_gdf.crs)
    return gpd.sjoin(gdf_points, sa4_gdf, how='left', predicate='within')

# 1.1.3. Define Column Cleaners
def GET_NSW_EV_CHARGING_COLUMN_CLEANERS() -> list[ColumnCleaner]:
    # Load ASGS LV4 Data
    sa4_gdf = gpd.read_file(AUS_ASGS_LV4_FILE)

    # Create DataCleaners
    return [
        # OBJECTID: Leave the empty rows blank at this stage. They will be filled up in the Stage 2 - Augmentation.
        # Typed as FLOAT (not INT) because ~94% of rows are missing an OBJECTID and pandas
        # cannot cast NaN into a native int column; it will be re-cast to int once Stage 2
        # backfills the missing ids.
        ColumnCleaner(
            "OBJECTID",
            DFDataType.FLOAT,
        ),
        # Station_name: Leave the empty rows blank. They will be filled up in the Stage 2 - Augmentation
        ColumnCleaner(
            "Station_name",
            DFDataType.STR,
        ),
        # Station_address: Normalize address formats
        ColumnCleaner(
            "Station_address",
            DFDataType.STR,
            post_processor=col_processor(address_processor)
        ),
        # Operator: Leave the empty rows blank. They will be filled up in the Stage 2 - Augmentation
        ColumnCleaner(
            "Operator",
            DFDataType.STR,
            special_values={
                'Viva Energy A': 'Viva Energy Australia',
                'Charge Hub': 'ChargeHub',
                'Evie': 'Evie Networks',
                'NRMA': 'NRMA Electric',
                'University of': 'University of Wollongong',  # According to charging station name
                'PLUS ES Manag': 'PLUS ES',
                'Fast Cities A': 'Fast Cities Australia'  # According to manual verifications
            },
        ),
        # Number_of_plugs
        ColumnCleaner(
            "Number_of_plugs",
            DFDataType.INT,
        ),
        ColumnCleaner(
            "Charger_Type",
            DFDataType.STR,
        ),
        ColumnCleaner(
            "Charger_rating",
            DFDataType.STR,
            special_values={
                'AC': np.nan,
            },
            post_processor=col_processor(charger_rating_processor),
            df_processor=split_charger_rating_df_processor,
        ),
        # Latitude / Longitude: enforce numeric type
        ColumnCleaner(
            "Latitude",
            DFDataType.FLOAT,
        ),
        ColumnCleaner(
            "Longitude",
            DFDataType.FLOAT,
        ),
        # LGANAME: the same council appears under multiple name formats in the source data
        ColumnCleaner(
            "LGANAME",
            DFDataType.STR,
        ),
        # PCODE: a handful of rows store "NSW 2500" instead of the bare 4-digit postcode
        ColumnCleaner(
            "PCODE",
            DFDataType.STR,
            post_processor=col_processor(pcode_processor),
            df_processor=pcode_df_processor,
        ),
        ColumnCleaner(
            "Source",
            DFDataType.STR,
        ),
        # New Feature: SA4 Name
        ColumnCleaner(
            'SA4_NAME26',
            DFDataType.STR,
            default_value=np.nan,
            column_create_function=lambda df: get_sa4_info(df, sa4_gdf)['SA4_NAME26']
        ),
        ColumnCleaner(
            'SA4_CODE26',
            DFDataType.STR,
            default_value=np.nan,
            column_create_function=lambda df: get_sa4_info(df, sa4_gdf)['SA4_CODE26']
        ),
    ]

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


def GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE(aug_df) -> list[ColumnCleaner]:
    """Return the existing ColumnCleaner interface backed by the final audit.

    The multi-source matcher writes one row per DC source record.  This adapter
    aligns that audit back to the full cleaned dataframe by ``source_index`` so
    the team's original DataCleaner pipeline can still write one complete
    augmented CSV without replacing the raw TfNSW fields.
    """
    if not TASK3_FINAL_AUDIT_FILE.exists():
        raise FileNotFoundError(
            "The final multi-source audit is missing. Run "
            "task3_final_multisource_audit.py before using the multi-source "
            "augmentation adapter."
        )

    audit = pd.read_csv(TASK3_FINAL_AUDIT_FILE, keep_default_na=False)
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
        for column in ("Station_address", "PCODE"):
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
