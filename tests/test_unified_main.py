"""Unit coverage for the unified main_ass_2 post-commit bridge."""
from __future__ import annotations

from datetime import datetime, timezone
import threading
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
            def notify_committed(self, event): self.events.append(event); return True

        coordinator = main_ass_2.MqttCommitCoordinator()
        dashboard = Dashboard()
        first = self._event()
        with patch.object(main_ass_2, "event_store", Store(True)), \
             patch.object(main_ass_2, "_dashboard_live_service", dashboard), \
             patch.object(main_ass_2, "_commit_coordinator", coordinator):
            coordinator.set_notifier(main_ass_2._notify_dashboard_after_join)
            main_ass_2.sub_database_update(first)
            self.assertEqual(dashboard.events, [])
            main_ass_2.sub_dashboard(first)
        self.assertEqual(len(dashboard.events), 1)

        coordinator = main_ass_2.MqttCommitCoordinator()
        dashboard = Dashboard()
        second = self._event()
        with patch.object(main_ass_2, "event_store", Store(False)), \
             patch.object(main_ass_2, "_dashboard_live_service", dashboard), \
             patch.object(main_ass_2, "_commit_coordinator", coordinator):
            coordinator.set_notifier(main_ass_2._notify_dashboard_after_join)
            main_ass_2.sub_dashboard(second)
            main_ass_2.sub_database_update(second)
        self.assertEqual(dashboard.events, [])

    def test_replay_removes_second_broker_flag_and_keeps_one_publisher(self):
        arguments = ["--limit", "3", "--inline-broker", "--publish"]
        self.assertNotIn("--publish", main_ass_2._prepare_arguments(arguments))
        replay = main_ass_2._replay_arguments(arguments, "localhost", 1883)
        self.assertNotIn("--inline-broker", replay)
        self.assertEqual(replay.count("--publish"), 1)
        self.assertIn("--replay", replay)

    def test_reconciliation_rejects_first_middle_and_final_persistence_failures(self):
        """An ACK is not a successful replay until Task B/C reach terminal state."""
        for failure_index in (0, 1, 2):
            with self.subTest(failure_index=failure_index):
                events = [self._event() for _ in range(3)]
                reconciliation = main_ass_2._ReplayReconciliation()
                coordinator = main_ass_2.MqttCommitCoordinator(lambda received: None)

                class Store:
                    def __init__(self): self.calls = 0
                    def save(self, received):
                        current, self.calls = self.calls, self.calls + 1
                        if current == failure_index:
                            raise RuntimeError("injected persistence failure")
                        return True

                with (patch.object(main_ass_2, "event_store", Store()),
                      patch.object(main_ass_2, "_commit_coordinator", coordinator),
                      patch.object(main_ass_2, "_replay_reconciliation", reconciliation),
                      patch.object(main_ass_2, "_fatal_persistence", None)):
                    for item in events:
                        reconciliation.record("broker_acknowledged", item)
                    for index, item in enumerate(events):
                        if index == failure_index:
                            with self.assertRaisesRegex(RuntimeError, "injected persistence failure"):
                                main_ass_2.sub_database_update(item)
                            break
                        main_ass_2.sub_database_update(item)
                        main_ass_2.sub_dashboard(item)
                    self.assertFalse(reconciliation.successful())
                    self.assertFalse(main_ass_2._wait_for_reconciliation(
                        reconciliation, threading.Event(), timeout=.02))
                    self.assertIn(events[failure_index].id, reconciliation.task_b_failed)
                coordinator.close()

    def test_queued_broker_acks_are_accounted_after_task_b_failure(self):
        """Backlog is reported, rather than assuming only one ACK can be uncommitted."""
        events = [self._event() for _ in range(4)]
        reconciliation = main_ass_2._ReplayReconciliation()
        coordinator = main_ass_2.MqttCommitCoordinator(lambda received: None)

        class Store:
            def save(self, received):
                raise RuntimeError("first queue failure")

        with (patch.object(main_ass_2, "event_store", Store()),
              patch.object(main_ass_2, "_commit_coordinator", coordinator),
              patch.object(main_ass_2, "_replay_reconciliation", reconciliation),
              patch.object(main_ass_2, "_fatal_persistence", None)):
            for item in events:
                reconciliation.record("broker_acknowledged", item)
            with self.assertRaisesRegex(RuntimeError, "first queue failure"):
                main_ass_2.sub_database_update(events[0])
            outstanding = reconciliation.unresolved()["task_b_outstanding"]
            self.assertEqual(outstanding, {item.id for item in events[1:]})
            self.assertFalse(reconciliation.successful())
        coordinator.close()

    def test_user_cancellation_prevents_false_success_without_waiting_for_mqtt(self):
        reconciliation = main_ass_2._ReplayReconciliation()
        cancelled = threading.Event(); cancelled.set()
        candidate = self._event()
        reconciliation.record("broker_acknowledged", candidate)
        self.assertFalse(main_ass_2._wait_for_reconciliation(reconciliation, cancelled, timeout=.02))
        self.assertFalse(reconciliation.successful())

    def test_notification_is_accounted_only_after_service_accepts_it(self):
        candidate = self._event()
        ledger = main_ass_2._ReplayReconciliation()

        class RejectingDashboard:
            def notify_committed(self, event): return False

        with (patch.object(main_ass_2, "_dashboard_live_service", RejectingDashboard()),
              patch.object(main_ass_2, "_replay_reconciliation", ledger)):
            with self.assertRaisesRegex(RuntimeError, "could not schedule"):
                main_ass_2._notify_dashboard_after_join(candidate)
        self.assertEqual(ledger.dashboard_notified, set())
        self.assertEqual(ledger.coordinator_matched, {candidate.id})

    def test_empty_replay_is_not_synchronized(self):
        self.assertFalse(main_ass_2._ReplayReconciliation().successful())


if __name__ == "__main__":
    unittest.main()
