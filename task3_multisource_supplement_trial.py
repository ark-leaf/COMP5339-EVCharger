"""Compatibility command for the modular Task 3 matcher."""
import json
from data_utils.multisource_matching import *  # noqa: F403


def main():
    print(json.dumps(run_matching(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
