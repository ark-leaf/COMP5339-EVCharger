from config import NSW_EV_CHARGING_SRC_FILE, NSW_EV_CHARGING_CLEAN_SRC_FILE, GET_NSW_EV_CHARGING_COLUMN_CLEANERS, \
    NSW_EV_CHARGING_AUG_FILE, GET_NSW_EV_COLUMN_AUGMENTATION_CCS
from data_utils.csv_file_helper import CsvFileHelper
from data_utils.data_cleaner import DataCleaner

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

clean_result = nsw_ev_charging_cleaner.clean_data()
# DataCleaner returns a lazy chunk generator when a file input is used.
# Consume it so the cleaned file is actually written.
if hasattr(clean_result, "__next__"):
    for _ in clean_result:
        pass

# 2. Data Augmentation
# EXPERIMENTAL Task 3 trial: the config function currently uses a local
# Peclet snapshot and exact coordinate matching only.
# MANUAL TODO: replace this with the final agreed external-source/matching
# policy after reviewing the trial output.
# Config the augmentation file helper
aug_file_helper = CsvFileHelper(
    input_file_name=NSW_EV_CHARGING_CLEAN_SRC_FILE,
    output_file_name=NSW_EV_CHARGING_AUG_FILE)

# Get the clean data to be augmented
aug_df = aug_file_helper.read_file()

# Clean the augmented data
nsw_ev_charging_cleaner = DataCleaner(
    GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df),
    input_data_frame=aug_df,
    # Supplying file names lets the existing DataCleaner write the result.
    input_file_name=NSW_EV_CHARGING_CLEAN_SRC_FILE,
    output_file_name=NSW_EV_CHARGING_AUG_FILE,
)

aug_result_df = nsw_ev_charging_cleaner.clean_data()

# 3. Data Transformation and Storage
ts_file_helper = (CsvFileHelper(
    input_file_name=NSW_EV_CHARGING_AUG_FILE,
    output_file_name=NSW_EV_CHARGING_AUG_FILE
))
ts_df = ts_file_helper.read_file()
ts_df
# MANUAL TODO: Store the final augmented dataset into DuckDB tables after the
# external fields and matching policy are confirmed.
