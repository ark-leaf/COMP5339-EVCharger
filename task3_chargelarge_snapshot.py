# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that I wrote/adapted the initial collection functions using
# OpenAI Codex references. Codex assisted with response handling, snapshot
# metadata and output safeguards, and with corrections and tests.

"""Collect raw Charge@Large records into a new Task 3 snapshot directory.

Core collection adapted from an AI reference by the student and reviewed
with AI assistance. Legacy flattening and match statistics are not used.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://chargeatlarge.app/locations"
RAW_FILE = ROOT / "result_data" / "task3_chargelarge_raw.json"

PARAMS = {
    "powerRangeMin": 0,
    "powerRangeMax": 350,
    "connectorTypes": "",
    "onlyAvailable": "false",
    "onlyAccessible": "false",
    "operatorIds": "",
    "updatedSince": "null",
}


# STUDENT_CORE[P8-CAL]: fetch
def fetch() -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode(PARAMS)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "COMP5339-EVCharger-ass1/0.1"},
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            records = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Charge@Large request failed") from exc

    if not isinstance(records, list) or not records:
        raise ValueError("Charge@Large returned an empty or invalid response")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("Charge@Large contains a non-object record")
    return records


# STUDENT_CORE[P8-CAL]: main
def main() -> None:
    directory = os.getenv("TASK3_NEW_SNAPSHOT_DIR")
    if not directory:
        raise RuntimeError("Set TASK3_NEW_SNAPSHOT_DIR to a new directory")

    output_dir = Path(directory)
    raw_file = output_dir / RAW_FILE.name
    metadata_file = output_dir / "task3_chargelarge_metadata.json"
    if raw_file.exists() or metadata_file.exists():
        raise FileExistsError("Choose a new snapshot directory")

    records = fetch()  # Fetch successfully before touching the destination.
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metadata_file.write_text(
        json.dumps({
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(raw_file.read_bytes()).hexdigest(),
            "endpoint": ENDPOINT,
            "parameters": PARAMS,
            "raw_record_count": len(records),
            "scope_note": "Results are limited by the endpoint parameters.",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
