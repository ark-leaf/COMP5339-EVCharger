"""Content fingerprints for the inputs used by one Task 3 run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from data_augmentation_config import Task3Config, display_path


def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": display_path(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def input_paths(settings: Task3Config) -> dict[str, Path | None]:
    """Include optional evidence so outputs cannot overwrite it either."""
    return {
        "task2_cleaned": settings.input_file,
        "nsw_boundary": settings.boundary_file,
        "ocm_snapshot": settings.snapshot_dir / "task3_ocm_tiled_snapshot.json",
        "ocm_metadata": settings.snapshot_dir / "task3_ocm_tiled_snapshot_metadata.json",
        "osm_snapshot": settings.snapshot_dir / "task3_osm_nsw_snapshot_for_multisource.json",
        "osm_metadata": settings.snapshot_dir / "task3_osm_snapshot_metadata.json",
        "chargelarge_normalized": settings.snapshot_dir / "task3_chargelarge_nsw.csv",
        "chargelarge_raw": settings.snapshot_dir / "task3_chargelarge_raw.json",
        "tfnsw_raw_provenance": settings.raw_file,
        "ocm_web_notes": settings.web_review_dir / "task3_ocm_125_web_confidence.csv",
        "supplemental_web_notes": settings.web_review_dir / "task3_104_non_ocm_web_verified.csv",
    }


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
    return result
