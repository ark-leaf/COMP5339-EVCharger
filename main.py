"""Main pipeline execution script for NSW EV Charging data processing.

Orchestrates the complete data pipeline:
1. Data Cleaning - Integrates NSW EV charging with ASGS LV4 spatial data
2. Data Augmentation - Enriches cleaned data with external sources
3. Data Loading - Loads results to DuckDB

All configuration is managed in config.py
"""
import sys

from pipeline.data_aug_script import nsw_evc_charging_augmentation
from pipeline.data_clean_script import nsw_evc_charging_cleaning


def main():
    """Execute the complete NSW EV charging data pipeline."""
    try:
        print("═" * 70)
        print("NSW EV CHARGING DATA PROCESSING PIPELINE")
        print("═" * 70)
        print()

        # Step 1: Data Cleaning
        print("Step 1: Data Cleaning")
        print("─" * 70)
        nsw_evc_charging_cleaning()
        print()

        # Step 2: Data Augmentation
        print("Step 2: Data Augmentation")
        print("─" * 70)
        nsw_evc_charging_augmentation()
        print()

        # Step 3: Data Transfer and Save (optional)
        # print("Step 3: Data Loading")
        # print("─" * 70)
        # subprocess.run([sys.executable, "pipeline/data_load_script.py"])
        # print()

        print("═" * 70)
        print("PIPELINE EXECUTION COMPLETE")
        print("═" * 70)
        return 0

    except Exception as e:
        print()
        print("═" * 70)
        print(f"PIPELINE FAILED: {e}")
        print("═" * 70)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
