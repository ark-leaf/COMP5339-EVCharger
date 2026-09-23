"""Task 2 processors, following ark-yeh's module split.

Retains the existing postcode-provenance and missing-count safeguards.
"""
from __future__ import annotations

import re
import numpy as np
import pandas as pd
import geopandas as gpd

def _text(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()



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
    original = df["PCODE"].map(_text)
    df["PCODE_ORIGINAL"] = original
    df["PCODE_REPAIRED_FROM_ADDRESS"] = False
    address_postcode = df["Station_address"].map(
        lambda value: (
            re.search(r"(?<!\d)(\d{4})\s*$", _text(value)).group(1)
            if re.search(r"(?<!\d)(\d{4})\s*$", _text(value))
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
    rating = _text(row.get("Charger_rating"))
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
