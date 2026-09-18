from config import NSW_EV_CHARGING_SRC_FILE, NSW_EV_CHARGING_CLEAN_SRC_FILE, GET_NSW_EV_CHARGING_COLUMN_CLEANERS, \
    NSW_EV_CHARGING_AUG_FILE, GET_NSW_EV_COLUMN_AUGMENTATION_CCS, NSW_EV_CHARGING_SRC_FILE_URL, AUS_ASGS_LV4_URL, \
    AUS_ASGS_LV4_FILE
from data_utils.csv_file_helper import CsvFileHelper
from data_utils.data_cleaner import DataCleaner
from data_utils.file_utils import YFileUtils

# 0. Download Data in Files
# 0.1. Download NSW EV Charging
# YFileUtils.download_file(NSW_EV_CHARGING_SRC_FILE_URL, NSW_EV_CHARGING_SRC_FILE)

# 0.2. Download Aus ASGS Lv.4 data
# YFileUtils.download_file(AUS_ASGS_LV4_URL, AUS_ASGS_LV4_FILE)

# 1. Data Cleaning and Integration
#  - Note: Please check the corresponding part of {config.py} for more details
nsw_ev_charging_cleaner = DataCleaner(
    GET_NSW_EV_CHARGING_COLUMN_CLEANERS(),
    input_file_name=NSW_EV_CHARGING_SRC_FILE,
    # The framework supports process original dataset by batch.
    input_file_trunk_size=20000,  # Config this field if the source data file is too large.
    output_file_name=NSW_EV_CHARGING_CLEAN_SRC_FILE)  # The cleaned fact data

nsw_ev_charging_cleaned = None
for one_chunk in nsw_ev_charging_cleaner.clean_data():
    nsw_ev_charging_cleaner = one_chunk

# 2. Data Augmentation
# TODO: Process data cleaning for step 2, using NSW_EV_COLUMN_AUGMENTATION
# # Config the augmentation file helper
# aug_file_helper = CsvFileHelper(
#     input_file_name=NSW_EV_CHARGING_CLEAN_SRC_FILE,
#     output_file_name=NSW_EV_CHARGING_AUG_FILE)
#
# # Get the clean data to be augmented
# aug_df = aug_file_helper.read_file()
#
# # Clean the augmented data
# nsw_ev_charging_cleaner = DataCleaner(
#     GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df))
#
# aug_result_df = nsw_ev_charging_cleaner.clean_data()
#
# # 3. Data Transformation and Storage
# ts_file_helper = (CsvFileHelper(
#     input_file_name=NSW_EV_CHARGING_AUG_FILE,
#     output_file_name=NSW_EV_CHARGING_AUG_FILE
# ))
# ts_df = ts_file_helper.read_file()
# ts_df
# todo: Store data into DuckDB tables
