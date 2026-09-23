"""Compatibility import for the relocated Task 3 module."""
from pipeline.data_aug.multisource_audit import *  # noqa: F403


def __getattr__(name):
    from pipeline.data_aug import multisource_audit as implementation
    return getattr(implementation, name)
