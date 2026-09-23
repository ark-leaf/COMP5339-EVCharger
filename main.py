"""Team pipeline: Task 1/2 cleaning -> Task 3 augmentation -> future storage."""
from __future__ import annotations

import argparse


def run_cleaning():
    from pipeline.data_clean_script import nsw_evc_charging_cleaning
    return nsw_evc_charging_cleaning()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "clean", "augment"), default="all")
    args = parser.parse_args(argv)
    if args.stage in ("all", "clean"):
        run_cleaning()
    if args.stage in ("all", "augment"):
        from pipeline.data_aug_script import nsw_evc_charging_augmentation
        nsw_evc_charging_augmentation()


if __name__ == "__main__":
    main()
