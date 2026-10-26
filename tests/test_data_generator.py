# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Generator integration checks with local data; no AEMO or MQTT connections."""
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_generator.data_generator_config import GenerationConfig, NEM_TIME
from data_generator.data_generator_utils import (
    generate_dataset, generate_evc_state_update, load_wholesale_hourly, station_record,
)
from repository.entity.ev_charger import EVCharger
from repository.entity.ev_charger_state import EVChargerState
from repository.event.ev_charger_state_event import EVChargerStateEvent


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.config = GenerationConfig(output_dir=self.path, start="2026-09-15", days=1)
        self.start = datetime(2026, 9, 15, tzinfo=NEM_TIME)
        self.wholesale = {self.start + timedelta(hours=h): .05 for h in range(24)}
        self.chargers = [EVCharger(7, charger_type="AC", number_of_plugs=1, rating_kw=7),
                         EVCharger(42, charger_type="DC", number_of_plugs=1, rating_kw=150)]

    def write_csv(self, name, rows):
        with (self.path / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def aemo_rows(self, period_type="TRADE"):
        return [dict(SETTLEMENTDATE=(self.start + timedelta(minutes=5 * (i + 1))).strftime(
            "%Y/%m/%d %H:%M:%S"), RRP=(-12 + i if i < 12 else (i // 12) * 10 + i % 12),
            PERIODTYPE=period_type) for i in range(24 * 12)]

    def write_aemo_cache(self, rows):
        (self.path / "aemo_cache").mkdir(exist_ok=True)
        self.write_csv("aemo_cache/PRICE_AND_DEMAND_202609_NSW1.csv", rows)

    @patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network call"))
    def test_aemo_period_ending_prices_and_negative_values(self, _urlopen):
        for period_type in ["TRADE", "ACTUAL"]:
            with self.subTest(period_type=period_type):
                rows = self.aemo_rows(period_type)
                self.write_aemo_cache(rows + [dict(row, RRP=99999, PERIODTYPE="FORECAST") for row in rows])
                hourly = load_wholesale_hourly(self.config)
                self.assertEqual(set(hourly), set(self.wholesale))
                self.assertAlmostEqual(hourly[self.start], -.0065)
                self.assertAlmostEqual(hourly[self.start + timedelta(hours=23)], .2355)

    @patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected next-month download"))
    def test_month_end_midnight_interval_is_in_previous_month_file(self, _urlopen):
        self.start = self.start.replace(day=30)
        self.config.start = "2026-09-30"
        rows = self.aemo_rows()
        self.assertEqual(rows[-1]["SETTLEMENTDATE"], "2026/10/01 00:00:00")
        self.write_aemo_cache(rows)
        hourly = load_wholesale_hourly(self.config)
        self.assertEqual(len(hourly), 24)
        self.assertAlmostEqual(hourly[self.start + timedelta(hours=23)], .2355)

    @patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network call"))
    def test_forecast_and_duplicate_cannot_replace_missing_actual_interval(self, _urlopen):
        rows = self.aemo_rows()
        rows[0]["PERIODTYPE"] = "FORECAST"
        self.write_aemo_cache(rows + [rows[1]])
        with self.assertRaisesRegex(ValueError, "Incomplete AEMO coverage"):
            load_wholesale_hourly(self.config)

    def test_station_mapping_preserves_identity_and_records_assumptions(self):
        original = self.chargers[0].to_dict()
        record = station_record(self.chargers[0], self.config)
        self.assertEqual((record["station_id"], record["connectors"], record["max_kw"]),
                         ("7", 1, 7))
        self.assertEqual(self.chargers[0].to_dict(), original)
        for kind, power in [("AC", 7), ("DC", 50), (None, 7)]:
            with self.subTest(kind=kind):
                row = station_record(EVCharger(900, charger_type=kind), self.config)
                self.assertEqual((row["station_id"], row["connectors"], row["max_kw"]),
                                 ("900", 1, power))
                self.assertEqual(row["model_type"], "DC" if kind == "DC" else "AC")
                self.assertTrue(row["assumptions"])

    def test_incomplete_or_nonfinite_wholesale_fails(self):
        for value in [None, float("nan"), float("inf")]:
            prices = self.wholesale.copy()
            if value is None:
                del prices[self.start]
            else:
                prices[self.start] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                generate_dataset(self.chargers, self.config, wholesale=prices)

    def test_no_sessions_still_produces_readable_csvs(self):
        self.config.sessions_per_connector_day = (0, 0)
        manifest = generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        self.assertEqual(manifest["counts"], dict(stations=2, prices=48, sessions=0, meters=0))
        for name in ["sessions.csv", "session_metering.csv"]:
            with (self.path / name).open() as stream:
                reader = csv.DictReader(stream)
                self.assertTrue(reader.fieldnames)
                self.assertEqual(list(reader), [])
        self.assertTrue(all(e.type == "price_update"
                            for e in generate_evc_state_update(self.path)))

    def test_generated_ac_dc_events_roundtrip_and_close_sessions(self):
        manifest = generate_dataset(self.chargers, self.config, wholesale=self.wholesale)
        self.assertGreater(manifest["counts"]["sessions"], 0)
        events = list(generate_evc_state_update(self.path))
        self.assertEqual([e.ts for e in events], sorted(e.ts for e in events))
        self.assertEqual({e.type for e in events},
                         {"price_update", "session_start", "meter", "session_end"})
        states = {c.station_id: EVChargerState(c.station_id, manifest["run_id"])
                  for c in self.chargers}
        ids = [e.event_id for e in events]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, [e.event_id for e in generate_evc_state_update(self.path)])
        for event in events:
            decoded = EVChargerStateEvent.from_json(event.to_json())
            self.assertEqual(event.to_dict(), decoded.to_dict())
            states[event.station_id].apply(decoded)
            if event.type == "meter":
                self.assertLessEqual(event.payload["power_kw"], 7 if event.station_id == "7" else 150)
        self.assertTrue(all(state.active_session_count == 0 for state in states.values()))

    def test_price_changes_and_same_time_session_handover(self):
        (self.path / "manifest.json").write_text(json.dumps({"run_id": "fixture"}))
        def ts(minutes):
            return (self.start + timedelta(minutes=minutes)).isoformat()
        self.write_csv("prices_hourly.csv", [dict(ts=ts(h * 60), station_id="7",
            price_per_kwh=p, wholesale_per_kwh=w) for h, p, w in
            [(0, .4, .05), (1, .4, .07), (2, .5, .07), (3, .5, .07)]])
        self.write_csv("sessions.csv", [dict(session_id=sid, station_id="7", connector_id=1,
            vehicle_model="Fixture EV", start_ts=ts(start), charge_end_ts=ts(end), end_ts=ts(end),
            charge_minutes=end - start, energy_kwh=.1, price_per_kwh=.5, cost_aud=.05,
            avg_kw=6, peak_kw=6) for sid, start, end in [("old", 1439, 1440), ("new", 1440, 1441)]])
        self.write_csv("session_metering.csv", [dict(ts=ts(end), type="meter", station_id="7",
            connector_id=1, session_id=sid, voltage_v=230, current_a=26.1, power_kw=6,
            energy_kwh=.1, soc_pct=50) for sid, end in [("old", 1440), ("new", 1441)]])
        events = list(generate_evc_state_update(self.path))
        prices = [e.payload["price_per_kwh"] for e in events if e.type == "price_update"]
        self.assertEqual(prices, [.4, .5])
        state = EVChargerState("7", "fixture")
        for event in events:
            state.apply(event)
        self.assertEqual(state.active_session_count, 0)
        self.assertGreater(events[-1].ts, self.start + timedelta(days=1))
        self.assertEqual([e.type for e in events if e.ts == self.start + timedelta(days=1)],
                         ["meter", "session_end", "session_start"])


if __name__ == "__main__":
    unittest.main()
