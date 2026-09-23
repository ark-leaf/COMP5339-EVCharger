"""Team Task 3 entry: consume Task 2 CSV, match, audit, validate and export."""
from pipeline.data_aug.nsw_evc_aug_config import Task3Config
from pipeline.data_aug.nsw_evc_aug_utils import main, run_task3


def nsw_evc_charging_augmentation(settings: Task3Config | None = None):
    """Return the augmented DataFrame, preserving the teammate's public interface."""
    settings = settings or Task3Config()
    report = run_task3(settings)
    print(
        f"Task 3 validated: {report['accepted_rows']}/{report['dc_rows']} DC rows "
        f"({report['accepted_coverage']:.2%}); output: {settings.output_file}"
    )
    import pandas as pd
    return pd.read_csv(settings.output_file, dtype={
        "PCODE": "string", "PCODE_ORIGINAL": "string", "SA4_CODE26": "string",
    })


if __name__ == "__main__":
    main()
