"""Offline regression and integration checks for the Task 2 -> Task 3 boundary."""
import hashlib
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from pipeline.data_aug.nsw_evc_aug_config import (
    Task3Config, ROOT, GET_NSW_EV_COLUMN_AUGMENTATION_CCS,
    read_task2_output, matching_input,
)
from data_utils.column_cleaner import ColumnCleaner, DFDataType
from data_utils.data_cleaner import DataCleaner
from pipeline.data_aug.multisource_matching import optional_bool
from pipeline.data_aug.provenance import fingerprint, input_paths
from pipeline.data_aug.nsw_evc_aug_utils import run_task3, preflight, validate_augmentation


class Task3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="task3-tests-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        cls.settings = replace(Task3Config(), result_dir=cls.folder / "results", output_file=cls.folder / "augmented.csv")
        cls.input_hash = hashlib.sha256(cls.settings.input_file.read_bytes()).hexdigest()
        # This path must neither rerun Task 2 nor access the live APIs.
        with patch("main.run_cleaning", side_effect=AssertionError("unexpected Task 2 run")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")), \
             patch("requests.sessions.Session.request", side_effect=AssertionError("unexpected network")):
            cls.report = run_task3(cls.settings)
        cls.source = read_task2_output(cls.settings.input_file)
        cls.augmented = pd.read_csv(cls.settings.output_file, keep_default_na=False)
        cls.audit = pd.read_csv(cls.settings.audit_file, keep_default_na=False)

    def test_regression_239_433_with_same_external_identities(self):
        self.assertEqual(self.report["dc_rows"], 433)
        self.assertEqual(self.report["accepted_rows"], 239)
        self.assertEqual(self.report["ocm_osm_only_rows"], 218)
        self.assertEqual(self.report["review_only_rows"], 83)
        self.assertEqual(self.report["quality_flag_rows"], 69)
        baseline = pd.read_csv(Task3Config().audit_file, keep_default_na=False)
        columns = ["source_index", "final_audit_status", "external_id", "augmented_attributes"]
        pd.testing.assert_frame_equal(baseline[columns], self.audit[columns])

    def test_all_task2_fields_rows_and_identifiers_preserved(self):
        self.assertEqual(len(self.augmented), 1958)
        original = pd.read_csv(self.settings.input_file, dtype=str, keep_default_na=False)
        output = pd.read_csv(self.settings.output_file, dtype=str, keep_default_na=False)
        pd.testing.assert_frame_equal(original, output[original.columns])
        self.assertEqual(hashlib.sha256(self.settings.input_file.read_bytes()).hexdigest(), self.input_hash)
        self.assertTrue(any(c.startswith("Charger_rating.") for c in output))

    def test_only_accepted_dc_rows_receive_attributes(self):
        accepted = self.augmented["augmentation_match_status"].eq("accepted")
        self.assertTrue(self.augmented.loc[accepted, "Charger_Type"].eq("DC").all())
        self.assertTrue(self.augmented.loc[~accepted, "external_attributes_json"].eq("").all())
        self.assertEqual(self.augmented.loc[accepted, "external_connector_types_normalized"].ne("").sum(), 239)

    def test_scalar_power_and_count_require_source_agreement(self):
        for _, row in self.augmented.iterrows():
            attrs = json.loads(row["external_attributes_json"] or "{}")
            for field, attribute in (
                ("external_number_of_plugs", "number_of_plugs"),
                ("external_power_kw_min", "power_kw_min"),
                ("external_power_kw_max", "power_kw_max"),
            ):
                values = {float(v) for k, v in attrs.items()
                          if k.rsplit("::", 1)[-1] == attribute and v not in (None, "") and float(v) > 0}
                if len(values) == 1:
                    self.assertEqual(float(row[field]), next(iter(values)))
                else:
                    self.assertEqual(row[field], "")

    def test_exported_json_and_numeric_formats(self):
        def reject_nonfinite(value):
            raise AssertionError(f"Nonstandard JSON constant: {value}")

        for raw in self.augmented["external_attributes_json"]:
            self.assertIsInstance(json.loads(raw or "{}", parse_constant=reject_nonfinite), dict)
        for field in ("external_number_of_plugs", "external_power_kw_min", "external_power_kw_max"):
            for value in self.augmented[field]:
                if value != "":
                    number = float(value)
                    self.assertTrue(math.isfinite(number) and number > 0)
                    if field == "external_number_of_plugs":
                        self.assertTrue(number.is_integer())

    def test_teammate_schema_recovers_postcode_audit_without_changing_file(self):
        source = self.source.drop(columns=["PCODE_ORIGINAL", "PCODE_REPAIRED_FROM_ADDRESS"], errors="ignore")
        path = self.folder / "teammate-cleaned.csv"
        source.to_csv(path, index=False)
        before = path.read_bytes()
        result = matching_input(replace(self.settings, input_file=path))
        self.assertEqual(path.read_bytes(), before)
        raw = pd.read_csv(self.settings.raw_file, dtype={"PCODE": "string"})
        expected = raw["PCODE"].str.extract(r"(\d{4})", expand=False).fillna("").rename("PCODE_ORIGINAL")
        pd.testing.assert_series_equal(result["PCODE_ORIGINAL"], expected)

    def test_raw_input_is_optional(self):
        result = matching_input(replace(self.settings, raw_file=None))
        pd.testing.assert_frame_equal(result, self.source)

    def test_stale_coordinate_or_postcode_audit_is_rejected(self):
        index = int(self.audit.iloc[0]["source_index"])
        for column, value in (("Latitude", -20.0), ("PCODE_ORIGINAL", "9999")):
            with self.subTest(column=column):
                changed = self.source.copy()
                changed.loc[index, column] = value
                with self.assertRaisesRegex(ValueError, "stale"):
                    GET_NSW_EV_COLUMN_AUGMENTATION_CCS(changed, self.settings.audit_file)

    def test_audit_dc_row_mismatch_is_rejected(self):
        changed = self.source.drop(index=int(self.audit.iloc[0]["source_index"]))
        with self.assertRaisesRegex(ValueError, "indices"):
            GET_NSW_EV_COLUMN_AUGMENTATION_CCS(changed, self.settings.audit_file)

    def test_missing_snapshot_does_not_fallback_or_write_output(self):
        settings = replace(self.settings, snapshot_dir=self.folder / "absent", output_file=self.folder / "absent.csv")
        with self.assertRaisesRegex(FileNotFoundError, "local inputs"):
            run_task3(settings)
        self.assertFalse(settings.output_file.exists())

    def test_source_overwrite_is_rejected(self):
        for name, path in input_paths(self.settings).items():
            if path is not None:
                with self.subTest(input=name), self.assertRaisesRegex(ValueError, "distinct"):
                    preflight(replace(self.settings, output_file=path))

    def test_run_manifest_binds_all_three_snapshots(self):
        inputs = self.report["input_fingerprints"]
        for key, filename in (("ocm_snapshot", "task3_ocm_tiled_snapshot.json"),
                              ("osm_snapshot", "task3_osm_nsw_snapshot_for_multisource.json"),
                              ("chargelarge_normalized", "task3_chargelarge_nsw.csv")):
            self.assertEqual(inputs[key], fingerprint(self.settings.snapshot_dir / filename))
        self.assertTrue(self.report["all_accepted_rows_have_new_attributes"])

    def test_provenance_only_json_does_not_count_as_enrichment(self):
        cleaners = GET_NSW_EV_COLUMN_AUGMENTATION_CCS(self.source, self.settings.audit_file)
        enriched = DataCleaner(cleaners, input_data_frame=self.source.copy()).clean_data()
        index = enriched.index[enriched["augmentation_match_status"].eq("accepted")][0]
        enriched.loc[index, "external_attributes_json"] = '{"OCM::data_provider":"Open Charge Map"}'
        with self.assertRaisesRegex(ValueError, "genuinely new"):
            validate_augmentation(self.source, enriched)

    def test_missing_boolean_is_not_false(self):
        self.assertIsNone(optional_bool(None))
        self.assertIsNone(optional_bool(float("nan")))
        self.assertIsNone(optional_bool("unknown"))
        self.assertIs(optional_bool("false"), False)
        self.assertIs(optional_bool("yes"), True)

    def test_shared_cleaner_supports_dataframe_and_chunk_modes(self):
        cleaner = ColumnCleaner("extra", DFDataType.STR, column_create_function=lambda df: pd.Series("ok", index=df.index))
        frame = DataCleaner([cleaner], input_data_frame=pd.DataFrame({"x": [1, 2]})).clean_data()
        self.assertIsInstance(frame, pd.DataFrame)
        self.assertEqual(frame["extra"].tolist(), ["ok", "ok"])
        src, dst = self.folder / "chunks-in.csv", self.folder / "chunks-out.csv"
        pd.DataFrame({"x": [1, 2, 3]}).to_csv(src, index=False)
        chunks = DataCleaner([cleaner], input_file_name=str(src), input_file_trunk_size=2, output_file_name=str(dst)).clean_data()
        self.assertEqual([len(c) for c in chunks], [2, 1])
        self.assertEqual(len(pd.read_csv(dst)), 3)

    def test_configs_and_entry_points_import_without_running_stages(self):
        with patch("main.run_cleaning", side_effect=AssertionError("unexpected cleaning")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("unexpected API request")):
            import importlib
            import config
            importlib.reload(config)
            self.assertTrue(callable(config.address_processor))
            self.assertTrue(callable(config.GET_NSW_EV_COLUMN_AUGMENTATION_CCS))


if __name__ == "__main__":
    unittest.main()
