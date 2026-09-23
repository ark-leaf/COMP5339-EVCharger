"""Retrieve the NSW OSM-derived mirror snapshot for Task 3 (no API key).

Cache-first by default. Use --refresh to query the live API, preferably with
--output-dir pointing to a new directory to retain the benchmark snapshot.
API reference: https://help.opendatasoft.com/apis/ods-explore-v2/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/osm-australia-charging-station/records"
SNAPSHOT_NAME = "task3_osm_nsw_snapshot_for_multisource.json"
METADATA_NAME = "task3_osm_snapshot_metadata.json"
NSW_FILTER = "meta_name_state='New South Wales'"


def request_page(params: dict, timeout: float = 30, attempts: int = 3) -> dict:
    request = urllib.request.Request(
        f"{ENDPOINT}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": "COMP5339-EVCharger-ass1/0.1", "Accept": "application/json"},
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt + 1 == attempts:
                raise RuntimeError(f"OSM mirror returned HTTP {error.code}; snapshot unchanged.") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt + 1 == attempts:
                raise RuntimeError("OSM mirror request failed; snapshot unchanged.") from error
        time.sleep(2 ** attempt)
    raise RuntimeError("No OSM request attempt was made.")


def record_id(record: dict) -> str:
    value = record.get("meta_osm_id")
    if value is None or str(value).strip() == "":
        raise ValueError("OSM record has no meta_osm_id.")
    value = str(value).strip()
    return value[:-2] if value.endswith(".0") and value[:-2].isdigit() else value


def validate_records(records: list[dict]) -> None:
    if not isinstance(records, list) or not records:
        raise ValueError("OSM snapshot must be a nonempty JSON list.")
    ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("OSM snapshot contains a non-object record.")
        identifier = record_id(record)
        if identifier in ids:
            raise ValueError(f"Duplicate OSM ID in snapshot: {identifier}")
        ids.add(identifier)
        if record.get("meta_name_state") != "New South Wales":
            raise ValueError("OSM snapshot contains a record outside the NSW query.")
        point = record.get("meta_geo_point") or {}
        try:
            lat, lon = float(point["lat"]), float(point["lon"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("OSM record lacks usable coordinates.") from error
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("OSM record has invalid WGS84 coordinates.")


def fetch_records(page_size: int = 100) -> tuple[list[dict], dict]:
    if not 1 <= page_size <= 100:
        raise ValueError("OSM page size must be between 1 and 100.")
    records, pages = {}, []
    offset, expected_total = 0, None
    while True:
        params = {"where": NSW_FILTER, "order_by": "meta_osm_id", "limit": page_size, "offset": offset}
        payload = request_page(params)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ValueError("OSM API response must contain a results array.")
        total = payload.get("total_count")
        if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
            raise ValueError("OSM API returned an invalid or empty total_count.")
        if expected_total is None:
            expected_total = total
            if total > 10000:
                raise ValueError("OSM query exceeds the records endpoint limit; use the export endpoint.")
        if total != expected_total:
            raise ValueError("OSM dataset changed during pagination; retry the complete snapshot.")
        batch = payload["results"]
        if not batch or len(batch) > page_size or offset + len(batch) > total:
            raise ValueError("OSM pagination is incomplete or inconsistent; snapshot unchanged.")
        validate_records(batch)
        for record in batch:
            identifier = record_id(record)
            if identifier in records:
                raise ValueError("OSM pages overlap; refusing to save a potentially incomplete snapshot.")
            records[identifier] = record
        pages.append({"offset": offset, "records": len(batch)})
        offset += len(batch)
        if offset == expected_total:
            break
        time.sleep(0.2)
    values = list(records.values())
    validate_records(values)
    return values, {
        "api_endpoint": ENDPOINT, "where": NSW_FILTER, "order_by": "meta_osm_id",
        "page_size": page_size, "api_query_count": len(pages), "pages": pages,
        "reported_total_count": expected_total, "unique_records": len(values),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "attribution": "OpenStreetMap contributors; Opendatasoft public mirror",
        "licence": "ODbL", "licence_url": "https://www.openstreetmap.org/copyright",
    }


def atomic_json(path: Path, value) -> None:
    """Publish only a fully serialized snapshot; a failed request never truncates it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def snapshot(output_dir: Path = ROOT / "result_data", refresh: bool = False, page_size: int = 100) -> dict:
    target = output_dir / SNAPSHOT_NAME
    metadata_path = output_dir / METADATA_NAME
    if target.exists() and not refresh:
        records = json.loads(target.read_text(encoding="utf-8"))
        validate_records(records)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        verified = metadata.get("sha256") == digest
        return {"mode": "cache", "snapshot": str(target), "records": len(records), "sha256": digest,
                "retrieved_at_utc": metadata.get("retrieved_at_utc") if verified else None,
                "retrieval_metadata_verified": verified}
    records, metadata = fetch_records(page_size)
    atomic_json(target, records)
    metadata["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    metadata["snapshot_file"] = SNAPSHOT_NAME
    atomic_json(metadata_path, metadata)
    return {"mode": "fetched", "snapshot": str(target), **metadata}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Fetch a complete live snapshot instead of using the cache")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "result_data")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args(argv)
    print(json.dumps(snapshot(args.output_dir.resolve(), args.refresh, args.page_size), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
