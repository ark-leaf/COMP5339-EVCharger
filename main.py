import geopandas as gpd
import numpy as np
import pandas as pd

from config import SRC_DATA_FILE_LOCATION, NSW_EV_CHARGING_SRC_FILE_NAME, AUS_ASGS_LV4_ZIP_FILE_NAME, \
    NSW_EV_CHARGING_COLUMN_CLEANERS, CLEAN_SRC_DATA_FILE_LOCATION
from data_utils.column_cleaner import ColumnCleaner, DFDataType
from data_utils.data_cleaner import DataCleaner

# Download NSW EV Charging
# download_file(NSW_EV_CHARGING_SRC_FILE_URL, f'{SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}')

# Download Aus ASGS Lv.4 data
# download_file(AUS_ASGS_LV4_URL, f'{SRC_DATA_FILE_LOCATION}/{AUS_ASGS_LV4_ZIP_FILE_NAME}')

# Download EV Charging Stations data
# - Load SA4 data:
sa4_gdf = gpd.read_file(f'{SRC_DATA_FILE_LOCATION}/{AUS_ASGS_LV4_ZIP_FILE_NAME}')

# Define a SA4 column creation function
sa4_info_df = pd.DataFrame()
def get_sa4_info(src_df: pd.DataFrame, sa4_gdf: gpd.GeoDataFrame):
    crd_df = src_df[['Longitude', 'Latitude']]
    gdf_points = gpd.GeoDataFrame(
        crd_df,
        geometry=gpd.points_from_xy(crd_df['Longitude'], crd_df['Latitude']),
        crs='EPSG:4326', )
    gdf_points = gdf_points.to_crs(sa4_gdf.crs)
    return gpd.sjoin(gdf_points, sa4_gdf, how='left', predicate='within')

def get_sa4_gdf(src_df: pd.DataFrame, sa4_df: pd.DataFrame):
    if sa4_df.empty:
        sa4_df = get_sa4_info(src_df, sa4_gdf)
    return sa4_df


# - Add a new data cleaner into NSW_EV_CHARGING_COLUMN_CLEANERS
NSW_EV_CHARGING_COLUMN_CLEANERS.append(ColumnCleaner(
    'SA4_NAME26',
    DFDataType.STR,
    default_value=np.nan,
    column_create_function=lambda df: get_sa4_gdf(df, get_sa4_gdf(df, sa4_info_df)['SA4_NAME26'],
)))
NSW_EV_CHARGING_COLUMN_CLEANERS.append(ColumnCleaner(
    'SA4_CODE26',
    DFDataType.STR,
    default_value=np.nan,
    column_create_function=lambda df: get_sa4_gdf(df, get_sa4_gdf(df, sa4_info_df)['SA4_CODE26'],
)))

# Data Cleaning: NSW EV Charging
nsw_ev_charging_cleaner = DataCleaner(
    NSW_EV_CHARGING_COLUMN_CLEANERS,
    input_file_name=f'{SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}',
    input_file_trunk_size=20000,
    output_file_name=f'{CLEAN_SRC_DATA_FILE_LOCATION}/{NSW_EV_CHARGING_SRC_FILE_NAME}')

nsw_ev_charging_cleaner.clean_data()
