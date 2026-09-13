# Data file location
import re

import numpy as np
import pandas as pd

from data_utils.column_cleaner import ColumnCleaner, DFDataType

# 0.1. File Locations
SRC_DATA_FILE_LOCATION = "src_data"
CLEAN_SRC_DATA_FILE_LOCATION = "clean_src_data"
RESULT_DATA_FILE_LOCATION = "result_data"

# 0.2. APIs
# 0.2.1. NSW EV Charging Locations - NSW Transport Open Data
NSW_TRANSPORT_API_TOKEN = "comp5339-usyd"
NSW_EV_CHARGING_SRC_FILE_URL = "https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv"
NSW_EV_CHARGING_SRC_FILE_NAME = "nsw_ev_charging.csv"

# 0.2.2. ABS ASGS Statistical Area Level 4
AUS_ASGS_LV4_URL = "https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files/SA4_2026_AUST_SHP_GDA2020.zip"
AUS_ASGS_LV4_ZIP_FILE_NAME = "SA4_2026_AUST_SHP_GDA2020.zip"

# 0.2.3. OpenStreetMap API
OSM_API_PROD = "https://api.openstreetmap.org/api/"
OSM_API_SANDBOX = "https://master.apis.dev.openstreetmap.org/"


# def call_osm(method, params={}, version="0.6") -> pd.DataFrame:

# 0.2.4. Peclet Charger Data

# 1. Data Cleaning and Integration
# 1.1. Cleaning and Integration: NSW EV Charging Locations + AUS ASGS Level 4

# 1.1.1. Define the post processors for address columns
def address_processor(addr: pd.DataFrame):
    if pd.isna(addr):
        return addr

    # Clean string and remove linebreaks
    addr = str(addr).replace('\n', ', ').strip()
    addr = re.sub(r'\s+', ' ', addr)
    addr = re.sub(r',\s*Australia\s*$', '', addr, flags=re.IGNORECASE)

    # Extract state and postcode
    postcode_match = re.search(r'\b(\d{4})\b', addr)
    postcode = postcode_match.group(1) if postcode_match else ''

    state_match = re.search(r'\b(NSW|VIC|ACT|QLD|SA|WA|NT|TAS)\b', addr, flags=re.IGNORECASE)
    state = state_match.group(1).upper() if state_match else 'NSW'

    # Remove state and postcode to isolate street and suburb
    clean_addr = addr
    if postcode:
        clean_addr = re.sub(r'\b' + postcode + r'\b', '', clean_addr)
    if state_match:
        clean_addr = re.sub(r'\b' + state_match.group(1) + r'\b', '', clean_addr, flags=re.IGNORECASE)

    parts = [p.strip() for p in clean_addr.split(',') if p.strip()]

    # Standardize abbreviations
    replacements = {
        r'\bSt\b': 'Street', r'\bRd\b': 'Road', r'\bLn\b': 'Lane',
        r'\bHwy\b': 'Highway', r'\bDr\b': 'Drive', r'\bAve\b': 'Avenue',
        r'\bPde\b': 'Parade', r'\bPl\b': 'Place', r'\bCres\b': 'Crescent',
        r'\bBlvd\b': 'Boulevard', r'\bCct\b': 'Circuit', r'\bCl\b': 'Close'
    }

    formatted_parts = []
    for part in parts:
        for pattern, replacement in replacements.items():
            part = re.sub(pattern, replacement, part, flags=re.IGNORECASE)
        part = part.title()
        part = re.sub(r'\b([0-9]+[a-z])\b', lambda x: x.group(0).upper(), part)
        formatted_parts.append(part)

    # Separate street and suburb
    street, suburb = "", ""
    if len(formatted_parts) == 1:
        if re.search(r'\d', formatted_parts[0]):
            street = formatted_parts[0]
        else:
            suburb = formatted_parts[0]
    elif len(formatted_parts) == 2:
        street = formatted_parts[0]
        suburb = formatted_parts[1]
    elif len(formatted_parts) > 2:
        suburb = formatted_parts[-1]
        street = ', '.join(formatted_parts[:-1])

    # Reconstruct final string
    unified = f"{street + ', ' if street else ''}{suburb + ' ' if suburb else ''}{state} {postcode}".strip()
    return unified.strip(', ')


# 1.1.2. Define feature creation function for SA4 column

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


