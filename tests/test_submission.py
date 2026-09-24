# USYD CODE CITATION ACKNOWLEDGEMENT
# I declare that OpenAI Codex generated these submission-readiness tests
# for downloads, cleaned-data replay and database failure recovery.

"""Submission checks around the team's existing stage interfaces."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest

import duckdb
import pandas as pd
import requests

import config
from data_utils.file_utils import YFileUtils


class SourceDownloadTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.target = Path(self.folder.name) / "source.csv"

    def response(self, chunks):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = chunks
        return response

    def test_download_accepts_csv_bytes_and_uses_timeout(self):
        response = self.response([b"id,value\r\n", b"1,hello\r\n"])
        response.headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        with patch("requests.get", return_value=response) as get, redirect_stdout(StringIO()):
            YFileUtils.download_file("https://example.test/source.csv", str(self.target))
        self.assertEqual(pd.read_csv(self.target).iloc[0].to_dict(), {"id": 1, "value": "hello"})
        self.assertEqual(get.call_args.kwargs["timeout"], (15, 60))
        self.assertEqual(list(self.target.parent.glob("*.part")), [])

    def test_cached_input_is_reused_without_network(self):
        self.target.write_text("id,value\n1,kept\n")
        with patch("requests.get") as get, redirect_stdout(StringIO()):
            YFileUtils.download_file("https://example.test/source.csv", str(self.target), override=False)
        get.assert_not_called()

    def test_failed_stream_preserves_previous_file(self):
        self.target.write_bytes(b"id,value\n1,previous\n")

        def interrupted():
            yield b"id,value\n"
            raise requests.ConnectionError("interrupted download")

        with patch("requests.get", return_value=self.response(interrupted())), redirect_stdout(StringIO()):
            with self.assertRaises(requests.ConnectionError):
                YFileUtils.download_file("https://example.test/source.csv", str(self.target))
        self.assertEqual(self.target.read_bytes(), b"id,value\n1,previous\n")
        self.assertEqual(list(self.target.parent.glob("*.part")), [])

    def test_html_response_is_not_cached_as_csv(self):
        with patch("requests.get", return_value=self.response([b"<!DOCTYPE html><html>error, retry</html>"])), redirect_stdout(StringIO()):
            with self.assertRaises(ValueError):
                YFileUtils.download_file("https://example.test/source.csv", str(self.target))
        self.assertFalse(self.target.exists())

    def test_empty_cached_input_fails_explicitly(self):
        self.target.touch()
        with patch("requests.get") as get, self.assertRaises(ValueError):
            YFileUtils.download_file("https://example.test/source.csv", str(self.target), override=False)
        get.assert_not_called()

    def test_invalid_zip_cannot_replace_saved_archive(self):
        import zipfile
        target = self.target.with_suffix(".zip")
        with patch("requests.get", return_value=self.response([b"not a zip"])), redirect_stdout(StringIO()):
            with self.assertRaises(zipfile.BadZipFile):
                YFileUtils.download_file("https://example.test/source.zip", str(target))
        self.assertFalse(target.exists())


class CleaningSubmissionTests(unittest.TestCase):
    def test_source_duplicate_assessment(self):
        source = pd.read_csv(config.NSW_EV_CHARGING_SRC_FILE)
        self.assertEqual(len(source), 1958)
        self.assertEqual(int(source.duplicated().sum()), 0)
        # Coordinate coincidences do not establish duplicate station records.
        self.assertGreater(int(source.duplicated(["Latitude", "Longitude"]).sum()), 0)

    def test_required_boundary_cannot_be_silently_skipped(self):
        from pipeline.data_clean import nsw_evc_cleaner_config as cleaners
        with TemporaryDirectory() as folder, patch.object(cleaners, "AUS_ASGS_LV4_FILE", Path(folder) / "missing.zip"):
            with self.assertRaises(FileNotFoundError):
                cleaners.GET_NSW_EV_CHARGING_COLUMN_CLEANERS()

    def test_rating_and_postcode_regex(self):
        from pipeline.data_clean.nsw_evc_data_clean_utils import (
            _parse_charger_rating, charger_rating_processor, pcode_processor,
        )
        self.assertEqual(charger_rating_processor("22"), "22 kW")
        self.assertEqual(pcode_processor("NSW 2500"), "2500")
        values = _parse_charger_rating({"Charger_rating": "2x350kW + 1x50 kW", "Number_of_plugs": 3})
        self.assertEqual(values.to_dict(), {"Charger_rating.350kW": 2, "Charger_rating.50kW": 1})

    def test_clean_stage_replays_saved_output_offline(self):
        from pipeline import data_clean_script as cleaning
        with TemporaryDirectory() as folder, \
                patch.object(cleaning, "NSW_EV_CHARGING_CLEANED_FILE", Path(folder) / "clean.csv"), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("unexpected network")), \
                redirect_stdout(StringIO()):
            result = cleaning.nsw_evc_cleaning()
            replay = pd.read_csv(Path(folder) / "clean.csv")
        pd.testing.assert_frame_equal(replay, pd.read_csv(config.NSW_EV_CHARGING_CLEANED_FILE))
        self.assertEqual(result.shape, (1958, 54))
        self.assertEqual(int(result["Charger_Type"].eq("DC").sum()), 433)
        self.assertEqual(int(replay["SA4_CODE26"].isna().sum()), 1)


class DatabaseRecoveryTests(unittest.TestCase):
    def test_failed_rebuild_rolls_back_previous_database(self):
        from pipeline import data_load_script as loading
        with TemporaryDirectory() as folder:
            database = Path(folder) / "previous.duckdb"
            with duckdb.connect(str(database)) as connection:
                connection.execute("CREATE TABLE operator (operator_id INTEGER)")
                connection.execute("INSERT INTO operator VALUES (999)")
            with patch.object(loading, "DB_DATA", database), \
                    patch.object(loading, "load_parent_tables", side_effect=RuntimeError("test failure")), \
                    redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, "test failure"):
                    loading.nsw_evc_load()
            with duckdb.connect(str(database), read_only=True) as connection:
                self.assertEqual(connection.execute("SHOW TABLES").fetchall(), [("operator",)])
                self.assertEqual(connection.execute("SELECT * FROM operator").fetchall(), [(999,)])


if __name__ == "__main__":
    unittest.main()
