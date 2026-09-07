"""Download and validate the two datasets required for Task 1."""

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

EV_SOURCE_URL = (
    "https://opendata.transport.nsw.gov.au/data/dataset/"
    "be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/"
    "7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv"
)
SA4_SOURCE_URL = (
    "https://www.abs.gov.au/statistics/standards/"
    "australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/"
    "access-and-downloads/digital-boundary-files/"
    "SA4_2026_AUST_SHP_GDA2020.zip"
)

EV_OUTPUT = RAW_DIR / "ev_20251216.csv"
SA4_ARCHIVE_OUTPUT = RAW_DIR / "SA4_2026_AUST_SHP_GDA2020.zip"
SA4_EXTRACTED_DIR = RAW_DIR / "sa4_2026_gda2020"
MANIFEST_OUTPUT = METADATA_DIR / "acquisition_manifest.json"


def prepare_directories() -> None:
    """Create the local output directories required by the acquisition step."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)


def download_file(source_url: str, destination: Path, force: bool = False) -> None:
    """Download a file atomically, skipping an existing non-empty file."""
    if destination.exists() and destination.stat().st_size > 0 and not force:
        print(f"Using existing file: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with requests.get(source_url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(
                mode="wb", delete=False, dir=destination.parent
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        temporary_file.write(chunk)
        temporary_path.replace(destination)
        print(f"Downloaded: {destination}")
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def extract_sa4_archive(archive: Path, destination: Path) -> None:
    """Safely extract the ABS ZIP archive into the requested directory."""
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()

    with zipfile.ZipFile(archive) as archive_file:
        for member in archive_file.infolist():
            member_path = (destination / member.filename).resolve()
            if destination_root not in member_path.parents and member_path != destination_root:
                raise ValueError(f"Unsafe ZIP member path: {member.filename}")
        archive_file.extractall(destination)

    print(f"Extracted: {destination}")


def sha256_for_file(file_path: Path) -> str:
    """Return the SHA-256 checksum of a local file."""
    digest = hashlib.sha256()
    with file_path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_csv_rows(file_path: Path) -> int:
    """Count data rows without loading the whole CSV into memory."""
    with file_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        return sum(1 for _ in csv.reader(input_file)) - 1


def find_required_sa4_files() -> dict[str, list[str]]:
    """Find the shapefile components, including archives with nested folders."""
    required_extensions = (".shp", ".dbf", ".shx", ".prj")
    files = {}
    for extension in required_extensions:
        matches = sorted(SA4_EXTRACTED_DIR.rglob(f"*{extension}"))
        if not matches:
            raise FileNotFoundError(f"No SA4 file found with extension {extension}")
        files[extension] = [str(path.relative_to(PROJECT_ROOT)) for path in matches]
    return files


def write_manifest(ev_rows: int, sa4_files: dict[str, list[str]]) -> None:
    """Write reproducibility information for the downloaded files."""
    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "ev_charging_locations": {
                "url": EV_SOURCE_URL,
                "local_path": str(EV_OUTPUT.relative_to(PROJECT_ROOT)),
                "size_bytes": EV_OUTPUT.stat().st_size,
                "sha256": sha256_for_file(EV_OUTPUT),
                "data_rows": ev_rows,
            },
            "abs_sa4_boundaries": {
                "url": SA4_SOURCE_URL,
                "archive_path": str(SA4_ARCHIVE_OUTPUT.relative_to(PROJECT_ROOT)),
                "archive_size_bytes": SA4_ARCHIVE_OUTPUT.stat().st_size,
                "archive_sha256": sha256_for_file(SA4_ARCHIVE_OUTPUT),
                "required_files": sa4_files,
            },
        },
    }
    MANIFEST_OUTPUT.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote manifest: {MANIFEST_OUTPUT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="download the source files again even if local copies exist",
    )
    arguments = parser.parse_args()

    prepare_directories()
    download_file(EV_SOURCE_URL, EV_OUTPUT, force=arguments.force)
    download_file(SA4_SOURCE_URL, SA4_ARCHIVE_OUTPUT, force=arguments.force)
    extract_sa4_archive(SA4_ARCHIVE_OUTPUT, SA4_EXTRACTED_DIR)

    ev_rows = count_csv_rows(EV_OUTPUT)
    sa4_files = find_required_sa4_files()
    write_manifest(ev_rows, sa4_files)
    print(f"Validation complete: {ev_rows} EV data rows and SA4 components found.")


if __name__ == "__main__":
    main()
