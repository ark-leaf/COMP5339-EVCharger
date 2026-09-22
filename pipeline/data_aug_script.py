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

def nsw_evc_charging_augmentation():
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
        input_file_name=NSW_EV_CHARGING_CLEANED_FILE,
        output_file_name=NSW_EV_CHARGING_AUG_FILE,
    )

    aug_result_df = nsw_ev_charging_cleaner.clean_data()

    # Fail fast if the final Task 3 adapter changes source values, leaks candidate-
    # only attributes, or falls below the assignment's 50% DC enrichment target.
    if TASK3_FINAL_AUDIT_FILE.exists():
        # Validate source columns were not modified
        for column in source_columns_before_augmentation.columns:
            before = source_columns_before_augmentation[column].astype("string").fillna("")
            after = aug_result_df[column].astype("string").fillna("")
            if not before.equals(after):
                raise ValueError(f"Task 3 augmentation changed source column {column}.")

        # Validate DC enrichment target
        dc_mask = aug_result_df["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")
        accepted_mask = aug_result_df["augmentation_match_status"].eq("accepted")
        required_rows = (int(dc_mask.sum()) + 1) // 2
        if int((dc_mask & accepted_mask).sum()) < required_rows:
            raise ValueError("Task 3 augmentation no longer meets the 50% DC-row target.")

        # Validate external attributes are properly handled
        if aug_result_df.loc[accepted_mask, "external_attributes_json"].eq("").any():
            raise ValueError("An accepted Task 3 row has no exported external attributes.")
        if aug_result_df.loc[~accepted_mask, "external_attributes_json"].ne("").any():
            raise ValueError("A review/unmatched Task 3 row exported candidate-only attributes.")

        # Validate quality review flags
        if aug_result_df.loc[aug_result_df["augmentation_quality_review"], "augmentation_match_status"].ne("accepted").any():
            raise ValueError("A Task 3 quality flag was attached to a non-accepted row.")

    print(f"NSW EV Charging data augmented: {NSW_EV_CHARGING_AUG_FILE}")
    return aug_result_df


if __name__ == "__main__":
    nsw_evc_charging_augmentation()
