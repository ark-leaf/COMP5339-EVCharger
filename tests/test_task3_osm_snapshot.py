"""OSM API pagination, retries, cache safety and provenance checks."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import task3_osm_snapshot as osm


def record(identifier):
    return {"meta_osm_id": identifier, "meta_name_state": "New South Wales",
            "meta_geo_point": {"lat": -33.8, "lon": 151.2}}


class OSMSnapshotTests(unittest.TestCase):
    def test_complete_pages_use_stable_order_and_offsets(self):
        pages = [{"total_count": 3, "results": [record(1), record(2)]},
                 {"total_count": 3, "results": [record(3)]}]
        with patch.object(osm, "request_page", side_effect=pages) as request, patch.object(osm.time, "sleep"):
            records, metadata = osm.fetch_records(page_size=2)
        self.assertEqual(len(records), 3)
        self.assertEqual(metadata["api_query_count"], 2)
        self.assertEqual([call.args[0]["offset"] for call in request.call_args_list], [0, 2])
        self.assertTrue(all(call.args[0]["order_by"] == "meta_osm_id" for call in request.call_args_list))

    def test_changed_total_overlapping_or_truncated_pages_fail(self):
        first = {"total_count": 3, "results": [record(1), record(2)]}
        for second in (
            {"total_count": 4, "results": [record(3)]},
            {"total_count": 3, "results": [record(2)]},
            {"total_count": 3, "results": []},
        ):
            with self.subTest(second=second), patch.object(osm, "request_page", side_effect=[first, second]), patch.object(osm.time, "sleep"):
                with self.assertRaises(ValueError):
                    osm.fetch_records(page_size=2)

    def test_invalid_schema_empty_result_and_non_nsw_rows_fail(self):
        for payload in ({"results": []}, {"total_count": 0, "results": []},
                        {"total_count": 1, "results": [{**record(1), "meta_name_state": "Victoria"}]}):
            with self.subTest(payload=payload), patch.object(osm, "request_page", return_value=payload):
                with self.assertRaises(ValueError):
                    osm.fetch_records()

    def test_transient_request_retries_but_client_errors_do_not(self):
        payload = {"total_count": 1, "results": [record(1)]}
        busy = urllib.error.HTTPError("https://example.invalid", 503, "busy", {}, None)
        with patch.object(osm.urllib.request, "urlopen", side_effect=[busy, io.BytesIO(json.dumps(payload).encode())]) as request, patch.object(osm.time, "sleep") as sleep:
            self.assertEqual(osm.request_page({"limit": 1}), payload)
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once()
        denied = urllib.error.HTTPError("https://example.invalid", 403, "denied", {}, None)
        with patch.object(osm.urllib.request, "urlopen", side_effect=denied) as request:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                osm.request_page({"limit": 1})
            self.assertEqual(request.call_count, 1)

    def test_failed_refresh_preserves_existing_snapshot_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path, metadata = folder / osm.SNAPSHOT_NAME, folder / osm.METADATA_NAME
            path.write_text(json.dumps([record(1)]))
            metadata.write_text('{"old":true}')
            before = (path.read_bytes(), metadata.read_bytes())
            with patch.object(osm, "fetch_records", side_effect=RuntimeError("unavailable")):
                with self.assertRaises(RuntimeError):
                    osm.snapshot(folder, refresh=True)
            self.assertEqual((path.read_bytes(), metadata.read_bytes()), before)

    def test_cache_does_not_query_or_invent_retrieval_time(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = folder / osm.SNAPSHOT_NAME
            path.write_text(json.dumps([record(1)]))
            before = path.read_bytes()
            with patch.object(osm, "request_page", side_effect=AssertionError("unexpected API call")):
                result = osm.snapshot(folder)
            self.assertEqual(result["mode"], "cache")
            self.assertIsNone(result["retrieved_at_utc"])
            self.assertEqual(path.read_bytes(), before)

    def test_successful_refresh_writes_hash_bound_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with patch.object(osm, "request_page", return_value={"total_count": 1, "results": [record(1)]}):
                fresh = osm.snapshot(folder, refresh=True)
            cached = osm.snapshot(folder)
            self.assertEqual(fresh["sha256"], cached["sha256"])
            self.assertEqual(fresh["retrieved_at_utc"], cached["retrieved_at_utc"])
            self.assertTrue(cached["retrieval_metadata_verified"])


if __name__ == "__main__":
    unittest.main()
