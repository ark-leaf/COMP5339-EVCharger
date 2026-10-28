"""Deterministic evidence for the independent Task B/Task C MQTT bridge."""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import main_ass_2
from repository.event.ev_charger_state_event import EVChargerStateEvent
from view.mqtt_commit_coordinator import MqttCommitCoordinator


def event(run="run-a", charger=1):
    return EVChargerStateEvent(id=str(uuid4()), run_id=run, type="price_update",
        ts=datetime(2026, 10, 28, tzinfo=timezone.utc), object_id=str(charger),
        payload={"price_per_kwh": 0.42})


class ParallelCoordinatorTests(unittest.TestCase):
    def test_unified_startup_creates_exactly_two_named_subscribers_and_stops_both(self):
        created = []

        class Broker:
            def __enter__(self): return self
            def __exit__(self, *unused): return False

        class Subscriber:
            @classmethod
            def __class_getitem__(cls, unused):
                return cls
            def __init__(self, name, callback, *unused):
                self.name, self.callback = name, callback
                self.ready, self.stopping = threading.Event(), threading.Event()
                self.error = None
                created.append(self)
            def start(self): self.ready.set()
            def join(self, timeout=None): return None

        class Live:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def notify_committed(self, received): pass

        with (patch.object(main_ass_2.data_generator_daemon, "main"),
              patch.object(main_ass_2, "YSimpleMqttRepository", return_value=Broker()),
              patch.object(main_ass_2, "YMqttEventSubscriber", Subscriber),
              patch("view.dashboard_live.DashboardLiveService", Live),
              patch("view.dashboard_daemon.run_dashboard")):
            main_ass_2.main(["--external-broker", "--dashboard-delay", "0"])
        self.assertEqual([item.name for item in created], ["database-update", "dashboard-update"])
        self.assertTrue(all(item.stopping.is_set() for item in created))
        self.assertTrue(main_ass_2._commit_coordinator._closed.is_set())
        self.assertFalse(main_ass_2._commit_coordinator._worker.is_alive())

    def test_unified_startup_failure_stops_the_already_started_subscriber(self):
        created = []

        class Broker:
            def __enter__(self): return self
            def __exit__(self, *unused): return False

        class Subscriber:
            @classmethod
            def __class_getitem__(cls, unused):
                return cls
            def __init__(self, name, callback, *unused):
                self.name, self.callback = name, callback
                self.ready, self.stopping = threading.Event(), threading.Event()
                self.error = None
                created.append(self)
            def start(self):
                if self.name == "dashboard-update":
                    raise RuntimeError("injected start failure")
                self.ready.set()
            def join(self, timeout=None): return None

        class Live:
            def __init__(self, **kwargs): pass

        with (patch.object(main_ass_2.data_generator_daemon, "main"),
              patch.object(main_ass_2, "YSimpleMqttRepository", return_value=Broker()),
              patch.object(main_ass_2, "YMqttEventSubscriber", Subscriber),
              patch("view.dashboard_live.DashboardLiveService", Live)):
            with self.assertRaisesRegex(RuntimeError, "injected start failure"):
                main_ass_2.main(["--external-broker"])
        self.assertEqual(len(created), 2)
        self.assertTrue(created[0].stopping.is_set())
        self.assertFalse(created[1].stopping.is_set())

    def test_dashboard_arrival_before_blocked_database_commit_is_parallel_and_safe(self):
        arrived_at_store = threading.Event()
        release_store = threading.Event()
        dashboard_seen = threading.Event()
        notifications = []
        candidate = event()

        class BlockingStore:
            def save(self, received):
                arrived_at_store.set()
                release_store.wait(2)
                return True

        coordinator = MqttCommitCoordinator(notifications.append)
        with patch.object(main_ass_2, "event_store", BlockingStore()), patch.object(
                main_ass_2, "_commit_coordinator", coordinator):
            database = threading.Thread(target=main_ass_2.sub_database_update, args=(candidate,))
            database.start()
            self.assertTrue(arrived_at_store.wait(1))
            dashboard = threading.Thread(
                target=lambda: (main_ass_2.sub_dashboard(candidate), dashboard_seen.set()))
            dashboard.start()
            self.assertTrue(dashboard_seen.wait(1))
            self.assertEqual(notifications, [])
            release_store.set()
            database.join(2)
            dashboard.join(2)
        self.assertEqual(notifications, [candidate])

    def test_database_then_dashboard_notifies_once(self):
        calls, coordinator, candidate = [], MqttCommitCoordinator(), event()
        coordinator.set_notifier(calls.append)
        self.assertFalse(coordinator.committed(candidate))
        self.assertTrue(coordinator.dashboard_received(candidate))
        self.assertFalse(coordinator.dashboard_received(candidate))
        self.assertFalse(coordinator.committed(candidate))
        self.assertEqual(calls, [candidate])

    def test_failed_persistence_is_never_notified(self):
        calls, coordinator, candidate = [], MqttCommitCoordinator(), event()
        coordinator.set_notifier(calls.append)

        class FailingStore:
            def save(self, received):
                raise RuntimeError("injected database failure")

        with patch.object(main_ass_2, "event_store", FailingStore()), patch.object(
                main_ass_2, "_commit_coordinator", coordinator):
            main_ass_2.sub_dashboard(candidate)
            with self.assertRaisesRegex(RuntimeError, "injected database failure"):
                main_ass_2.sub_database_update(candidate)
        self.assertEqual(calls, [])
        self.assertEqual(coordinator.pending_count, 0)

    def test_duplicate_deliveries_do_not_duplicate_dashboard(self):
        calls, saves, candidate = [], [], event()
        coordinator = MqttCommitCoordinator(calls.append)

        class DeduplicatingStore:
            def save(self, received):
                saves.append(received.id)
                return len(saves) == 1

        with patch.object(main_ass_2, "event_store", DeduplicatingStore()), patch.object(
                main_ass_2, "_commit_coordinator", coordinator):
            main_ass_2.sub_dashboard(candidate)
            main_ass_2.sub_dashboard(candidate)
            main_ass_2.sub_database_update(candidate)
            main_ass_2.sub_database_update(candidate)
        self.assertEqual(len(saves), 2)
        self.assertEqual(calls, [candidate])

    def test_interleaved_runs_and_stations_join_only_same_event_id(self):
        calls, coordinator = [], MqttCommitCoordinator()
        coordinator.set_notifier(calls.append)
        first, second, third = event("run-a", 1), event("run-b", 2), event("run-a", 3)
        coordinator.dashboard_received(second)
        coordinator.committed(first)
        coordinator.dashboard_received(third)
        coordinator.committed(second)
        coordinator.dashboard_received(first)
        coordinator.committed(third)
        self.assertEqual([item.id for item in calls], [second.id, first.id, third.id])

    def test_high_frequency_state_is_bounded_and_committed_events_are_not_lost(self):
        calls = []
        coordinator = MqttCommitCoordinator(calls.append, max_pending=16, ttl_seconds=60)
        committed = [event("meter-run", index + 1) for index in range(100)]
        for item in committed:
            coordinator.committed(item)
            coordinator.dashboard_received(item)
        self.assertEqual(len(calls), 100)
        self.assertEqual(coordinator.pending_count, 0)
        for index in range(40):
            coordinator.dashboard_received(event("uncommitted", index + 1))
        self.assertLessEqual(coordinator.pending_count, 16)

    def test_overflow_and_expiration_recover_committed_events_observably(self):
        calls, gaps = [], []
        now = [0.0]
        coordinator = MqttCommitCoordinator(calls.append, max_pending=2, ttl_seconds=1,
                                            on_gap=lambda event, reason: gaps.append(reason),
                                            clock=lambda: now[0])
        first, second, third = event(), event(), event()
        coordinator.committed(first); coordinator.committed(second); coordinator.committed(third)
        coordinator.pending_count
        self.assertEqual(calls, [])
        now[0] = 2
        coordinator.pending_count
        self.assertTrue(gaps)

    def test_notification_failure_is_retained_and_recovers_without_duplicate_success(self):
        calls = []
        def flaky(received):
            if not calls:
                calls.append("failed")
                raise RuntimeError("temporary")
            calls.append(received.id)
        coordinator, candidate = MqttCommitCoordinator(flaky, max_notify_attempts=2), event()
        coordinator.committed(candidate)
        self.assertFalse(coordinator.dashboard_received(candidate))
        threading.Event().wait(.35)
        self.assertEqual(calls.count(candidate.id), 1)

    def test_permanent_failure_stops_at_limit_and_reports_once(self):
        attempts, gaps, done = [], [], threading.Event()
        candidate = event()
        coordinator = MqttCommitCoordinator(lambda received: attempts.append(received.id) or (_ for _ in ()).throw(RuntimeError("no")),
                                            max_notify_attempts=3, retry_delay=.01,
                                            on_gap=lambda received, reason: (gaps.append(reason), done.set()))
        coordinator.committed(candidate); coordinator.dashboard_received(candidate)
        self.assertTrue(done.wait(1))
        threading.Event().wait(.08)
        self.assertEqual(attempts, [candidate.id] * 3)
        self.assertEqual(len(gaps), 1)
        coordinator.close()

    def test_idle_ttl_expiry_is_reported_by_worker(self):
        expired = threading.Event()
        coordinator = MqttCommitCoordinator(max_pending=10, ttl_seconds=.02, retry_delay=.01,
            on_gap=lambda received, reason: expired.set())
        coordinator.dashboard_received(event())
        self.assertTrue(expired.wait(1))
        coordinator.close()

    def test_inflight_reservation_prevents_concurrent_duplicate_callbacks(self):
        entered, release, calls = threading.Event(), threading.Event(), []
        candidate = event()
        def blocking(received):
            calls.append(received.id); entered.set(); release.wait(1)
        coordinator = MqttCommitCoordinator(blocking)
        coordinator.committed(candidate)
        first = threading.Thread(target=lambda: coordinator.dashboard_received(candidate))
        first.start(); self.assertTrue(entered.wait(1))
        second = threading.Thread(target=lambda: coordinator.dashboard_received(candidate))
        second.start(); release.set(); first.join(1); second.join(1)
        self.assertEqual(calls, [candidate.id])
        coordinator.close()

    def test_gap_reporter_requests_real_snapshot_resync(self):
        class Live:
            def __init__(self): self.events = []
            def request_snapshot_resync(self, received): self.events.append(received.id)
        live, candidate = Live(), event()
        with patch.object(main_ass_2, "_dashboard_live_service", live):
            main_ass_2._report_coordinator_gap(candidate, "test recovery")
        self.assertEqual(live.events, [candidate.id])

    def test_dashboard_service_unified_mode_owns_no_subscriber_or_writer(self):
        from view.dashboard_live import DashboardLiveService
        service = DashboardLiveService(start_subscriber=False)
        self.assertIsNone(service.subscriber)
        self.assertIsNone(service.store)


if __name__ == "__main__":
    unittest.main()
