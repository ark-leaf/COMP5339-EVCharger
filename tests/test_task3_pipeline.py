"""Task 3 business rules, source collection and full snapshot replay tests."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
import json
import os
import re
import unittest
import urllib.error
from unittest.mock import patch

import pandas as pd
import task3_ocm_tiled_snapshot as ocm_snapshot
import task3_osm_snapshot as osm_snapshot
import task3_chargelarge_snapshot as chargelarge_snapshot

from data_utils.data_cleaner import DataCleaner
from pipeline.data_aug.nsw_evc_aug_config import (
    Task3Config, GET_NSW_EV_COLUMN_AUGMENTATION_CCS,
    matching_input,
    read_task2_output,
)
from pipeline.data_aug.multisource_matching import (
    as_positive_count,
    load_chargelarge_candidates,
    load_ocm_candidates,
    load_osm_candidate_records,
    normalised_connectors,
    optional_bool,
    power_attributes,
    power_values,
    run_matching,
    resolve_reused_ids,
    source_row_candidates,
)
from pipeline.data_aug import charging_match_rules as relaxed
from pipeline.data_aug.multisource_audit import (
    SOURCE_CONFIG, duplicate_external_id_rows, identifier,
    new_attribute_count, run_audit,
)
from pipeline.data_aug.nsw_evc_aug_utils import run_task3, validate_augmentation, preflight
from pipeline.data_aug.provenance import snapshot_metadata


class Task3StudentTests(unittest.TestCase):
    @staticmethod
    def _sample_rows() -> pd.DataFrame:
        return pd.DataFrame({
            "Station_name": ["First", "Second", "Third"],
            "Station_address": ["1 Main St", "2 Main St", "3 Side Rd"],
            "Operator": ["Example", "Example", "Other"],
            "Number_of_plugs": [2, 2, 1],
            "Charger_Type": ["DC", "DC", "AC"],
            "Charger_rating": ["50 kW", "50 kW", "7 kW"],
            "Latitude": [-33.0, -33.0, -34.0],
            "Longitude": [151.0, 151.0, 150.0],
            "LGANAME": ["Example LGA"] * 3,
            "PCODE": ["0200", "0201", "0210"],
            "Source": ["TfNSW"] * 3,
        })

    @staticmethod
    def _simple_match_rules():
        """Isolate P4 selection from the separately implemented P3 module."""
        def distance_metres(lat_a, lon_a, lat_b, lon_b):
            return abs(float(lat_a) - float(lat_b)) * 111_000

        def address_parts(address, postcode_value=""):
            text = re.sub(r"[^a-z0-9]+", " ", str(address or "").lower()).strip()
            parts = text.split()
            return {
                "normalised": text,
                "house_number": parts[0] if parts and parts[0].isdigit() else "",
                "postcode": str(postcode_value or ""),
                "street_core": text,
            }

        def address_score(source, candidate):
            return float(
                bool(source["normalised"])
                and source["normalised"] == candidate["normalised"]
            )

        def address_accepted(source, candidate, score):
            return score >= 0.85

        return patch.multiple(
            relaxed,
            distance_metres=distance_metres,
            address_parts=address_parts,
            address_score=address_score,
            address_accepted=address_accepted,
        )

    def test_task2_input_contract(self):
        """Preserve source rows and reject missing fields or invalid DC coordinates."""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "cleaned.csv"
            rows = self._sample_rows()
            rows.to_csv(path, index=False)

            result = read_task2_output(path)
            self.assertEqual(len(result), 3)
            self.assertEqual(result.index.tolist(), [0, 1, 2])
            self.assertEqual(result["PCODE"].tolist(), ["0200", "0201", "0210"])
            self.assertEqual(result["Charger_Type"].tolist(), ["DC", "DC", "AC"])

            with self.assertRaises(FileNotFoundError):
                read_task2_output(Path(folder) / "missing.csv")

            rows.drop(columns="Station_address").to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Station_address"):
                read_task2_output(path)

            rows.iloc[:0].to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "empty"):
                read_task2_output(path)

            rows.assign(Charger_Type="AC").to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "no DC"):
                read_task2_output(path)

            invalid = rows.copy()
            invalid.loc[0, "Latitude"] = 100.0
            invalid.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Invalid DC coordinates"):
                read_task2_output(path)

            missing_coordinate = rows.copy()
            missing_coordinate.loc[1, "Longitude"] = float("nan")
            missing_coordinate.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Invalid DC coordinates"):
                read_task2_output(path)

    def test_matching_input_provenance(self):
        """Reject reordered raw data and leave ambiguous raw postcodes unknown."""
        with TemporaryDirectory() as folder:
            cleaned_path = Path(folder) / "cleaned.csv"
            raw_path = Path(folder) / "raw.csv"
            cleaned = self._sample_rows()
            raw = cleaned.copy()
            raw["PCODE"] = ["0300", "0301", "0310"]
            cleaned.to_csv(cleaned_path, index=False)
            raw.to_csv(raw_path, index=False)
            settings = replace(
                Task3Config(), input_file=cleaned_path, raw_file=raw_path
            )

            matched = matching_input(settings)
            self.assertEqual(matched["PCODE"].tolist(), ["0200", "0201", "0210"])
            self.assertTrue(pd.isna(matched.loc[0, "PCODE_ORIGINAL"]))
            self.assertTrue(pd.isna(matched.loc[1, "PCODE_ORIGINAL"]))
            self.assertEqual(matched.loc[2, "PCODE_ORIGINAL"], "0310")

            raw.iloc[:2].to_csv(raw_path, index=False)
            with self.assertRaisesRegex(ValueError, "row counts"):
                matching_input(settings)

            raw.iloc[::-1].to_csv(raw_path, index=False)
            with self.assertRaisesRegex(ValueError, "row order"):
                matching_input(settings)

            no_raw_file = replace(settings, raw_file=None)
            self.assertNotIn(
                "PCODE_ORIGINAL", matching_input(no_raw_file).columns
            )

    def test_distance_units_and_invalid_coordinates(self):
        """P3: independent distance reference, metre units and invalid coordinates."""
        self.assertEqual(relaxed.distance_metres(-33.0, 151.0, -33.0, 151.0), 0.0)
        self.assertAlmostEqual(
            relaxed.distance_metres(0, 0, 1, 0), 111_195, delta=1
        )
        self.assertAlmostEqual(
            relaxed.distance_metres(-33.0, 151.0, -33.0, 151.001),
            93.3, delta=0.5,
        )
        for invalid in (None, float("nan"), float("inf"), True, 91):
            self.assertEqual(
                relaxed.distance_metres(invalid, 151.0, -33.0, 151.0),
                float("inf"),
            )

    def test_address_evidence(self):
        """P3: equivalent spelling, missing components and explicit conflicts."""
        source = relaxed.address_parts("152 Pacific Highway, Swansea NSW 2281")
        equivalent = relaxed.address_parts("152 Pacific Hwy, Swansea NSW 2281")
        self.assertEqual(source["house_number"], "152")
        self.assertEqual(source["street_core"], "pacific hwy")
        self.assertEqual(source["postcode"], "2281")
        self.assertEqual(relaxed.address_score(source, equivalent), 1.0)
        self.assertTrue(relaxed.address_accepted(source, equivalent, 1.0))

        wrong_house = relaxed.address_parts("153 Pacific Hwy, Swansea NSW 2281")
        wrong_postcode = relaxed.address_parts("152 Pacific Hwy, Swansea NSW 2282")
        for candidate in (wrong_house, wrong_postcode):
            self.assertFalse(relaxed.address_accepted(
                source, candidate, relaxed.address_score(source, candidate)
            ))

        repaired = relaxed.address_parts(
            "50 Bathurst Street, Brewarrina NSW 2839", "2390"
        )
        self.assertEqual(repaired["postcode"], "2839")
        self.assertEqual(
            relaxed.address_parts("Unit 2, 1 - 7 Ross Street NSW 2000")["house_number"],
            "1-7",
        )
        self.assertEqual(relaxed.address_parts(pd.NA)["normalised"], "")
        street_only = relaxed.address_parts("Lake Haven Drive, Lake Haven NSW 2263")
        street_only_short = relaxed.address_parts("Lake Haven Dr, Lake Haven NSW 2263")
        score = relaxed.address_score(street_only, street_only_short)
        self.assertTrue(relaxed.address_accepted(
            street_only, street_only_short, score
        ))
        self.assertEqual(street_only["house_number"], "")

    def test_coordinate_acceptance_retains_address_warnings(self):
        """A coordinate match is accepted while address doubts remain visible."""
        source = pd.DataFrame([{
            "Station_address": "Lake Haven Drive, Lake Haven NSW 2263",
            "Operator": "Example", "PCODE": "2263",
            "Latitude": -33.2400, "Longitude": 151.5000,
        }])
        candidate = {
            "id": "street-level", "source": "Test", "fast_dc": True,
            "latitude": -33.2403, "longitude": 151.5000,
            "address": "Lake Haven Dr, Lake Haven NSW 2263",
            "postcode": "2263", "operator": "", "station_name": "Centre",
            "attributes": {"is_operational": True},
        }
        result = source_row_candidates(source, [candidate])
        self.assertEqual(result.loc[0, "match_method"], "coordinate_and_fuzzy_address")
        self.assertEqual(result.loc[0, "match_status"], "accepted")
        self.assertIn("street-level", result.loc[0, "match_quality_flags"])
        self.assertEqual(result.loc[0, "review_reason"], "")

        source.loc[0, "Station_address"] = "152 Pacific Highway, Swansea NSW 2281"
        source.loc[0, "PCODE"] = "2281"
        candidate["address"] = "152 Pacific Hwy, Swansea NSW 2281"
        candidate["postcode"] = "2281"
        exact = source_row_candidates(source, [candidate])
        self.assertEqual(exact.loc[0, "match_status"], "accepted")

        candidate["address"] = "153 Pacific Hwy, Swansea NSW 2281"
        conflicting = source_row_candidates(source, [candidate])
        self.assertEqual(conflicting.loc[0, "match_status"], "review")
        self.assertIn("house numbers conflict", conflicting.loc[0, "review_reason"])

    def test_power_count_connector_semantics(self):
        """P2: reject ambiguous counts and retain power and connector meanings."""
        self.assertEqual(as_positive_count("2.0"), 2)
        self.assertIsNone(as_positive_count(True))
        self.assertIsNone(as_positive_count(2.5))
        self.assertIsNone(as_positive_count(350))
        self.assertIsNone(optional_bool(None))
        self.assertIs(optional_bool("false"), False)
        self.assertEqual(power_values("500 W; 50 kW; 0.15 MW"), [0.5, 50.0, 150.0])
        self.assertEqual(power_values("-50 kW; 0 kW; 22 kW"), [22.0])
        self.assertEqual(power_values("unknown"), [])
        self.assertEqual(power_attributes("50 kW; 150 kW")["power_kw_max"], 150.0)
        self.assertEqual(
            normalised_connectors("CCS (Type 2); CHAdeMO; Type2"),
            "CCS;CHAdeMO;Type2",
        )
        self.assertEqual(normalised_connectors(["CCS2", "Type2"]), "CCS;Type2")

    def test_ocm_osm_candidate_contracts(self):
        """P2: OCM and OSM use WGS84 points and do not invent plug counts."""
        with TemporaryDirectory() as folder:
            snapshot_dir = Path(folder)
            ocm_records = [
                {
                    "ID": 11,
                    "AddressInfo": {
                        "Title": "Sydney", "AddressLine1": "1 Main St",
                        "Latitude": -33.87, "Longitude": 151.21,
                    },
                    "Connections": [
                        {"ConnectionType": {"Title": "CCS (Type 2)"}, "PowerKW": 50}
                    ],
                    "NumberOfPoints": 2,
                    "StatusType": {"IsOperational": False},
                },
                {
                    "ID": 12,
                    "AddressInfo": {"Latitude": -37.81, "Longitude": 144.96},
                },
            ]
            (snapshot_dir / "task3_ocm_tiled_snapshot.json").write_text(
                json.dumps(ocm_records), encoding="utf-8"
            )
            settings = replace(Task3Config(), snapshot_dir=snapshot_dir)
            ocm = load_ocm_candidates(settings)

        self.assertEqual(len(ocm), 1)
        self.assertEqual(ocm[0]["id"], "11")
        self.assertTrue(ocm[0]["fast_dc"])
        self.assertIs(ocm[0]["attributes"]["is_operational"], False)
        self.assertEqual(ocm[0]["attributes"]["charging_point_count"], 2)
        self.assertIsNone(ocm[0]["attributes"]["number_of_plugs"])

        osm = load_osm_candidate_records([{
            "meta_osm_id": "42",
            "meta_name_state": "New South Wales",
            "latitude": -4_000_000,
            "longitude": 16_000_000,
            "meta_geo_point": {"lat": -33.9, "lon": 151.2},
            "has_socket_combo_ccs": "true",
            "charge_points_count": 2,
            "is_free": None,
            "max_power_kw": 50,
        }])
        self.assertEqual(len(osm), 1)
        self.assertEqual(osm[0]["latitude"], -33.9)
        self.assertEqual(osm[0]["longitude"], 151.2)
        self.assertTrue(osm[0]["fast_dc"])
        self.assertIsNone(osm[0]["attributes"]["number_of_plugs"])
        self.assertIsNone(osm[0]["attributes"]["is_free"])
        self.assertIsNone(osm[0]["attributes"]["power_kw_min"])

    def test_three_source_candidate_contracts(self):
        """P2: Charge@Large clips NSW and counts DC ports once each."""
        with TemporaryDirectory() as folder:
            snapshot_dir = Path(folder)
            stations = [
                {
                    "id": "nsw-dc", "name": "Mixed", "address": "1 Main St NSW 2000",
                    "coordinate": {"latitude": -33.87, "longitude": 151.21},
                    "chargePoints": [{"id": "device-1", "ports": [
                        {"id": "1", "connectorTypes": ["CCS2", "CHAdeMO"],
                         "powerKilowatts": 150, "status": "Available"},
                        {"id": "2", "connectorTypes": ["Type2"],
                         "powerKilowatts": 22, "status": "Charging"},
                        {"id": "3", "connectorTypes": ["CCS2"],
                         "powerKilowatts": 50, "status": "OutOfService"},
                        {"id": "3", "connectorTypes": ["CCS2"],
                         "powerKilowatts": 50, "status": "OutOfService"},
                    ]}],
                },
                {
                    "id": "vic-dc", "coordinate": {
                        "latitude": -37.81, "longitude": 144.96,
                    },
                    "chargePoints": [{"ports": [
                        {"connectorTypes": ["CCS2"], "powerKilowatts": 100}
                    ]}],
                },
                {
                    "id": "nsw-ac", "coordinate": {
                        "latitude": -33.87, "longitude": 151.21,
                    },
                    "chargePoints": [{"ports": [
                        {"connectorTypes": ["Type2"], "powerKilowatts": 22}
                    ]}],
                },
            ]
            (snapshot_dir / "task3_chargelarge_raw.json").write_text(
                json.dumps(stations), encoding="utf-8"
            )
            settings = replace(Task3Config(), snapshot_dir=snapshot_dir)
            candidates = load_chargelarge_candidates(settings)

        self.assertEqual({item["id"] for item in candidates}, {"nsw-dc", "nsw-ac"})
        dc = next(item for item in candidates if item["id"] == "nsw-dc")
        self.assertTrue(dc["fast_dc"])
        self.assertEqual(dc["postcode"], "2000")
        self.assertEqual(dc["attributes"]["dc_port_count"], 2)
        self.assertEqual(dc["attributes"]["total_port_count"], 3)
        self.assertEqual(dc["attributes"]["power_kw_min"], 50.0)
        self.assertEqual(dc["attributes"]["power_kw_max"], 150.0)
        self.assertEqual(dc["attributes"]["status_counts"], {
            "Available": 1, "OutOfService": 1,
        })
        self.assertIsNone(dc["attributes"]["number_of_plugs"])
        self.assertFalse(next(item for item in candidates if item["id"] == "nsw-ac")["fast_dc"])

    def test_candidate_selection_and_ambiguity(self):
        """P4: the 500 m search keeps distant and ambiguous candidates for review."""
        source = pd.DataFrame([{
            "Station_address": "1 Main St NSW 2000", "Operator": "Example",
            "PCODE": "2000", "Latitude": -33.0, "Longitude": 151.0,
        }], index=[17])

        def candidate(identifier, delta, address=""):
            return {
                "id": identifier, "source": "Test", "fast_dc": True,
                "latitude": -33.0 + delta, "longitude": 151.0,
                "address": address, "postcode": "2000", "operator": "",
                "station_name": identifier, "attributes": {"status": "Operational"},
            }

        with self._simple_match_rules():
            accepted = source_row_candidates(source, [
                candidate("close", 0.0004, "1 Main St NSW 2000")
            ])
            review_distance = source_row_candidates(source, [
                candidate("far", 0.003, "")
            ])
            review_address = source_row_candidates(source, [
                candidate("address-only", 0.01, "1 Main St NSW 2000")
            ])
            ambiguous = source_row_candidates(source, [
                candidate("first", 0.0004, "1 Main St NSW 2000"),
                candidate("second", 0.00045, "1 Main St NSW 2000"),
            ])
            unmatched = source_row_candidates(source, [])
            inside = source_row_candidates(source, [
                candidate("inside", 499 / 111_000, "")
            ])
            outside = source_row_candidates(source, [
                candidate("outside", 501 / 111_000, "")
            ])

        self.assertEqual(accepted.index.tolist(), [17])
        self.assertEqual(accepted.loc[17, "source_index"], 17)
        self.assertEqual(accepted.loc[17, "match_status"], "accepted")
        self.assertEqual(review_distance.loc[17, "match_status"], "review")
        self.assertEqual(review_address.loc[17, "match_status"], "review")
        self.assertEqual(ambiguous.loc[17, "match_status"], "review")
        self.assertIn("similarly close", ambiguous.loc[17, "review_reason"])
        self.assertEqual(ambiguous.loc[17, "candidate_count"], 2)
        self.assertEqual(inside.loc[17, "match_status"], "review")
        self.assertEqual(outside.loc[17, "match_status"], "unmatched")
        self.assertEqual(unmatched.loc[17, "match_status"], "unmatched")
        self.assertEqual(unmatched.loc[17, "matched_id"], "")

    def test_matching_replay_keeps_task2_rows(self):
        """P4: offline replay writes aligned evidence and never changes Task 2."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source_file = root / "cleaned.csv"
            source = self._sample_rows().iloc[[0, 2]].reset_index(drop=True)
            source.to_csv(source_file, index=False)
            original_bytes = source_file.read_bytes()

            snapshots = {
                "task3_ocm_tiled_snapshot.json": [{
                    "ID": 101,
                    "AddressInfo": {
                        "Title": "First", "AddressLine1": "1 Main St",
                        "Latitude": -33.0002, "Longitude": 151.0,
                    },
                    "Connections": [{
                        "ConnectionType": {"Title": "CCS (Type 2)"},
                        "PowerKW": 50,
                    }],
                    "StatusType": {"IsOperational": True},
                }],
                "task3_osm_nsw_snapshot_for_multisource.json": [{
                    "meta_osm_id": "0042",
                    "meta_name_state": "New South Wales",
                    "meta_geo_point": {"lat": -33.0002, "lon": 151.0},
                    "has_socket_combo_ccs": "true",
                }],
                "task3_chargelarge_raw.json": [{
                    "id": "charge-1", "address": "1 Main St",
                    "coordinate": {"latitude": -33.0002, "longitude": 151.0},
                    "chargePoints": [{"ports": [{
                        "connectorTypes": ["CCS2"], "powerKilowatts": 50,
                    }]}],
                }],
            }
            for name, records in snapshots.items():
                (root / name).write_text(json.dumps(records), encoding="utf-8")
            settings = replace(
                Task3Config(), input_file=source_file, raw_file=None,
                snapshot_dir=root, result_dir=root,
            )

            with self._simple_match_rules():
                summary = run_matching(settings)
                first_csv = settings.matches_file.read_bytes()
                rerun = run_matching(settings)

            self.assertEqual(summary, rerun)
            self.assertEqual(first_csv, settings.matches_file.read_bytes())
            self.assertEqual(source_file.read_bytes(), original_bytes)
            self.assertEqual(summary["source_dc_rows"], 1)
            self.assertEqual(
                summary["accepted_with_quality_flags"]
                + summary["accepted_without_quality_flags"],
                summary["combined_dc_indicated_count"],
            )
            output = pd.read_csv(settings.matches_file, dtype={
                "osm_fast_dc_id": "string",
            })
            self.assertEqual(len(output), 1)
            self.assertEqual(output.loc[0, "source_index"], 0)
            self.assertEqual(output.loc[0, "osm_fast_dc_id"], "0042")
            self.assertEqual(output.loc[0, "combined_dc_indicated_status"], "accepted")
            self.assertIn("ocm_quality_flags", output.columns)
            for source_columns in SOURCE_CONFIG.values():
                for field in ("id", "status", "method", "distance", "address", "address_score", "gap"):
                    self.assertIn(source_columns[field], output.columns)

    def test_reused_ids_require_a_shared_site(self):
        source = self._sample_rows().iloc[:2].copy()
        source["Station_address"] = ["1 Main St NSW 2000", "8 Other Rd NSW 2000"]
        source["PCODE"] = "2000"
        source.loc[1, "Latitude"] = source.loc[0, "Latitude"] + 0.001
        matches = pd.DataFrame({
            "source_index": [0, 1], "matched_id": ["shared", "shared"],
            "match_status": ["accepted", "accepted"],
            "review_reason": ["", ""], "match_quality_flags": ["", ""],
        })
        reviewed = resolve_reused_ids(matches.copy(), source)
        self.assertEqual(reviewed["match_status"].tolist(), ["review", "review"])
        source.loc[1, "Station_address"] = source.loc[0, "Station_address"]
        retained = resolve_reused_ids(matches.copy(), source)
        self.assertTrue(retained["match_status"].eq("accepted").all())

    def test_distant_numbered_address_can_corroborate_coordinates(self):
        source = self._sample_rows().iloc[:1].copy()
        source["Station_address"] = "1 Main Street NSW 2000"
        source["PCODE"] = "2000"
        candidate = {
            "id": "numbered", "fast_dc": True,
            "latitude": -32.997, "longitude": 151.0,
            "address": "1 Main St NSW 2000", "postcode": "2000",
            "attributes": {"connector_types_normalized": "CCS"},
        }
        self.assertEqual(source_row_candidates(source, [candidate]).iloc[0]["match_status"], "accepted")
        candidate["postcode"] = "2001"
        candidate["address"] = "1 Main St NSW 2001"
        self.assertEqual(source_row_candidates(source, [candidate]).iloc[0]["match_status"], "review")

    def test_osm_object_namespaces_do_not_collide(self):
        records = [{
            "meta_osm_id": 42, "meta_osm_url": f"https://www.openstreetmap.org/{kind}/42",
            "meta_name_state": "New South Wales",
            "meta_geo_point": {"lat": -33.0, "lon": 151.0},
            "has_socket_combo_ccs": "true",
        } for kind in ("node", "way")]
        self.assertEqual(len({r["id"] for r in load_osm_candidate_records(records)}), 2)

    def test_ocm_dc_power_excludes_ac_connections(self):
        from pipeline.data_aug.ocm_reference import _task3_normalise_ocm_record
        record = _task3_normalise_ocm_record({"ID": 1, "Connections": [
            {"ConnectionType": {"Title": "Type 2"}, "PowerKW": 7},
            {"ConnectionType": {"Title": "CCS (Type 2)"}, "PowerKW": 150},
        ]})
        self.assertEqual(record["dc_power_kw_values"], [150])
        self.assertEqual(new_attribute_count({"OCM::operator": "Example", "OCM::power_scope": "DC"}), 0)

    def test_tampered_snapshot_cannot_reuse_retrieval_metadata(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for filename in ("task3_ocm_tiled_snapshot.json", "task3_osm_nsw_snapshot_for_multisource.json",
                             "task3_chargelarge_raw.json"):
                (root / filename).write_text("[]")
            (root / "task3_ocm_tiled_snapshot_metadata.json").write_text(json.dumps({"sha256": "incorrect"}))
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                preflight(replace(Task3Config(), snapshot_dir=root))

    def test_duplicates_and_conflicting_sources(self):
        """P5: duplicate IDs across/within sources and contradictory attribute evidence."""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = self._sample_rows().iloc[:2].copy()
            source_file = root / "cleaned.csv"
            source.to_csv(source_file, index=False)
            original_source = source_file.read_bytes()
            settings = replace(
                Task3Config(), input_file=source_file, raw_file=None,
                snapshot_dir=root, result_dir=root,
            )
            matches = source.copy()
            matches.insert(0, "source_index", [0, 1])
            for prefix, config in SOURCE_CONFIG.items():
                matches[config["status"]] = ["unmatched", "unmatched"]
                matches[config["id"]] = ["", ""]
                matches[config["distance"]] = [None, None]
                matches[f"{prefix}_attributes"] = ["{}", "{}"]
                matches[f"{prefix}_quality_flags"] = ["", ""]
                matches[f"{prefix}_review_reason"] = ["", ""]

            matches["ocm_status"] = ["accepted", "accepted"]
            matches["ocm_id"] = ["0007", "0007"]
            matches["ocm_distance_m"] = [20.0, 30.0]
            matches["ocm_attributes"] = [
                json.dumps({"connector_types_normalized": "CCS", "power_kw_max": 50}),
                json.dumps({"connector_types_normalized": "CCS", "power_kw_max": 0}),
            ]
            matches["osm_fast_dc_status"] = ["accepted", "unmatched"]
            matches["osm_fast_dc_id"] = ["0007", ""]
            matches["osm_fast_dc_attributes"] = [json.dumps({
                "is_free": False, "power_kw_max": 150,
            }), "{}"]
            matches["chargelarge_fast_dc_status"] = ["review", "unmatched"]
            matches["chargelarge_fast_dc_attributes"] = [json.dumps({
                "opening_hours": "24/7",
            }), "{}"]
            matches["chargelarge_fast_dc_review_reason"] = [
                "address-only candidate", "",
            ]
            matches.to_csv(settings.matches_file, index=False)
            for name in (
                "task3_ocm_tiled_snapshot.json",
                "task3_osm_nsw_snapshot_for_multisource.json",
                "task3_chargelarge_raw.json",
            ):
                (root / name).write_text("[]", encoding="utf-8")

            summary = run_audit(settings)
            audit = pd.read_csv(
                settings.audit_file,
                dtype={config["id"]: "string" for config in SOURCE_CONFIG.values()},
                keep_default_na=False,
            )
            duplicates = duplicate_external_id_rows(audit)

            self.assertEqual(summary["tfnsw_dc_rows"], 2)
            self.assertEqual(summary["accepted_with_new_attributes_rows"], 2)
            self.assertEqual(summary["accepted_quality_flag_rows"], 2)
            self.assertEqual(summary["duplicate_external_id_groups"], 1)
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates.loc[0, "source"], "OCM")
            self.assertEqual(duplicates.loc[0, "external_id"], "0007")
            self.assertEqual(duplicates.loc[0, "source_indices"], "0;1")
            self.assertIn("multiple TfNSW rows", audit.loc[0, "quality_review_reason"])
            self.assertIn("power_kw_max", audit.loc[0, "augmentation_conflict_flags"])
            exported = json.loads(audit.loc[0, "augmented_attributes"])
            self.assertIs(exported["OSM::is_free"], False)
            self.assertNotIn("OCM::power_kw_max", exported)
            self.assertNotIn("Charge@Large::opening_hours", exported)
            self.assertNotIn(
                "OCM::power_kw_max",
                json.loads(audit.loc[1, "augmented_attributes"]),
            )
            self.assertEqual(source_file.read_bytes(), original_source)

            matches.loc[0, "ocm_attributes"] = "invalid json"
            matches.to_csv(settings.matches_file, index=False)
            with self.assertRaisesRegex(ValueError, "Malformed matched attributes"):
                run_audit(settings)

            matches.loc[0, "ocm_attributes"] = "{}"
            matches.loc[0, "Operator"] = "different operator"
            matches.to_csv(settings.matches_file, index=False)
            with self.assertRaisesRegex(ValueError, "Stale matching input: Operator"):
                run_audit(settings)

            matches.loc[0, "Operator"] = source.loc[0, "Operator"]
            matches.loc[0, "Station_address"] = "changed address"
            matches.to_csv(settings.matches_file, index=False)
            with self.assertRaisesRegex(ValueError, "Stale matching input"):
                run_audit(settings)

    def test_genuinely_new_attributes(self):
        """P5: unknown versus false/zero, metadata and original TfNSW field semantics."""
        self.assertEqual(new_attribute_count({
            "OCM::data_provider": "OCM",
            "OCM::number_of_plugs": 2,
            "OCM::power_kw_max": 150,
            "OCM::connector_types_normalized": "CCS",
            "OSM::connector_types_normalized": "CCS",
            "OSM::is_free": False,
            "OSM::opening_hours": "unknown",
            "Charge@Large::status_counts": {},
            "OCM::network": pd.NA,
        }), 2)
        self.assertEqual(new_attribute_count({
            "OCM::power_kw_max": 150,
            "OSM::dc_port_count": 2,
        }), 0)
        self.assertEqual(identifier(7.0), "7")
        self.assertEqual(identifier("0007"), "0007")

    def test_column_cleaner_alignment_and_preservation(self):
        """P6: unchanged source data, AC/DC separation and stale/misaligned audit input."""
        with TemporaryDirectory() as folder:
            path = Path(folder) / "audit.csv"
            source = self._sample_rows()
            audit = source.loc[[1, 0]].copy()
            audit.insert(0, "source_index", [1, 0])
            audit["final_audit_status"] = ["review", "accepted"]
            audit["augmented_attributes"] = [
                json.dumps({"OCM::network": "Unconfirmed"}),
                json.dumps({
                    "OCM::connector_types_normalized": "CCS2",
                    "OCM::power_kw_max": 150,
                    "OSM::dc_port_count": 2,
                    "OSM::is_free": False,
                }),
            ]
            audit["quality_review_required"] = ["no", "yes"]
            audit["augmentation_conflict_flags"] = ["", ""]
            audit["matched_source"] = ["", "OCM;OSM"]
            audit["matched_external_ids"] = ["", "OCM:0007;OSM:0042"]

            def apply_audit():
                cleaners = GET_NSW_EV_COLUMN_AUGMENTATION_CCS(source, path)
                return DataCleaner(
                    cleaners, input_data_frame=source.copy(deep=True)
                ).clean_data()

            audit.to_csv(path, index=False)
            result = apply_audit()
            pd.testing.assert_frame_equal(result[source.columns], source)
            self.assertEqual(result["augmentation_match_status"].tolist(),
                             ["accepted", "review", "not_applicable"])
            self.assertEqual(result.loc[0, "external_connector_types_normalized"], "CCS2")
            self.assertEqual(result.loc[0, "external_power_kw_max"], 150.0)
            self.assertEqual(result.loc[0, "external_dc_port_count"], 2.0)
            self.assertEqual(result.loc[0, "external_is_free"], "false")
            self.assertEqual(result.loc[0, "augmentation_quality_review"], "yes")
            self.assertEqual(result.loc[0, "external_station_id"], "OCM:0007;OSM:0042")
            self.assertEqual(json.loads(result.loc[0, "external_attributes_json"])[
                "OSM::is_free"], False)
            for row in (1, 2):
                self.assertEqual(result.loc[row, "external_attributes_json"], "")
                self.assertEqual(result.loc[row, "external_is_free"], "")
                self.assertTrue(pd.isna(result.loc[row, "external_power_kw_max"]))
            self.assertEqual(result.loc[2, "augmentation_quality_review"], "")
            self.assertEqual(source.loc[0, "PCODE"], "0200")

            audit.loc[1, "final_audit_status"] = "unmatched"
            audit.to_csv(path, index=False)
            self.assertEqual(apply_audit().loc[1, "external_attributes_json"], "")

            audit.loc[1, "final_audit_status"] = "accepted"
            audit.loc[0, "augmentation_conflict_flags"] = "power_kw_max"
            audit.loc[0, "augmented_attributes"] = json.dumps({
                "OCM::power_kw_max": 50, "OSM::power_kw_max": 150,
                "OCM::connector_types_normalized": "CCS2",
            })
            audit.to_csv(path, index=False)
            self.assertTrue(pd.isna(apply_audit().loc[0, "external_power_kw_max"]))

            # A missing conflict flag must not turn disagreeing sources into
            # one authoritative scalar either.
            audit.loc[0, "augmentation_conflict_flags"] = ""
            audit.to_csv(path, index=False)
            self.assertTrue(pd.isna(apply_audit().loc[0, "external_power_kw_max"]))

            audit.loc[0, "augmented_attributes"] = "not json"
            audit.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Malformed augmented_attributes"):
                apply_audit()

            audit.loc[0, "augmented_attributes"] = "{}"
            audit.loc[0, "Station_address"] = "Changed address"
            audit.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Stale audit input: Station_address"):
                apply_audit()

            audit.loc[0, "Station_address"] = source.loc[0, "Station_address"]
            audit.loc[0, "Latitude"] = -32.0
            audit.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Stale audit input: Latitude"):
                apply_audit()

            audit.loc[0, "Latitude"] = source.loc[0, "Latitude"]
            audit.loc[0, "source_index"] = 1
            audit.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                apply_audit()

            audit.loc[0, "source_index"] = 0
            audit = audit.iloc[:1]
            audit.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "cover current Task 2 DC rows"):
                apply_audit()

    def test_coverage_validation_accepts_and_rejects(self):
        """P7: current DC denominator, unique source rows and failing validation cases."""
        source = self._sample_rows()
        augmented = source.copy(deep=True)
        augmented["augmentation_match_status"] = [
            "accepted", "review", "not_applicable",
        ]
        augmented["external_attributes_json"] = [
            json.dumps({
                "OCM::connector_types_normalized": "CCS2",
                "OSM::is_free": False,
            }),
            "", "",
        ]
        augmented["augmentation_quality_review"] = ["yes", "", ""]
        augmented["external_connector_types_normalized"] = ["CCS2", "", ""]
        augmented["external_power_kw_max"] = [150.0, None, None]

        report = validate_augmentation(source, augmented)
        self.assertEqual(report["input_rows"], 3)
        self.assertEqual(report["dc_rows"], 2)
        self.assertEqual(report["accepted_rows"], 1)
        self.assertEqual(report["required_rows"], 1)
        self.assertEqual(report["accepted_coverage"], 0.5)
        self.assertEqual(report["input_columns"], list(source.columns))
        self.assertTrue(report["all_accepted_rows_have_new_attributes"])

        changed = augmented.copy(deep=True)
        changed.loc[0, "PCODE"] = "9999"
        with self.assertRaisesRegex(ValueError, "original Task 2 value"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed.loc[2, "augmentation_match_status"] = "accepted"
        with self.assertRaisesRegex(ValueError, "non-DC"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed.loc[1, "external_attributes_json"] = '{"OCM::network":"X"}'
        with self.assertRaisesRegex(ValueError, "Unaccepted row"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed["external_is_free"] = ["", "false", ""]
        with self.assertRaisesRegex(ValueError, "Unaccepted row"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed.loc[1, "augmentation_quality_review"] = "yes"
        with self.assertRaisesRegex(ValueError, "Quality review flag"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed.loc[0, "external_attributes_json"] = "not json"
        with self.assertRaisesRegex(ValueError, "Invalid external attributes"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed.loc[0, "external_attributes_json"] = json.dumps({
            "OCM::power_kw_max": 150,
        })
        with self.assertRaisesRegex(ValueError, "no genuinely new attribute"):
            validate_augmentation(source, changed)

        changed = augmented.copy(deep=True)
        changed["augmentation_match_status"] = [
            "review", "review", "not_applicable",
        ]
        changed["external_attributes_json"] = ""
        changed["augmentation_quality_review"] = ""
        changed["external_connector_types_normalized"] = ""
        changed["external_power_kw_max"] = None
        with self.assertRaisesRegex(ValueError, "coverage is too low"):
            validate_augmentation(source, changed)

        duplicate_source = source.copy(deep=True)
        duplicate_output = augmented.copy(deep=True)
        duplicate_source.index = [0, 0, 2]
        duplicate_output.index = [0, 0, 2]
        with self.assertRaisesRegex(ValueError, "indices must be unique"):
            validate_augmentation(duplicate_source, duplicate_output)

    def test_ocm_collection_without_network(self):
        """P8: key stays in the header, duplicate POIs collapse, old files survive."""
        response = json.dumps([{"ID": 7, "AddressInfo": {}}]).encode()
        with patch.dict(os.environ, {"OCM_API_KEY": "test-key"}):
            with patch.object(ocm_snapshot.urllib.request, "urlopen",
                              return_value=BytesIO(response)) as urlopen:
                records = ocm_snapshot.request_tile(-34, 150, -33, 151)
            self.assertEqual(ocm_snapshot.poi_id(records[0]), "7")
            request = urlopen.call_args.args[0]
            self.assertNotIn("test-key", request.full_url)
            headers = dict(request.header_items())
            self.assertEqual(headers["X-api-key"], "test-key")

        with patch.dict(os.environ, {"OCM_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "OCM_API_KEY"):
                ocm_snapshot.request_tile(-34, 150, -33, 151)
        with self.assertRaisesRegex(ValueError, "no ID"):
            ocm_snapshot.poi_id({})

        with TemporaryDirectory() as folder:
            destination = Path(folder) / "new-snapshot"
            with patch.dict(os.environ, {"TASK3_NEW_SNAPSHOT_DIR": str(destination)}):
                with patch.object(ocm_snapshot, "request_tile",
                                  side_effect=RuntimeError("offline")):
                    with self.assertRaisesRegex(RuntimeError, "offline"):
                        ocm_snapshot.main()
                self.assertFalse(destination.exists())

                with patch.object(ocm_snapshot, "request_tile",
                                  return_value=[{"ID": 7}]):
                    with patch.object(ocm_snapshot.time, "sleep"):
                        ocm_snapshot.main()
                snapshot = destination / "task3_ocm_tiled_snapshot.json"
                self.assertEqual(len(json.loads(snapshot.read_text())), 1)
                metadata = json.loads((destination /
                                       "task3_ocm_tiled_snapshot_metadata.json").read_text())
                self.assertEqual(metadata["query_count"], 16)
                original = snapshot.read_bytes()
                self.assertEqual(metadata["sha256"],
                                 ocm_snapshot.hashlib.sha256(original).hexdigest())
                self.assertTrue(snapshot_metadata(
                    snapshot, destination / "task3_ocm_tiled_snapshot_metadata.json",
                )["retrieval_metadata_hash_verified"])
                with self.assertRaises(FileExistsError):
                    ocm_snapshot.main()
                self.assertEqual(snapshot.read_bytes(), original)

    def test_chargelarge_collection_without_network(self):
        """P8: validate raw response and save it only in a new directory."""
        raw = [{"id": "x", "chargePoints": [{"ports": []}]}]
        payload = json.dumps(raw).encode()
        with patch.object(chargelarge_snapshot.urllib.request, "urlopen",
                          return_value=BytesIO(payload)):
            self.assertEqual(chargelarge_snapshot.fetch(), raw)
        with patch.object(chargelarge_snapshot.urllib.request, "urlopen",
                          return_value=BytesIO(b"{}")):
            with self.assertRaisesRegex(ValueError, "invalid response"):
                chargelarge_snapshot.fetch()

        with TemporaryDirectory() as folder:
            destination = Path(folder) / "new-snapshot"
            with patch.dict(os.environ, {"TASK3_NEW_SNAPSHOT_DIR": str(destination)}):
                with patch.object(chargelarge_snapshot, "fetch", return_value=raw):
                    chargelarge_snapshot.main()
                path = destination / "task3_chargelarge_raw.json"
                self.assertEqual(json.loads(path.read_text()), raw)
                metadata = json.loads((destination /
                                       "task3_chargelarge_metadata.json").read_text())
                self.assertEqual(metadata["raw_record_count"], 1)
                original = path.read_bytes()
                self.assertEqual(metadata["sha256"],
                                 chargelarge_snapshot.hashlib.sha256(original).hexdigest())
                self.assertTrue(snapshot_metadata(
                    path, destination / "task3_chargelarge_metadata.json",
                )["retrieval_metadata_hash_verified"])
                with self.assertRaises(FileExistsError):
                    chargelarge_snapshot.main()
                self.assertEqual(path.read_bytes(), original)

    def test_osm_collection_pagination_without_network(self):
        """P8: retry, complete pagination, provenance, and safe refresh."""
        page = {"total_count": 1, "results": [{"meta_osm_id": "1"}]}
        response = json.dumps(page).encode()
        with patch.object(osm_snapshot.urllib.request, "urlopen",
                          return_value=BytesIO(response)):
            self.assertEqual(osm_snapshot.request_page({"limit": 1}), page)
        error = urllib.error.HTTPError(osm_snapshot.ENDPOINT, 403, "forbidden", {}, None)
        with patch.object(osm_snapshot.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                osm_snapshot.request_page({"limit": 1})
        temporary_error = urllib.error.HTTPError(
            osm_snapshot.ENDPOINT, 429, "busy", {}, None,
        )
        with patch.object(osm_snapshot.urllib.request, "urlopen",
                          side_effect=[temporary_error, BytesIO(response)]):
            with patch.object(osm_snapshot.time, "sleep") as sleeper:
                self.assertEqual(osm_snapshot.request_page({"limit": 1}), page)
            sleeper.assert_called_once()

        with TemporaryDirectory() as folder:
            target = Path(folder) / osm_snapshot.SNAPSHOT_NAME
            target.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "nonempty list"):
                osm_snapshot.snapshot(Path(folder), refresh=False)

        first = {
            "meta_osm_id": "1", "meta_osm_url": "https://www.openstreetmap.org/node/1",
            "meta_name_state": "New South Wales",
            "meta_geo_point": {"lat": -33.9, "lon": 151.2},
        }
        second = {
            "meta_osm_id": "2", "meta_osm_url": "https://www.openstreetmap.org/node/2",
            "meta_name_state": "New South Wales",
            "meta_geo_point": {"lat": -34.0, "lon": 150.9},
        }
        batches = [
            {"total_count": 2, "results": [first]},
            {"total_count": 2, "results": [second]},
        ]
        with patch.object(osm_snapshot, "request_page", side_effect=batches) as page_request:
            with patch.object(osm_snapshot.time, "sleep"):
                records, metadata = osm_snapshot.fetch_records(page_size=1)
        self.assertEqual([call.args[0]["offset"] for call in page_request.call_args_list],
                         [0, 1])
        self.assertEqual([r["meta_osm_id"] for r in records], ["1", "2"])
        self.assertEqual(metadata["reported_total_count"], 2)

        with patch.object(osm_snapshot, "request_page", side_effect=[
            batches[0], {"total_count": 3, "results": [second]},
        ]):
            with patch.object(osm_snapshot.time, "sleep"):
                with self.assertRaisesRegex(ValueError, "changed during pagination"):
                    osm_snapshot.fetch_records(page_size=1)
        with patch.object(osm_snapshot, "request_page", side_effect=[
            batches[0], {"total_count": 2, "results": [first]},
        ]):
            with patch.object(osm_snapshot.time, "sleep"):
                with self.assertRaisesRegex(ValueError, "Duplicate OSM"):
                    osm_snapshot.fetch_records(page_size=1)
        with self.assertRaisesRegex(ValueError, "outside the NSW"):
            osm_snapshot.validate_records([{
                **first, "meta_name_state": "Victoria",
            }])
        with self.assertRaisesRegex(ValueError, "invalid WGS84"):
            osm_snapshot.validate_records([{
                **first, "meta_geo_point": {"lat": 99, "lon": 151},
            }])

        with TemporaryDirectory() as folder:
            destination = Path(folder)
            with patch.object(osm_snapshot, "fetch_records",
                              return_value=(records, metadata)):
                osm_snapshot.snapshot(destination, refresh=True, page_size=1)
            target = destination / osm_snapshot.SNAPSHOT_NAME
            metadata_file = destination / osm_snapshot.METADATA_NAME
            saved_metadata = json.loads(metadata_file.read_text())
            self.assertEqual(saved_metadata["sha256"],
                             osm_snapshot.hashlib.sha256(target.read_bytes()).hexdigest())
            cached = osm_snapshot.snapshot(destination, refresh=False)
            self.assertTrue(cached["retrieval_metadata_verified"])
            self.assertEqual(cached["retrieved_at_utc"], metadata["retrieved_at_utc"])
            original = target.read_bytes()
            with self.assertRaises(FileExistsError):
                osm_snapshot.snapshot(destination, refresh=True, page_size=1)
            self.assertEqual(target.read_bytes(), original)

        with TemporaryDirectory() as folder:
            destination = Path(folder)
            with patch.object(osm_snapshot, "request_page",
                              side_effect=RuntimeError("offline")):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    osm_snapshot.snapshot(destination, refresh=True)
            self.assertFalse((destination / osm_snapshot.SNAPSHOT_NAME).exists())

    def test_offline_end_to_end_replay(self):
        """P1-P7: temporary output paths, local fixtures, replay and CSV round-trip types."""
        base = Task3Config()
        if not base.input_file.is_file():
            self.fail("Task 2 fixture is missing")
        source_bytes = base.input_file.read_bytes()
        source = read_task2_output(base.input_file)

        with TemporaryDirectory() as folder:
            destination = Path(folder)
            settings = replace(
                base, result_dir=destination,
                output_file=destination / "augmented.csv",
            )
            report = run_task3(settings)
            written = pd.read_csv(
                settings.output_file,
                dtype={"PCODE": "string", "PCODE_ORIGINAL": "string",
                       "SA4_CODE26": "string", "external_is_free": "string"},
            )
            audit = pd.read_csv(settings.audit_file, keep_default_na=False)

            self.assertEqual(report["input_rows"], len(source))
            self.assertEqual(report["dc_rows"], int(source["Charger_Type"].eq("DC").sum()))
            self.assertEqual(report["accepted_rows"],
                             int(written["augmentation_match_status"].eq("accepted").sum()))
            self.assertEqual(report["accepted_rows"],
                             int(audit["final_audit_status"].eq("accepted").sum()))
            self.assertGreaterEqual(report["accepted_rows"], report["required_rows"])
            self.assertEqual(len(written), len(source))
            self.assertTrue(source["PCODE"].fillna("").equals(written["PCODE"].fillna("")))
            self.assertTrue(written.loc[
                written["Charger_Type"].ne("DC"),
                "augmentation_match_status",
            ].eq("not_applicable").all())
            self.assertEqual(base.input_file.read_bytes(), source_bytes)


if __name__ == "__main__":
    unittest.main()
