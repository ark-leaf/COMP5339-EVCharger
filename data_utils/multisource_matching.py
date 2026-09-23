"""Compatibility import for the relocated Task 3 module."""
from pipeline.data_aug.multisource_matching import *  # noqa: F403


def __getattr__(name):
    from pipeline.data_aug import multisource_matching as implementation
    return getattr(implementation, name)
