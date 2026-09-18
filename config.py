# Data file location
import re

import geopandas as gpd
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
    # Some ratings are missing their unit (e.g. "22", "50", "7") - append it.
    if re.fullmatch(r'\d+(\.\d+)?', rating):
        return f"{rating} kW"
    return rating

# PCODE
def pcode_processor(pcode):
    if pd.isna(pcode):
        return pcode
    # A few rows store "NSW 2500" instead of the bare postcode - extract the digits.
    match = re.search(r'\d{4}', str(pcode))
    return match.group(0) if match else pcode

def pcode_df_processor(df):
    for row in df.itertuples():
        addr_pcode_match = re.search(r'\d{4}$', str(row.Station_address))
        addr_pcode = addr_pcode_match.group(0) if addr_pcode_match else None
        if addr_pcode is not None and addr_pcode != row.PCODE:
            df.at[row.Index, 'PCODE'] = addr_pcode
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

# 1.2. Define Column Cleaners
def GET_NSW_EV_CHARGING_COLUMN_CLEANERS() -> list[ColumnCleaner]:
    # Load ASGS LV4 Data
    sa4_gdf = gpd.read_file(AUS_ASGS_LV4_FILE)

    # Create DataCleaners
    cleaners = [
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
            post_processor=col_processor(pcode_processor),
            df_processor=pcode_df_processor
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
    # Clean Ratings Data

    return cleaners

# TODO: 2. Data Augmentation: Enrich NSW EV Charging Locations details
# TODO: 2.1. Create a function: Get charger details from the OCM API
def get_ocm_details(fact_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fetching EV charging station details from OCM API one-by-one.
    Notice: OCM API doesn't support batch query, please fetch them row-by-row with a half-second sleep.
    :param fact_df:
    :return: A pd.DataFrame contains all the features (columns) that can be added into the original DF directly
    """
    pass # todo: Please remove this line once finished
# TODO: 2.2. Column (feature) creation function for new features

# TODO: 2.3. ColumnCleaners for NSW EV data augmentation:
def GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df) -> list[ColumnCleaner]:
    ocm_df = get_ocm_details(aug_df)
    return [
        # TODO: Create ColumnCleaners
    ]
