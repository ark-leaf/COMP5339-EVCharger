# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex assisted with main() stage dispatch and
# integration of the team's cleaning, augmentation and database interfaces.

"""Run the team's cleaning, augmentation and database stages."""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "clean", "augment", "load"), default="all")
    args = parser.parse_args(argv)
    if args.stage in ("all", "clean"):
        from pipeline.data_clean_script import nsw_evc_cleaning
        nsw_evc_cleaning()
    if args.stage in ("all", "augment"):
        from pipeline.data_aug_script import nsw_evc_augmentation
        nsw_evc_augmentation()
    if args.stage in ("all", "load"):
        from pipeline.data_load_script import nsw_evc_load
        nsw_evc_load()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
