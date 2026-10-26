# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex helped implement nsw_evc_augmentation()
# and connect the augmentation output to the team's pipeline interface.

"""Task 3 stage: consume Task 2 output and apply audited multi-source enrichment."""
import pandas as pd

from pipeline.data_aug.nsw_evc_aug_config import Task3Config
from pipeline.data_aug.nsw_evc_aug_utils import main, run_task3


def nsw_evc_augmentation(settings: Task3Config | None = None):
    """Return the augmented frame through the teammate's current stage interface."""
    settings = settings or Task3Config()
    report = run_task3(settings)
    print(
        f"Task 3 validated: {report['accepted_rows']}/{report['dc_rows']} DC rows "
        f"({report['accepted_coverage']:.2%}); output: {settings.output_file}"
    )
    return pd.read_csv(settings.output_file, dtype={
        "PCODE": "string", "PCODE_ORIGINAL": "string", "SA4_CODE26": "string",
    })


if __name__ == "__main__":
    main()
