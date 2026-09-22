"""Data Cleaning Script for NSW EV Charging Data

Downloads raw NSW EV charging and ASGS LV4 spatial data, then cleans and integrates
them into a unified dataset with standardized formats and enriched geographic information.
"""
from data_utils.file_utils import YFileUtils
from data_utils.data_cleaner import DataCleaner
from pipeline.data_clean.nsw_evc_cleaner_config import GET_NSW_EV_CHARGING_COLUMN_CLEANERS
from config import NSW_EV_CHARGING_SRC_FILE, NSW_EV_CHARGING_CLEANED_FILE, AUS_ASGS_LV4_URL, AUS_ASGS_LV4_FILE, \
    NSW_EV_CHARGING_SRC_FILE_URL


def nsw_evc_charging_cleaning():
    """Execute data cleaning for NSW EV charging dataset.

    Steps:
    1. Download raw data files (NSW EV Charging, Australian ASGS LV4)
    2. Clean and integrate the datasets
    3. Output cleaned and enriched data
    """
    # Step 0: Download Data
    print("Step 0: Downloading source data...")

    # 0.1. Download NSW EV Charging data
    YFileUtils.download_file(NSW_EV_CHARGING_SRC_FILE_URL, NSW_EV_CHARGING_SRC_FILE, override=False)

    # 0.2. Download Aus ASGS LV4 data (spatial boundaries)
    YFileUtils.download_file(AUS_ASGS_LV4_URL, AUS_ASGS_LV4_FILE, override=False)

    # Step 1: Data Cleaning and Integration
    print("Step 1: Cleaning and integrating data...")

    nsw_ev_charging_cleaner = DataCleaner(
        GET_NSW_EV_CHARGING_COLUMN_CLEANERS(),
        input_file_name=NSW_EV_CHARGING_SRC_FILE,
        # The framework supports processing large datasets by batch.
        input_file_trunk_size=20000,  # Adjust if source file is very large
        output_file_name=NSW_EV_CHARGING_CLEANED_FILE)

    # Process data (supports streaming for large files)
    nsw_ev_charging_cleaned = None
    for one_chunk in nsw_ev_charging_cleaner.clean_data():
        nsw_ev_charging_cleaned = one_chunk

    print(f"✓ NSW EV Charging data cleaned: {NSW_EV_CHARGING_CLEANED_FILE}")
    return nsw_ev_charging_cleaned


if __name__ == "__main__":
    nsw_evc_charging_cleaning()
