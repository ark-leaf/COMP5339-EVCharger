"""Run and validate Task 3 using the team's cleaned CSV and cleaner interfaces."""
from __future__ import annotations

import argparse
import json
import math
import platform
from importlib.metadata import version
from dataclasses import replace
from pathlib import Path

import pandas as pd

from pipeline.data_aug.nsw_evc_aug_config import (
    Task3Config, GET_NSW_EV_COLUMN_AUGMENTATION_CCS, read_task2_output, display_path,
)
from data_utils.csv_file_helper import CsvFileHelper
from data_utils.data_cleaner import DataCleaner
from pipeline.data_aug.multisource_matching import run_matching
from pipeline.data_aug.multisource_audit import run_audit, new_attribute_count
from pipeline.data_aug.provenance import input_fingerprints, input_paths, fingerprint, snapshot_metadata


# P7 validation follows an AI-provided reference reviewed with the student.
def validate_augmentation(source: pd.DataFrame, augmented: pd.DataFrame) -> dict:
    """Check that Task 3 added valid DC attributes without changing Task 2 data."""
    if not source.index.is_unique or not augmented.index.is_unique:
        raise ValueError("Task 3 source row indices must be unique")
    if not source.columns.is_unique or not augmented.columns.is_unique:
        raise ValueError("Task 3 column names must be unique")

    if len(source) != len(augmented) or not source.index.equals(augmented.index):
        raise ValueError("Task 3 changed the source row count or order")

    if list(augmented.columns[:len(source.columns)]) != list(source.columns):
        raise ValueError("Task 3 changed the source column order")

    try:
        pd.testing.assert_frame_equal(source, augmented[source.columns])
    except AssertionError as exc:
        raise ValueError("Task 3 changed an original Task 2 value") from exc

    required_columns = {
        "augmentation_match_status",
        "external_attributes_json",
        "augmentation_quality_review",
    }
    missing = required_columns - set(augmented.columns)
    if missing:
        raise ValueError(f"Missing augmentation columns: {sorted(missing)}")

    dc = (
        source["Charger_Type"]
        .astype("string")
        .str.strip()
        .str.upper()
        .eq("DC")
        .fillna(False)
    )
    dc_count = int(dc.sum())
    if dc_count == 0:
        raise ValueError("No DC rows to validate")

    status = augmented["augmentation_match_status"].astype("string").fillna("")
    if not status[dc].isin({"accepted", "review", "unmatched"}).all():
        raise ValueError("A DC row has an invalid match status")
    if status[~dc].ne("not_applicable").any():
        raise ValueError("A non-DC row has an incorrect match status")

    accepted = status.eq("accepted")
    attributes = (
        augmented["external_attributes_json"]
        .astype("string")
        .fillna("")
        .str.strip()
    )

    # Unaccepted rows must not expose confirmed external data.
    for column in (c for c in augmented.columns if c.startswith("external_")):
        values = augmented.loc[~accepted, column]
        has_value = (
            values.notna()
            & values.astype("string").fillna("").str.strip().ne("")
        )
        if has_value.any():
            raise ValueError(f"Unaccepted row contains {column}")

    quality = (
        augmented["augmentation_quality_review"]
        .astype("string")
        .fillna("")
        .str.strip()
    )
    if quality[~accepted].ne("").any():
        raise ValueError("Quality review flag appears on an unaccepted row")
    if not quality[accepted].isin({"yes", "no"}).all():
        raise ValueError("Accepted row has an invalid quality review flag")

    for source_index, raw in attributes[accepted].items():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid external attributes at row {source_index}"
            ) from exc

        if not isinstance(data, dict) or new_attribute_count(data) == 0:
            raise ValueError(
                f"Accepted row {source_index} has no genuinely new attribute"
            )

    accepted_count = int(accepted.sum())
    for column in ("external_power_kw_min", "external_power_kw_max",
                   "external_dc_port_count", "external_number_of_plugs"):
        if column not in augmented:
            continue
        raw = augmented[column].dropna()
        values = pd.to_numeric(raw, errors="coerce")
        if values.isna().any() or not values.map(math.isfinite).all() or values.le(0).any():
            raise ValueError(f"Invalid positive quantity: {column}")
        if column.endswith(("count", "plugs")) and not values.mod(1).eq(0).all():
            raise ValueError(f"Non-integral port count: {column}")
    required_count = math.ceil(dc_count * 0.5)
    if accepted_count < required_count:
        raise ValueError(
            f"DC coverage is too low: {accepted_count}/{dc_count}; "
            f"at least {required_count} required"
        )

    return {
        "input_rows": len(source),
        "dc_rows": dc_count,
        "input_columns": list(source.columns),
        "output_columns": list(augmented.columns),
        "accepted_rows": accepted_count,
        "accepted_coverage": accepted_count / dc_count,
        "required_rows": required_count,
        "source_columns_unchanged": True,
        "unaccepted_attributes_blank": True,
        "all_accepted_rows_have_new_attributes": True,
    }


