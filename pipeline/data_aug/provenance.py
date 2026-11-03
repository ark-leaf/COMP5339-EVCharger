# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex generated or substantially revised the
# snapshot fingerprinting and metadata-validation logic in this file.

"""Content fingerprints for the inputs used by one Task 3 run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline.data_aug.nsw_evc_aug_config import Task3Config, display_path

SNAPSHOT_FILES = {
    "ocm": ("OCM", "task3_ocm_tiled_snapshot.json", "task3_ocm_tiled_snapshot_metadata.json"),
    "osm": ("OSM-derived", "task3_osm_nsw_snapshot_for_multisource.json", "task3_osm_snapshot_metadata.json"),
    "chargelarge": ("Charge@Large", "task3_chargelarge_raw.json", "task3_chargelarge_metadata.json"),
}


def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": display_path(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def input_paths(settings: Task3Config) -> dict[str, Path | None]:
    """Include optional evidence so outputs cannot overwrite it either."""
    paths = {
        "task2_cleaned": settings.input_file,
        "nsw_boundary": settings.boundary_file,
        "chargelarge_historical_query": settings.snapshot_dir / "task3_chargelarge_summary.json",
        "tfnsw_raw_provenance": settings.raw_file,
        "task2_geocoding_cache": settings.task2_geocoding_cache,
        "ocm_web_notes": settings.web_review_dir / "task3_ocm_125_web_confidence.csv",
        "supplemental_web_notes": settings.web_review_dir / "task3_104_non_ocm_web_verified.csv",
    }
    for prefix, (_, snapshot, metadata) in SNAPSHOT_FILES.items():
        key = "chargelarge_raw" if prefix == "chargelarge" else f"{prefix}_snapshot"
        paths[key] = settings.snapshot_dir / snapshot
        paths[f"{prefix}_metadata"] = settings.snapshot_dir / metadata
    return paths


def input_fingerprints(settings: Task3Config) -> dict:
    return {key: fingerprint(path) if path is not None and path.is_file() else None
            for key, path in input_paths(settings).items()}


def snapshot_metadata(snapshot: Path, metadata_file: Path | None = None) -> dict:
    """Retain unknown retrieval times; never use filesystem time as API evidence."""
    result = {"snapshot_fingerprint": fingerprint(snapshot), "retrieved_at_utc": None,
              "retrieval_metadata_hash_verified": None}
    if metadata_file and metadata_file.is_file():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        checksum = metadata.get("sha256")
        verified = checksum == result["snapshot_fingerprint"]["sha256"] if checksum else None
        result["retrieval_metadata_hash_verified"] = verified
        result["retrieved_at_utc"] = metadata.get("retrieved_at_utc") if verified is not False else None
        result["retrieval_metadata_file"] = display_path(metadata_file)
        result["retrieval_metadata_fingerprint"] = fingerprint(metadata_file)
        reported_count = next((metadata[key] for key in (
            "unique_records", "unique_merged_record_count", "raw_record_count"
        ) if key in metadata), None)
        if reported_count is not None:
            result["reported_record_count"] = reported_count
            result["reported_count_matches_snapshot"] = reported_count == len(json.loads(snapshot.read_text()))
        result["metadata_status"] = (
            "checksum_verified" if verified else "checksum_mismatch" if verified is False
            else "historical_query_record_without_original_checksum"
        )
    return result
