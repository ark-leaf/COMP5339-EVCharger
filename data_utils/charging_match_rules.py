"""Compatibility import for the relocated Task 3 module."""
from pipeline.data_aug.charging_match_rules import *  # noqa: F403


def __getattr__(name):
    from pipeline.data_aug import charging_match_rules as implementation
    return getattr(implementation, name)