def preflight(settings: Task3Config) -> None:
    required = [settings.input_file, settings.boundary_file] + [
        settings.snapshot_dir / name for name in (
            "task3_ocm_tiled_snapshot.json", "task3_osm_nsw_snapshot_for_multisource.json",
            "task3_chargelarge_raw.json",
        )
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Task 3 requires local inputs (refresh separately): " + ", ".join(missing))
    for snapshot_name, metadata_name in (
        ("task3_ocm_tiled_snapshot.json", "task3_ocm_tiled_snapshot_metadata.json"),
        ("task3_osm_nsw_snapshot_for_multisource.json", "task3_osm_snapshot_metadata.json"),
        ("task3_chargelarge_raw.json", "task3_chargelarge_metadata.json"),
    ):
        evidence = snapshot_metadata(settings.snapshot_dir / snapshot_name,
                                     settings.snapshot_dir / metadata_name)
        if evidence["retrieval_metadata_hash_verified"] is False:
            raise ValueError(f"Snapshot checksum mismatch: {snapshot_name}")
        if evidence.get("reported_count_matches_snapshot") is False:
            raise ValueError(f"Snapshot record count mismatch: {snapshot_name}")
    outputs = [settings.output_file, settings.matches_file, settings.audit_file,
               settings.result_dir / "task3_multisource_summary.json"]
    outputs += [settings.audit_dir / name for name in (
        "task3_multisource_final_audit_summary.json", "task3_multisource_manual_review_queue.csv",
        "task3_multisource_accepted_quality_flags.csv", "task3_duplicate_external_id_report.csv",
        "task3_source_manifest.json", "task3_run_manifest.json",
    )]
    inputs = {p.resolve() for p in input_paths(settings).values() if p is not None}
    if any(p.resolve() in inputs for p in outputs) or len({p.resolve() for p in outputs}) != len(outputs):
        raise ValueError("Task 3 output paths must be distinct from each other and all source inputs.")


def augment_dataframe(source: pd.DataFrame, settings: Task3Config) -> pd.DataFrame:
    """Apply the team's reserved cleaners without writing until validation passes."""
    cleaners = GET_NSW_EV_COLUMN_AUGMENTATION_CCS(source, settings.audit_file)
    augmented = DataCleaner(cleaners, input_data_frame=source.copy(deep=True)).clean_data()
    validate_augmentation(source, augmented)
    return augmented


def run_task3(settings: Task3Config = Task3Config()) -> dict:
    preflight(settings)
    source = read_task2_output(settings.input_file)
    fingerprints = input_fingerprints(settings)
    input_hash = fingerprints["task2_cleaned"]["sha256"]
    run_matching(settings)
    audit_summary = run_audit(settings)
    # Shared team interface; validate in memory before writing the final CSV.
    augmented = augment_dataframe(source, settings)
    validation = validate_augmentation(source, augmented)
    if input_fingerprints(settings) != fingerprints:
        raise ValueError("A Task 3 input changed during processing; rerun with stable inputs.")
    CsvFileHelper(str(settings.input_file), str(settings.output_file)).write_file(augmented)
    # Re-read the final artifact to check that text identifiers survived CSV IO.
    written = pd.read_csv(settings.output_file, dtype={
        "PCODE": "string", "PCODE_ORIGINAL": "string", "SA4_CODE26": "string",
    })
    pd.testing.assert_frame_equal(source, written[source.columns], check_dtype=False,
                                  check_exact=False, rtol=1e-12, atol=1e-12)
    for column in ("PCODE", "PCODE_ORIGINAL", "SA4_CODE26"):
        if column in source and not source[column].fillna("").equals(written[column].fillna("")):
            raise ValueError(f"Task 3 CSV changed identifier {column}.")
    manifest = {
        **validation,
        "input_file": display_path(settings.input_file),
        "input_sha256": input_hash,
        "output_file": display_path(settings.output_file),
        "audit_file": display_path(settings.audit_file),
        "review_only_rows": audit_summary["manual_review_only_rows"],
        "quality_flag_rows": audit_summary["accepted_quality_flag_rows"],
        "ocm_osm_only_rows": audit_summary["ocm_osm_only_union_rows"],
        "assignment_check": audit_summary["assignment_check"],
        "execution": "offline snapshots; no Task 2 rerun; no automatic OCM-only fallback",
        "teammate_base_commit": "874eb5b",
        "entry_point": "pipeline.data_aug_script",
        "input_fingerprints": fingerprints,
        "output_fingerprint": fingerprint(settings.output_file),
        "runtime": {"python": platform.python_version(), "packages": {
            name: version(name) for name in ("numpy", "pandas", "geopandas", "shapely", "pyogrio", "pyproj", "requests")
        }},
    }
    manifest_file = settings.audit_dir / "task3_run_manifest.json"
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Task 2 cleaned CSV")
    parser.add_argument("--output", type=Path, help="Final augmented CSV")
    parser.add_argument("--results-dir", type=Path, help="Matching/audit output directory")
    parser.add_argument("--snapshot-dir", type=Path, help="Directory containing all three local source snapshots")
    args = parser.parse_args(argv)
    changes = {field: value.resolve() for field, value in (
        ("input_file", args.input), ("output_file", args.output), ("result_dir", args.results_dir),
        ("snapshot_dir", args.snapshot_dir),
    ) if value is not None}
    result = run_task3(replace(Task3Config(), **changes))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
