"""Data Augmentation Script for NSW EV Charging Data

Enhances cleaned NSW EV charging data with additional features and attributes
from external data sources (OCM, multi-source audit, etc.).

This script follows the same pattern as data_clean_script.py for consistency.
"""
import pandas as pd

from data_utils.file_utils import YFileUtils
from data_utils.data_cleaner import DataCleaner
from config import NSW_EV_CHARGING_CLEANED_FILE, NSW_EV_CHARGING_AUG_FILE
from pipeline.data_aug.nsw_evc_aug_config import GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE, TASK3_FINAL_AUDIT_FILE, \
    GET_NSW_EV_COLUMN_AUGMENTATION_CCS

def nsw_evc_augmentation():
    """Execute data augmentation for NSW EV charging dataset.

    Task 3 uses the final multi-source audit when available. Before the
    audit exists, the original OCM-only adapter remains a compatible fallback.
    """

    # Load cleaned data to be augmented
    # Postal/SA4 codes are identifiers: preserve their cleaned text form instead
    # of letting pandas turn them into floats and write spurious ".0" suffixes.
    aug_df = YFileUtils.read_file(
        NSW_EV_CHARGING_CLEANED_FILE,
        format='auto',
        chunk_size=-1  # Read entire file
    )

    # Ensure proper data types for codes
    for col in ["PCODE", "PCODE_ORIGINAL", "SA4_CODE26"]:
        if col in aug_df.columns:
            aug_df[col] = aug_df[col].astype("string")

    source_columns_before_augmentation = aug_df.copy(deep=True)

    # Select augmentation strategy based on audit file availability
    augmentation_cleaners = (
        GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE(aug_df)
        if TASK3_FINAL_AUDIT_FILE.exists()
        else GET_NSW_EV_COLUMN_AUGMENTATION_CCS(aug_df)
    )

    # Apply augmentation via DataCleaner framework
    nsw_ev_charging_cleaner = DataCleaner(
        augmentation_cleaners,
        input_data_frame=aug_df,
        # input_file_name=str(NSW_EV_CHARGING_CLEANED_FILE),
        output_file_name=str(NSW_EV_CHARGING_AUG_FILE),
    )
    aug_result_df = nsw_ev_charging_cleaner.clean_data()
    print(f"NSW EV Charging data augmented: {NSW_EV_CHARGING_AUG_FILE}")
    return aug_result_df


if __name__ == "__main__":
    nsw_evc_augmentation()
