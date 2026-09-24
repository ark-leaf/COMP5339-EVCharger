# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex generated and revised the stage-interface,
# pipeline migration and cached-input regression tests in this file.

"""New team layout, stage boundaries and cached Task 2 integration contracts."""
import ast
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import config
from data_utils.address_enricher import AddressEnricher
from data_utils.data_cleaner import DataCleaner
from pipeline.data_aug.nsw_evc_aug_config import Task3Config, matching_input
from pipeline.data_aug.nsw_evc_aug_utils import run_task3


class MigrationTests(unittest.TestCase):
    def test_reserved_team_interfaces_share_one_implementation(self):
        from pipeline.data_aug.nsw_evc_aug_config import (
            GET_NSW_EV_COLUMN_AUGMENTATION_CCS,
            GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE,
        )
        self.assertIs(GET_NSW_EV_COLUMN_AUGMENTATION_CCS,
                      GET_NSW_EV_COLUMN_AUGMENTATION_MULTISOURCE)

    def test_main_uses_team_stage_functions(self):
        import main
        with patch("pipeline.data_clean_script.nsw_evc_cleaning") as clean, \
             patch("pipeline.data_aug_script.nsw_evc_augmentation") as augment, \
             patch("pipeline.data_load_script.nsw_evc_load") as load:
            main.main(["--stage", "augment"])
            clean.assert_not_called()
            augment.assert_called_once_with()
            augment.reset_mock()
            main.main(["--stage", "all"])
            clean.assert_called_once_with()
            augment.assert_called_once_with()
            load.assert_called_once_with()

    def test_entry_returns_dataframe_without_loading_task2(self):
        from pipeline.data_aug_script import nsw_evc_augmentation
        expected = pd.DataFrame({"PCODE": pd.Series(["0123"], dtype="string")})
        with patch("pipeline.data_aug_script.run_task3") as run, \
             patch("pandas.read_csv", return_value=expected):
            run.return_value = {"accepted_rows": 1, "dc_rows": 2, "accepted_coverage": 0.5}
            self.assertIs(nsw_evc_augmentation(), expected)
            run.assert_called_once()

    def test_configs_import_without_network_or_stage_execution(self):
        with patch("requests.sessions.Session.request", side_effect=AssertionError("network")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            for name in ("config", "pipeline.data_clean.nsw_evc_cleaner_config",
                         "pipeline.data_aug.nsw_evc_aug_config", "pipeline.data_aug_script"):
                importlib.import_module(name)

    def test_task3_defaults_follow_central_paths(self):
        settings = Task3Config()
        self.assertEqual(settings.input_file, Path(config.NSW_EV_CHARGING_CLEANED_FILE))
        self.assertEqual(settings.output_file, Path(config.NSW_EV_CHARGING_AUG_FILE))
        self.assertTrue(settings.input_file.is_absolute())

    def test_no_literal_ocm_key_in_central_config(self):
        tree = ast.parse((config.PROJECT_ROOT / "config.py").read_text())
        assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "OCM_API_KEY" for t in n.targets)]
        self.assertEqual(len(assignments), 1)
        self.assertNotIsInstance(assignments[0].value, ast.Constant)

    def test_shared_cleaner_file_without_explicit_chunk_size(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/"in.csv", Path(folder)/"out.csv"
            pd.DataFrame({"value": [1,2]}).to_csv(source,index=False)
            frames = list(DataCleaner([], input_file_name=str(source), output_file_name=str(output)).clean_data())
            self.assertEqual(len(frames),1)
            self.assertEqual(pd.read_csv(output)["value"].tolist(), [1,2])

    def test_new_task2_addresses_are_used_without_modifying_input(self):
        settings = Task3Config()
        before = settings.input_file.read_bytes()
        frame = matching_input(settings)
        self.assertEqual(settings.input_file.read_bytes(),before)
        self.assertIn("PCODE_ORIGINAL",frame.columns)
        self.assertEqual(frame["Charger_Type"].eq("DC").sum(),433)


class GeocodingCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "geocoding.json"

    def enricher(self, online=False):
        return AddressEnricher(config.NOMINATIM_URL, config.GOOGLE_GEOCODING_URL,
                               cache_file=self.path, allow_network=online)

    def test_success_is_cached_and_replayed_offline(self):
        response = Mock(status_code=200)
        response.json.return_value = {"address": {"house_number":"10", "road":"Test Road",
                                                  "suburb":"Sydney", "state":"NSW", "postcode":"2000"}}
        with patch("requests.get",return_value=response) as get:
            value = self.enricher(True).get_address(151.2,-33.8)
            self.assertEqual(get.call_count,1)
        with patch("requests.get",side_effect=AssertionError("network")):
            self.assertEqual(self.enricher().get_address(151.2,-33.8),value)
        self.assertEqual(len(json.loads(self.path.read_text())),1)

    def test_missing_cache_fails_closed_without_network(self):
        with patch("requests.get",side_effect=AssertionError("network")):
            with self.assertRaisesRegex(RuntimeError,"Missing Task 2"):
                self.enricher().get_address(151.2,-33.8)

    def test_http_failure_does_not_create_empty_success_cache(self):
        with patch("requests.get",return_value=Mock(status_code=403)):
            with self.assertRaisesRegex(RuntimeError,"HTTP 403"):
                self.enricher(True).get_address(151.2,-33.8)
        self.assertFalse(self.path.exists())

    def test_invalid_coordinates_never_query(self):
        with patch("requests.get",side_effect=AssertionError("network")):
            self.assertEqual(self.enricher(True).get_address(181,-33.8),"")

    def test_network_error_stops_instead_of_silently_changing_output(self):
        with patch("requests.get",side_effect=requests.exceptions.ConnectionError("offline")):
            with self.assertRaisesRegex(RuntimeError,"request failed"):
                self.enricher(True).get_address(151.2,-33.8)
        self.assertFalse(self.path.exists())
