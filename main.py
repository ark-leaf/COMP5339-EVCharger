from config import NSW_EV_CHARGING_SRC_FILE, NSW_EV_CHARGING_CLEAN_SRC_FILE, GET_NSW_EV_CHARGING_COLUMN_CLEANERS, \
    NSW_EV_CHARGING_AUG_FILE, GET_NSW_EV_COLUMN_AUGMENTATION_CCS, \
    GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE, TASK3_FINAL_AUDIT_FILE
from data_utils.csv_file_helper import CsvFileHelper
from data_utils.data_cleaner import DataCleaner
import pandas as pd

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
# Task 3 uses the final multi-source audit when it is available. Before the
# audit exists, the original OCM-only adapter remains a compatible fallback.
# Config the augmentation file helper
aug_file_helper = CsvFileHelper(
    input_file_name=NSW_EV_CHARGING_CLEAN_SRC_FILE,
    output_file_name=NSW_EV_CHARGING_AUG_FILE)

# Get the clean data to be augmented
# Postal/SA4 codes are identifiers: preserve their cleaned text form instead
# of letting pandas turn them into floats and write spurious ".0" suffixes.
aug_df = pd.read_csv(
    aug_file_helper.input_file_name,
    dtype={"PCODE": "string", "SA4_CODE26": "string"},
)

# Clean the augmented data
augmentation_cleaners = (
    GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE(aug_df)
    if TASK3_FINAL_AUDIT_FILE.exists()
    else GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df)
)
nsw_ev_charging_cleaner = DataCleaner(
    augmentation_cleaners,
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
