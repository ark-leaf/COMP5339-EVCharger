# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that I wrote/adapted the request and CLI flow using OpenAI Codex
# references. Codex implemented or substantially revised pagination, record
# validation and atomic snapshot writing, and assisted with tests.

"""Collect the NSW OSM-derived mirror without overwriting prior snapshots.

The request and CLI flow were adapted from an AI reference by the student.
Pagination, record checks, atomic writes, and tests were completed with AI
assistance. This uses an Opendatasoft mirror, not the Overpass API.
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


ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/osm-australia-charging-station/records"
SNAPSHOT_NAME = "task3_osm_nsw_snapshot_for_multisource.json"
METADATA_NAME = "task3_osm_snapshot_metadata.json"
NSW_FILTER = "meta_name_state='New South Wales'"


# STUDENT_CORE[P8-OSM]: request_page
def request_page(params: dict, timeout: float=30, attempts: int=3) -> dict:
    if attempts < 1 or timeout <= 0:
        raise ValueError("attempts and timeout must be positive")
    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "COMP5339-EVCharger-ass1/0.1",
            "Accept": "application/json",
        },
    )

    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("OSM mirror returned a non-object response")
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"OSM mirror returned HTTP {exc.code}") from exc
            if attempt == attempts - 1:
                raise RuntimeError("OSM mirror failed after retries") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError("OSM mirror request failed") from exc

        time.sleep(2 ** attempt)

    raise RuntimeError("No OSM request was completed")


def record_id(record: dict) -> str:
    """Prefer the typed OSM URL, which distinguishes nodes from ways."""
    url = str(record.get("meta_osm_url") or "").strip()
    if url:
        return url
    value = record.get("meta_osm_id")
    if value is None or isinstance(value, bool):
        raise ValueError("OSM record has no stable identifier")
    identifier = str(value).strip()
    if not identifier:
        raise ValueError("OSM record has no stable identifier")
    return identifier


def validate_records(records: list[dict]) -> None:
    """Reject incomplete, duplicate, non-NSW, or invalid-coordinate records."""
    if not isinstance(records, list) or not records:
        raise ValueError("OSM records must be a nonempty list")
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("OSM records must contain objects")
        identifier = record_id(record)
        if identifier in seen:
            raise ValueError(f"Duplicate OSM record: {identifier}")
        seen.add(identifier)
        if record.get("meta_name_state") != "New South Wales":
            raise ValueError("OSM record is outside the NSW query")
        point = record.get("meta_geo_point") or {}
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("OSM record lacks WGS84 coordinates") from exc
        if not (math.isfinite(lat) and math.isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("OSM record has invalid WGS84 coordinates")


# AI-assisted completion of the P8 OSM pagination core.
def fetch_records(page_size: int=100) -> tuple[list[dict], dict]:
    """Fetch all pages, checking reported total and unique IDs before export."""
    if not 1 <= page_size <= 100:
        raise ValueError("OSM page_size must be between 1 and 100")

    records = {}
    pages = []
    offset = 0
    expected_total = None
    while True:
        limit = min(page_size, expected_total - offset) if expected_total else page_size
        params = {
            "where": NSW_FILTER,
            "order_by": "meta_osm_id",
            "limit": limit,
            "offset": offset,
        }
        response = request_page(params)
        batch = response.get("results")
        total = response.get("total_count")
        if not isinstance(batch, list) or isinstance(total, bool) or not isinstance(total, int):
            raise ValueError("OSM page lacks results or total_count")
        if total <= 0 or total >= 10000:
            raise ValueError("OSM result count is empty or exceeds records pagination")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError("OSM dataset changed during pagination")
        if not batch or len(batch) > limit or offset + len(batch) > total:
            raise ValueError("OSM pagination is incomplete or inconsistent")
        if len(batch) < limit and offset + len(batch) < total:
            raise ValueError("OSM page ended before reported total")

        validate_records(batch)
        for record in batch:
            identifier = record_id(record)
            if identifier in records:
                raise ValueError(f"Duplicate OSM record across pages: {identifier}")
            records[identifier] = record
        pages.append({"offset": offset, "returned": len(batch)})
        offset += len(batch)
        if offset == expected_total:
            break
        time.sleep(0.2)

    result = list(records.values())
    validate_records(result)
    return result, {
        "api_endpoint": ENDPOINT,
        "where": NSW_FILTER,
        "order_by": "meta_osm_id",
        "page_size": page_size,
        "pages": pages,
        "api_query_count": len(pages),
        "reported_total_count": expected_total,
        "unique_records": len(result),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "attribution": "OpenStreetMap contributors; Opendatasoft public mirror",
        "licence_url": "https://www.openstreetmap.org/copyright",
    }


def atomic_json(path: Path, value) -> None:
    """Publish a complete JSON file from a temporary file in the same dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


# The student supplied the cache/new-directory structure; metadata validation
# and atomic publication were added during AI-assisted review.
def snapshot(output_dir: Path=ROOT / 'result_data', refresh: bool=False, page_size: int=100) -> dict:
    output_dir = Path(output_dir)
    target = output_dir / SNAPSHOT_NAME
    meta_target = output_dir / METADATA_NAME

    if target.exists() and not refresh:
        records = json.loads(target.read_text(encoding="utf-8"))
        validate_records(records)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        metadata = json.loads(meta_target.read_text(encoding="utf-8")) if meta_target.exists() else {}
        verified = isinstance(metadata, dict) and metadata.get("sha256") == digest
        return {
            "mode": "cache", "records": len(records), "path": str(target),
            "sha256": digest, "retrieval_metadata_verified": verified,
            "retrieved_at_utc": metadata.get("retrieved_at_utc") if verified else None,
        }
    if target.exists() or meta_target.exists():
        raise FileExistsError("For refresh, choose a new --output-dir")

    records, metadata = fetch_records(page_size)
    validate_records(records)
    atomic_json(target, records)
    metadata = {
        **metadata,
        "snapshot_file": SNAPSHOT_NAME,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    try:
        atomic_json(meta_target, metadata)
    except Exception:
        # Both targets were absent before this call; do not leave a cache
        # without its retrieval metadata if publishing the second file fails.
        target.unlink(missing_ok=True)
        raise
    return {"mode": "fetched", "path": str(target), **metadata}


# STUDENT_CORE[P8-OSM]: main
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args(argv)
    result = snapshot(args.output_dir, args.refresh, args.page_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
