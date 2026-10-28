"""Unit coverage for the unified main_ass_2 post-commit bridge."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from uuid import uuid4

import main_ass_2
from repository.event.ev_charger_state_event import EVChargerStateEvent


class UnifiedMainTests(unittest.TestCase):
    def _event(self):
        return EVChargerStateEvent(id=str(uuid4()), run_id="unified-run", type="price_update",
            ts=datetime(2026, 10, 28, tzinfo=timezone.utc), object_id="1",
            payload={"price_per_kwh": 0.42})

    def test_dashboard_notification_follows_only_a_successful_store(self):
        class Store:
            def __init__(self, stored): self.stored = stored
            def save(self, event): return self.stored
        class Dashboard:
            def __init__(self): self.events = []
            def notify_committed(self, event): self.events.append(event)

        dashboard = Dashboard()
        with patch.object(main_ass_2, "event_store", Store(True)), \
             patch.object(main_ass_2, "_dashboard_live_service", dashboard):
            main_ass_2.sub_database_update(self._event())
        self.assertEqual(len(dashboard.events), 1)

        dashboard = Dashboard()
        with patch.object(main_ass_2, "event_store", Store(False)), \
             patch.object(main_ass_2, "_dashboard_live_service", dashboard):
            main_ass_2.sub_database_update(self._event())
        self.assertEqual(dashboard.events, [])

    def test_replay_removes_second_broker_flag_and_keeps_one_publisher(self):
        arguments = ["--limit", "3", "--inline-broker", "--publish"]
        self.assertNotIn("--publish", main_ass_2._prepare_arguments(arguments))
        replay = main_ass_2._replay_arguments(arguments, "localhost", 1883)
        self.assertNotIn("--inline-broker", replay)
        self.assertEqual(replay.count("--publish"), 1)
        self.assertIn("--replay", replay)


if __name__ == "__main__":
    unittest.main()
