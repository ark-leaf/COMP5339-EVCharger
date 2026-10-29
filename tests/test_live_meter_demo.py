"""Controlled live-demo event schema and state-transition tests."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest

from repository.entity.ev_charger_state import EVChargerState
from repository.event.ev_charger_state_event import EVChargerStateEvent
from scripts.live_meter_demo import build_demo_events, parse_args


class LiveMeterDemoTests(unittest.TestCase):
    def test_interactive_mode_requires_publish_and_keeps_noninteractive_default(self):
        args = parse_args(["--publish", "--wait-for-ready", "--run-id", "a" * 32, "--charger-id", "4"])
        self.assertTrue(args.wait_for_ready)
        self.assertEqual(args.pause_after_start, 45.0)
        with self.assertRaises(SystemExit):
            parse_args(["--prepare", "--wait-for-ready", "--run-id", "a" * 32, "--charger-id", "4"])

    def test_sequence_has_ten_cumulative_meters_and_closes_cleanly(self):
        events = build_demo_events("a" * 32, 4, started_at=datetime(2026, 10, 28, tzinfo=timezone.utc))
        self.assertEqual([event.type for event in events[:2]], ["price_update", "session_start"])
        meters = [event for event in events if event.type == "meter"]
        self.assertEqual(len(meters), 10)
        self.assertEqual([event.payload["energy_kwh"] for event in meters], [1.25 * i for i in range(1, 11)])
        self.assertTrue(all(event.run_id == "a" * 32 and event.charger_id == 4
                            and event.connector_id == 1 and event.session_id == meters[0].session_id
                            for event in events[1:]))
        self.assertEqual((meters[0].ts - events[1].ts).total_seconds(), 90)
        self.assertTrue(all((later.ts - earlier.ts).total_seconds() == 90
                            for earlier, later in zip(meters, meters[1:])))
        self.assertTrue(all(event.payload["power_kw"] == 50.0 for event in meters))
        self.assertTrue(all((later.payload["energy_kwh"] - earlier.payload["energy_kwh"]) == 1.25
                            for earlier, later in zip(meters, meters[1:])))
        self.assertEqual(events[-1].payload["charge_minutes"], 15.0)
        self.assertEqual(events[-1].payload["charge_end_ts"], meters[-1].ts)
        self.assertGreater(events[-1].ts, meters[-1].ts)
        self.assertEqual(events[-1].payload["energy_kwh"], 12.5)
        self.assertAlmostEqual(events[-1].payload["cost_aud"], 6.875, places=6)
        state = EVChargerState(4, "a" * 32)
        for event in events[:2]:
            state.apply(event)
        self.assertEqual(state.active_session_count, 1)
        for event in events[2:]:
            state.apply(event)
        self.assertEqual(state.active_session_count, 0)
        restored = [EVChargerStateEvent.from_json(event.to_json()) for event in events]
        self.assertEqual([event.to_dict() for event in restored], [event.to_dict() for event in events])


if __name__ == "__main__":
    unittest.main()
