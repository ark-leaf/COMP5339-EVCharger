"""Collect tiled OCM records into a new Task 3 snapshot directory.

Core collection adapted from an AI reference by the student and reviewed
with AI assistance. NSW boundary filtering occurs in the matching loader.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENDPOINT = os.getenv("OCM_ENDPOINT", "https://api.openchargemap.io/v3/poi/")
USER_AGENT = os.getenv("OCM_USER_AGENT", "COMP5339-EVCharger-ass1/0.1")
OUTPUT_DIR = ROOT / "result_data"
SNAPSHOT_FILE = OUTPUT_DIR / "task3_ocm_tiled_snapshot.json"
METADATA_FILE = OUTPUT_DIR / "task3_ocm_tiled_snapshot_metadata.json"

# The OCM examples use (south,west),(north,east) coordinate pairs.  The
# overlap avoids losing points exactly on a tile boundary; IDs are deduped.
SOUTH, NORTH = -37.6, -27.9
WEST, EAST = 140.8, 154.3
LAT_EDGES = [-37.6, -35.175, -32.75, -30.325, -27.9]
LON_EDGES = [140.8, 144.175, 147.55, 150.925, 154.3]
OVERLAP = 0.03
MAXRESULTS = 100000
REQUEST_DELAY_SECONDS = 0.2


# STUDENT_CORE[P8-OCM]: poi_id
def poi_id(record: dict) -> str:
    value = record.get("ID")
    if value is None or value == "" or isinstance(value, bool):
        raise ValueError("OCM record has no ID")
    return str(value)


# STUDENT_CORE[P8-OCM]: request_tile
def request_tile(south: float, west: float, north: float, east: float) -> list[dict]:
    key = os.getenv("OCM_API_KEY", "")
    if not key or not key.isascii():
        raise RuntimeError("Set a valid OCM_API_KEY in the current shell")

    params = {
        "output": "json",
        "countrycode": "AU",
        "boundingbox": f"({south},{west}),({north},{east})",
        "maxresults": MAXRESULTS,
        "compact": "false",
        "verbose": "false",
    }
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={"X-API-Key": key, "User-Agent": USER_AGENT},
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            records = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OCM returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("OCM request failed") from exc

    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("OCM response is not a list of records")
    if len(records) >= MAXRESULTS:
        raise RuntimeError("OCM tile may be truncated; split it into smaller tiles")
    return records


# STUDENT_CORE[P8-OCM]: main
def main() -> None:
    directory = os.getenv("TASK3_NEW_SNAPSHOT_DIR")
    if not directory:
        raise RuntimeError("Set TASK3_NEW_SNAPSHOT_DIR to a new directory")

    output_dir = Path(directory)
    snapshot = output_dir / SNAPSHOT_FILE.name
    metadata_file = output_dir / METADATA_FILE.name
    if snapshot.exists() or metadata_file.exists():
        raise FileExistsError("Choose a new snapshot directory")

    records_by_id = {}
    tile_stats = []

    for i in range(len(LAT_EDGES) - 1):
        for j in range(len(LON_EDGES) - 1):
            south = max(SOUTH, LAT_EDGES[i] - OVERLAP)
            north = min(NORTH, LAT_EDGES[i + 1] + OVERLAP)
            west = max(WEST, LON_EDGES[j] - OVERLAP)
            east = min(EAST, LON_EDGES[j + 1] + OVERLAP)

            batch = request_tile(south, west, north, east)
            for record in batch:
                records_by_id.setdefault(poi_id(record), record)

            tile_stats.append({
                "bounds": [south, west, north, east],
                "returned": len(batch),
            })
            time.sleep(REQUEST_DELAY_SECONDS)

    if not records_by_id:
        raise ValueError("OCM returned no records for the requested tiles")

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(list(records_by_id.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metadata_file.write_text(
        json.dumps({
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            "query_count": len(tile_stats),
            "unique_records": len(records_by_id),
            "tiles": tile_stats,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
