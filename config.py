"""Compatibility imports for older team scripts.

New stages import nsw_evc_cleaning_config or data_augmentation_config directly.
There is no cleaning or augmentation implementation in this module.
"""
from nsw_evc_cleaning_config import *  # noqa: F403
from nsw_evc_data_cleaning import *  # noqa: F403
from data_augmentation_config import (
    GET_NSW_EV_COLUMN_AUGMENTATION_CCS,
    GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE,
    TASK3_FINAL_AUDIT_FILE,
    get_ocm_details,
)


def __getattr__(name):
    # Old exploratory scripts import private OCM normalisation helpers.
    from data_utils import ocm_reference
    try:
        return getattr(ocm_reference, name)
    except AttributeError:
        raise AttributeError(f"module config has no attribute {name!r}") from None
