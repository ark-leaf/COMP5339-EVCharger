"""Validate NSW OCM coverage with multiple overlapping bounding-box queries.

This audit is deliberately separate from the Task 3 matcher.  It checks
whether one large NSW bounding-box request is missing records.  The API key is
read only from ``OCM_API_KEY`` and is never written to output.

Run from the repository root, in the same shell where the key is exported:

    export OCM_API_KEY='your-real-api-key'
    python task3_ocm_tiled_snapshot.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parent
ENDPOINT = os.getenv("OCM_ENDPOINT", "https://api.openchargemap.io/v3/poi/")
API_KEY = os.getenv("OCM_API_KEY", "")
USER_AGENT = os.getenv("OCM_USER_AGENT", "COMP5339-EVCharger-ass1/0.1")
OUTPUT_DIR = ROOT / "result_data"
SNAPSHOT_FILE = OUTPUT_DIR / "task3_ocm_tiled_snapshot.json"
METADATA_FILE = OUTPUT_DIR / "task3_ocm_tiled_snapshot_metadata.json"
BOUNDARY_FILE = ROOT / "src_data" / "SA4_2026_AUST_SHP_GDA2020.zip"

# The OCM examples use (south,west),(north,east) coordinate pairs.  The
# overlap avoids losing points exactly on a tile boundary; IDs are deduped.
SOUTH, NORTH = -37.6, -27.9
WEST, EAST = 140.8, 154.3
LAT_EDGES = [-37.6, -35.175, -32.75, -30.325, -27.9]
LON_EDGES = [140.8, 144.175, 147.55, 150.925, 154.3]
OVERLAP = 0.03
MAXRESULTS = 100000
REQUEST_DELAY_SECONDS = 0.2


def poi_id(record: dict) -> str:
    value = record.get("ID")
    if value not in (None, ""):
        return f"id:{value}"
    info = record.get("AddressInfo") or {}
    return "fallback:" + "|".join(
        str(info.get(key, ""))
        for key in ("Title", "AddressLine1", "Postcode", "Latitude", "Longitude")
    )


def request_tile(south: float, west: float, north: float, east: float) -> list[dict]:
    if not API_KEY:
        raise RuntimeError(
            "OCM_API_KEY is not available in this shell. Export it and rerun "
            "the script in the same terminal."
        )
    if not API_KEY.isascii() or API_KEY in {"你的真实API_KEY", "your-real-api-key"}:
        raise RuntimeError(
            "OCM_API_KEY is still a placeholder or contains non-ASCII characters. "
            "Replace it with the actual API key from Open Charge Map; do not type "
            "the Chinese placeholder text."
        )
    params = {
        "output": "json",
        "countrycode": "AU",
        "boundingbox": f"({south},{west}),({north},{east})",
        "maxresults": MAXRESULTS,
        "compact": "false",
        "verbose": "false",
    }
    query = urllib.parse.urlencode(params)
    separator = "&" if "?" in ENDPOINT else "?"
    request = urllib.request.Request(
        f"{ENDPOINT}{separator}{query}",
        headers={"X-API-Key": API_KEY, "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"OCM rejected tile with HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"OCM tile request failed: {error}") from error
    if not isinstance(payload, list):
        raise RuntimeError("OCM returned a non-list response.")
    return [record for record in payload if isinstance(record, dict)]


def filter_nsw(records: list[dict]) -> int:
    boundary = gpd.read_file(f"zip://{BOUNDARY_FILE}")
    nsw_geometry = boundary[boundary["STE_NAME26"].eq("New South Wales")].geometry.union_all()
    points = []
    valid_ids = []
    for record in records:
        info = record.get("AddressInfo") or {}
        try:
            point = Point(float(info["Longitude"]), float(info["Latitude"]))
        except (KeyError, TypeError, ValueError):
            continue
        points.append(point)
        valid_ids.append(poi_id(record))
    if not points:
        return 0
    points_gdf = gpd.GeoDataFrame({"poi_id": valid_ids}, geometry=points, crs="EPSG:4326")
    points_gdf = points_gdf.to_crs(boundary.crs)
    return int(points_gdf.geometry.intersects(nsw_geometry).sum())


def main() -> None:
    merged: dict[str, dict] = {}
    tile_stats = []
    started = time.time()

    for lat_index in range(len(LAT_EDGES) - 1):
        for lon_index in range(len(LON_EDGES) - 1):
            south = max(SOUTH, LAT_EDGES[lat_index] - OVERLAP)
            north = min(NORTH, LAT_EDGES[lat_index + 1] + OVERLAP)
            west = max(WEST, LON_EDGES[lon_index] - OVERLAP)
            east = min(EAST, LON_EDGES[lon_index + 1] + OVERLAP)
            payload = request_tile(south, west, north, east)
            for record in payload:
                merged[poi_id(record)] = record
            tile_stats.append(
                {
                    "tile": [south, west, north, east],
                    "raw_result_count": len(payload),
                }
            )
            print(f"tile {len(tile_stats):2d}/16: {len(payload):4d} records")
            if REQUEST_DELAY_SECONDS:
                time.sleep(REQUEST_DELAY_SECONDS)

    records = list(merged.values())
    nsw_count = filter_nsw(records)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = {
        "query_mode": "16_overlapping_nsw_tiles",
        "api_query_count": len(tile_stats),
        "raw_tile_result_total": sum(item["raw_result_count"] for item in tile_stats),
        "unique_merged_record_count": len(records),
        "unique_records_inside_nsw_sa4": nsw_count,
        "maxresults_per_query": MAXRESULTS,
        "overlap_degrees": OVERLAP,
        "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "tile_stats": tile_stats,
        "snapshot_file": str(SNAPSHOT_FILE.relative_to(ROOT)),
    }
    METADATA_FILE.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw tile results: {metadata['raw_tile_result_total']}")
    print(f"Unique merged OCM IDs: {len(records)}")
    print(f"Unique records inside NSW SA4: {nsw_count}")
    print(f"Elapsed seconds: {time.time() - started:.1f}")
    print(f"Snapshot: {SNAPSHOT_FILE}")
    print(f"Metadata: {METADATA_FILE}")


if __name__ == "__main__":
    main()
