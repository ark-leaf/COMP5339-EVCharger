"""Team entry point: Task 2 cleaning followed by independent Task 3 augmentation."""
from __future__ import annotations

import argparse
import json


def run_cleaning():
    from nsw_evc_cleaning_config import (
        GET_NSW_EV_CHARGING_COLUMN_CLEANERS,
        NSW_EV_CHARGING_SRC_FILE, NSW_EV_CHARGING_CLEAN_SRC_FILE,
    )
    from data_utils.data_cleaner import DataCleaner
    cleaner = DataCleaner(
        GET_NSW_EV_CHARGING_COLUMN_CLEANERS(),
        input_file_name=NSW_EV_CHARGING_SRC_FILE,
        input_file_trunk_size=20000,
        output_file_name=NSW_EV_CHARGING_CLEAN_SRC_FILE,
    )
    for _ in cleaner.clean_data():
        pass
    return NSW_EV_CHARGING_CLEAN_SRC_FILE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "clean", "augment"), default="all")
    args = parser.parse_args(argv)
    if args.stage in ("all", "clean"):
        run_cleaning()
    if args.stage in ("all", "augment"):
        from task3_pipeline import run_task3
        print(json.dumps(run_task3(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
