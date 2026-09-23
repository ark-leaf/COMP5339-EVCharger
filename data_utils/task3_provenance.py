"""Compatibility import for the relocated Task 3 module."""
from pipeline.data_aug.provenance import *  # noqa: F403


def __getattr__(name):
    from pipeline.data_aug import provenance as implementation
    return getattr(implementation, name)
