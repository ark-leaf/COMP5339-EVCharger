# Data file location

import geopandas as gpd
import numpy as np
import pandas as pd
from pathlib import Path

from data_utils.column_cleaner import ColumnCleaner, DFDataType
from pipeline.data_clean.nsw_evc_data_clean_utils import address_processor, address_formalizer, col_processor, charger_rating_processor, pcode_processor, \
    pcode_df_processor, get_sa4_info, split_charger_rating_df_processor
from config import AUS_ASGS_LV4_FILE

# 1.2. Define Column Cleaners
def GET_NSW_EV_CHARGING_COLUMN_CLEANERS() -> list[ColumnCleaner]:
    # Load ASGS LV4 Data
    sa4_gdf = None
    if AUS_ASGS_LV4_FILE.exists():
        sa4_gdf = gpd.read_file(AUS_ASGS_LV4_FILE)
    else:
        import warnings
        warnings.warn(f"SA4 shapefile not found at {AUS_ASGS_LV4_FILE}. SA4 info will be empty.", UserWarning)

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
        # Station_address: Normalize and enrich address formats
        ColumnCleaner(
            "Station_address",
            DFDataType.STR,
            df_processor=address_processor
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
            df_processor=split_charger_rating_df_processor
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
            column_create_function=lambda df: get_sa4_info(df, sa4_gdf)['SA4_NAME26'] if sa4_gdf is not None else pd.Series([np.nan] * len(df), index=df.index)
        ),
        ColumnCleaner(
            'SA4_CODE26',
            DFDataType.STR,
            default_value=np.nan,
            column_create_function=lambda df: get_sa4_info(df, sa4_gdf)['SA4_CODE26'] if sa4_gdf is not None else pd.Series([np.nan] * len(df), index=df.index)
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
