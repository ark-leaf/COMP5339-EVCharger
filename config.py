from __future__ import annotations

# Data file location
import json
import math
import re
import unicodedata
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

# 0.2.3. Open Charger Map (OCM):
OCM_ENDPOINT = ""
OCM_API_KEY = ""

# 0.2.4. OpenStreetMap API
OSM_API_PROD = "https://api.openstreetmap.org/api/"
OSM_API_SANDBOX = "https://master.apis.dev.openstreetmap.org/"

# 0.2.5. EXPERIMENTAL external charger snapshot for the first Task 3 trial.
# MANUAL TODO: replace this local path with the team's agreed source/API
# configuration before submission. The trial deliberately uses a local snapshot
# and does not make live network requests.
PECLET_REFERENCE_FILE = (
    Path("/Users/caodengjie/Desktop/26S2/5339/ass1")
    / "drive-download-20260915T070916Z-1-001"
    / "ev-charging-stations.json"
)
TASK3_COORDINATE_PRECISION = 6
TASK3_MAX_NEAR_DISTANCE_METRES = 5.0
TASK3_MIN_NEAREST_GAP_METRES = 20.0

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
            post_processor=col_processor(charger_rating_processor)
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
            post_processor=col_processor(pcode_processor)
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
    labels = []
    for field, label in (("tesla", "Tesla"), ("type_2", "Type 2"), ("j_1772", "J-1772")):
        try:
            if record.get(field) is not None and float(record[field]) > 0:
                labels.append(label)
        except (TypeError, ValueError):
            continue
    return "; ".join(labels)


# TODO: 2. Data Augmentation: Enrich NSW EV Charging Locations details
# TODO: 2.1. Create a function: Get charger details from the OCM API
def get_ocm_details(fact_df: pd.DataFrame) -> pd.DataFrame:
    """
    EXPERIMENTAL three-rule charger augmentation for a local first trial.

    The interface is retained for the team's planned OCM implementation. The
    temporary trial reads the local Peclet snapshot and returns one aligned
    result row per input fact row.
    """
    # ------------------------------------------------------------------
    # EXPERIMENTAL FIRST TRIAL ONLY
    # ------------------------------------------------------------------
    # The three acceptance rules intentionally mirror the previous local
    # probe. The result keeps all evidence needed for later manual review.
    # MANUAL TODO: confirm whether OCM or Peclet is the final external source.
    # MANUAL TODO: add the agreed API/local-cache retrieval and provenance.
    if not PECLET_REFERENCE_FILE.exists():
        raise FileNotFoundError(
            "Set PECLET_REFERENCE_FILE to the local external station snapshot "
            "before running the Task 3 trial."
        )

    with PECLET_REFERENCE_FILE.open("r", encoding="utf-8") as handle:
        reference_records = json.load(handle)

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
                "external_source": "Peclet local snapshot (experimental)",
                "external_station_id": record.get("ev_station_id", ""),
                "external_station_name": record.get("station_name", ""),
                "external_station_address": record.get("station_address", ""),
                "external_operator": record.get("operator", ""),
                "external_plug_types": _task3_plug_types(record),
                "external_number_of_plugs": record.get("number_of_plugs"),
                "external_charger_capacity": record.get("charger_capacities", ""),
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
    """Return temporary Task 3 cleaners backed by the local trial result."""
    ocm_df = get_ocm_details(aug_df)

    def create_column(column_name):
        # The augmentation result is indexed from the same fact dataframe.
        # MANUAL TODO: preserve this alignment when the final matcher is added.
        return lambda current_df: ocm_df.reindex(current_df.index)[column_name]

    return [
        # EXPERIMENTAL columns. Rename/normalise these after the team confirms
        # the final external schema and avoids replacing original source fields.
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
