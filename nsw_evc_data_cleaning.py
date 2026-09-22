import re

import geopandas as gpd
import pandas as pd

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

# Split Charger_rating
def charger_rating_processor(rating):
    if pd.isna(rating):
        return rating
    # Some ratings are missing their unit (e.g. "22", "50", "7") - append it.
    if re.fullmatch(r'\d+(\.\d+)?', rating):
        return f"{rating} kW"
    return rating

def _parse_charger_rating(row):
    rating_str = str(row['Charger_rating'])

    # Regex explanation:
    # (?:(\d+)\s*[xX]\s*)? -> Optionally captures a number followed by an 'x' or 'X' (e.g., "2x")
    # (\d+(?:\.\d+)?)      -> Captures the power number, allowing for decimals (e.g., "350" or "22.5")
    # \s*[kK][wW]          -> Matches "kW" (case-insensitive) with optional spacing
    pattern = r'(?:(\d+)\s*[xX]\s*)?(\d+(?:\.\d+)?)\s*[kK][wW]'
    matches = re.findall(pattern, rating_str)

    counts = {}
    for multiplier, power in matches:
        # Format power to drop trailing zeros (e.g. 19.0 -> 19) for cleaner column names
        power_fmt = f"{float(power):g}"
        col_name = f"Charger_rating.{power_fmt}kW"

        # Use the multiplier if it exists (e.g., "2" from "2x350kW"), else use Number_of_plugs
        count = int(multiplier) if multiplier else int(row['Number_of_plugs'])

        # Add to counts (using .get() allows us to sum them if a rating appears twice)
        counts[col_name] = counts.get(col_name, 0) + count

    return pd.Series(counts)


def split_charger_rating_df_processor(df: pd.DataFrame):
    charger_rating_cols = df.apply(_parse_charger_rating, axis=1).fillna(0).astype(int)
    for col in charger_rating_cols.columns:
        df[col] = charger_rating_cols[col].reindex(df.index).fillna(0)
    return df


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

# SA4
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
