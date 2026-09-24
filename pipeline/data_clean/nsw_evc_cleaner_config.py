# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex removed unused augmentation stubs, corrected
# misleading comments and added the required-boundary check in the factory.

import geopandas as gpd
import numpy as np

from data_utils.column_cleaner import ColumnCleaner, DFDataType
from pipeline.data_clean.nsw_evc_data_clean_utils import address_processor, col_processor, charger_rating_processor, pcode_processor, \
    pcode_df_processor, get_sa4_info, split_charger_rating_df_processor
from config import AUS_ASGS_LV4_FILE

# 1.2. Define Column Cleaners
def GET_NSW_EV_CHARGING_COLUMN_CLEANERS() -> list[ColumnCleaner]:
    # Load ASGS LV4 Data
    if not AUS_ASGS_LV4_FILE.is_file():
        raise FileNotFoundError(f"Required ABS SA4 archive not found: {AUS_ASGS_LV4_FILE}")
    sa4_gdf = gpd.read_file(AUS_ASGS_LV4_FILE)

    # Create DataCleaners
    cleaners = [
        # Retain missing source IDs. The loader creates a separate charger_id.
        ColumnCleaner(
            "OBJECTID",
            DFDataType.FLOAT,
        ),
        # Preserve missing names; augmentation does not overwrite source fields.
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
        # Standardize known operator aliases.
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