def parse_combo_rating(rating_str):
    """Parse complex charger rating strings like '2x350kW & 6x175kW'.

    Returns tuple: (total_plugs, ratings_list)
    - total_plugs: Sum of all plug counts
    - ratings_list: List of individual ratings (e.g., ['350 kW', '175 kW'])
    """
    if pd.isna(rating_str):
        return None, []

    rating_str = str(rating_str).strip()

    # Pattern: "NxCAPkW" (e.g., "2x350kW", "6x175kW")
    import re
    combo_pattern = r'(\d+)x(\d+)(?:kW)?'
    matches = re.findall(combo_pattern, rating_str, re.IGNORECASE)

    if matches:
        # Found combo format like "2x350kW & 6x175kW"
        total_plugs = 0
        ratings_list = []
        for count_str, capacity_str in matches:
            count = int(count_str)
            capacity = int(capacity_str)
            total_plugs += count
            # Add individual capacity entries (e.g., '350 kW' x 2)
            for _ in range(count):
                ratings_list.append(f"{capacity} kW")
        return total_plugs, ratings_list
    else:
        # Single rating format like "150 kW" or "22 kW"
        capacity_match = re.search(r'(\d+(?:\.\d+)?)', rating_str)
        if capacity_match:
            capacity = capacity_match.group(1)
            return 1, [f"{capacity} kW"]
        else:
            return None, []


# General extractors using parameterization

def extract_rating_by_type(charger_type, exclude_placeholder=False):
    """Extract charger rating for a specific type.

    Args:
        charger_type: 'AC' or 'DC' to filter by
        exclude_placeholder: If True, skip placeholder values like 'AC'
    """
    def extractor(df):
        return df.apply(
            lambda row: (
                row['Charger_rating']
                if row['Charger_Type'] == charger_type
                and pd.notna(row['Charger_rating'])
                and (not exclude_placeholder or row['Charger_rating'] != 'AC')
                else np.nan
            ),
            axis=1
        )
    return extractor

def extract_plug_count_by_type(charger_types, use_combo_parsing=False):
    """Extract plug count for specific charger types.

    Args:
        charger_types: list of charger types to include (e.g., ['AC'] or ['DC', 'Upcoming'])
        use_combo_parsing: If True, try to parse combo ratings like "2x350kW & 6x175kW"
    """
    def extractor(df):
        def get_plugs(row):
            if row['Charger_Type'] not in charger_types:
                return np.nan

            if use_combo_parsing:
                # Try to parse combo rating first
                plug_count, _ = parse_combo_rating(row['Charger_rating'])
                if plug_count is not None:
                    return float(plug_count)

            # Fallback to Number_of_plugs
            if pd.notna(row['Number_of_plugs']):
                return float(row['Number_of_plugs'])

            return np.nan
        return df.apply(get_plugs, axis=1)
    return extractor

# Convenience functions for the column cleaners
extract_ac_charger_rating = extract_rating_by_type('AC', exclude_placeholder=True)
extract_dc_charger_rating = extract_rating_by_type('DC')
extract_ac_plug_count = extract_plug_count_by_type(['AC'])
extract_dc_plug_count = extract_plug_count_by_type(['DC', 'Upcoming'], use_combo_parsing=True)

def extract_status(df):
    """Extract status: 'Upcoming' for Upcoming chargers, 'Existing' for others."""
    return df['Charger_Type'].apply(lambda x: 'Upcoming' if x == 'Upcoming' else 'Existing')


# 1.1.3. Define Column Cleaners
NSW_EV_CHARGING_COLUMN_CLEANERS = [
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
    # Source: dataset/program the record came from. Rows for 'Upcoming' stations lack
    # this (and LGANAME/PCODE) entirely in the source data - left blank, to be
    # backfilled in Stage 2 if that metadata becomes available.
    ColumnCleaner(
        "Source",
        DFDataType.STR,
    ),
    # New feature: AC_charger_rating (extracted from mixed Charger_rating when Charger_Type='AC')
    ColumnCleaner(
        "AC_charger_rating",
        DFDataType.STR,
        column_create_function=extract_ac_charger_rating
    ),
    # New feature: Number_of_AC_plugs (count of AC plugs, NaN for non-AC chargers)
    # Note: Using FLOAT type to preserve NaN values (INT cannot hold NaN)
    ColumnCleaner(
        "Number_of_AC_plugs",
        DFDataType.FLOAT,
        column_create_function=extract_ac_plug_count
    ),
    # New feature: DC_charger_rating (extracted from mixed Charger_rating when Charger_Type='DC')
    ColumnCleaner(
        "DC_charger_rating",
        DFDataType.STR,
        column_create_function=extract_dc_charger_rating
    ),
    # New feature: Number_of_DC_plugs (count of plugs, parsed from combo ratings for DC and Upcoming)
    # Note: Using FLOAT type to preserve NaN values (INT cannot hold NaN)
    ColumnCleaner(
        "Number_of_DC_plugs",
        DFDataType.FLOAT,
        column_create_function=extract_dc_plug_count
    ),
    # New categorical feature: Status (Existing = operational, Upcoming = not yet built)
    ColumnCleaner(
        "Status",
        DFDataType.STR,
        column_create_function=extract_status
    ),
]
# 1.2. Cleaning: Peclet Charger Data

# 2. Data Augmentation: Replenishing NSW EV Charging Locations data from Peclet Charger Data

# Final: Data Processing Pipeline Configuration
