"""Run Task 3 independently from an already completed Task 2 CSV."""
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
from pipeline.data_aug.provenance import input_fingerprints, input_paths
from pipeline.data_aug.ocm_reference import get_ocm_details


def validate_augmentation(source: pd.DataFrame, augmented: pd.DataFrame) -> dict:
    if len(source) != len(augmented) or not source.index.equals(augmented.index):
        raise ValueError("Task 3 changed the Task 2 row count/order.")
    pd.testing.assert_frame_equal(source, augmented[source.columns])
    dc = source["Charger_Type"].astype("string").str.strip().str.upper().eq("DC")
    accepted = augmented["augmentation_match_status"].eq("accepted")
    if (accepted & ~dc).any():
        raise ValueError("Task 3 accepted a non-DC row.")
    attrs = augmented["external_attributes_json"].fillna("")
    if attrs[~accepted].ne("").any():
        raise ValueError("An unaccepted row exported external attributes.")
    if any(new_attribute_count(json.loads(value or "{}")) == 0 for value in attrs[accepted]):
        raise ValueError("An accepted row has no genuinely new external attribute.")
    required = math.ceil(int(dc.sum()) / 2)
    if int(accepted.sum()) < required:
        raise ValueError("Task 3 does not meet the 50% DC enrichment target.")
    if (augmented["augmentation_quality_review"] & ~accepted).any():
        raise ValueError("Quality flags must refer to accepted rows.")
    return {
        "input_rows": len(source), "dc_rows": int(dc.sum()),
        "input_columns": len(source.columns), "output_columns": len(augmented.columns),
        "accepted_rows": int(accepted.sum()),
        "accepted_coverage": float(accepted.sum() / dc.sum()),
        "required_rows": required, "source_columns_unchanged": True,
        "unaccepted_attributes_blank": True,
        "all_accepted_rows_have_new_attributes": True,
    }


def preflight(settings: Task3Config) -> None:
    required = [settings.input_file, settings.boundary_file] + [
        settings.snapshot_dir / name for name in (
            "task3_ocm_tiled_snapshot.json", "task3_osm_nsw_snapshot_for_multisource.json",
            "task3_chargelarge_nsw.csv",
        )
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Task 3 requires local inputs (refresh separately): " + ", ".join(missing))
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
        "teammate_base_commit": "299b876",
        "entry_point": "pipeline.data_aug_script",
        "input_fingerprints": fingerprints,
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
