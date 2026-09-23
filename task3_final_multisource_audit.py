"""Compatibility command for the modular Task 3 audit."""
import json
from data_utils.multisource_audit import *  # noqa: F403


def main():
    print(json.dumps(run_audit(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
