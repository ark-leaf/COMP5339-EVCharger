"""Compatibility import for the relocated Task 3 module."""
from pipeline.data_aug.ocm_reference import *  # noqa: F403


def __getattr__(name):
    from pipeline.data_aug import ocm_reference as implementation
    return getattr(implementation, name)
