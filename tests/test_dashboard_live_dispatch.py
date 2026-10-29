"""Run-isolated, event-triggered Dashboard view dispatch tests."""
from __future__ import annotations

import unittest
import asyncio
import threading
from unittest.mock import patch

from view.dashboard_live import DashboardLiveService, RegisteredView


class DashboardLiveDispatchTests(unittest.TestCase):
    def test_only_matching_run_accepts_a_committed_snapshot(self):
        self.assertTrue(DashboardLiveService._accepts_committed_run("run-new", "run-new"))
        self.assertFalse(DashboardLiveService._accepts_committed_run("run-other", "run-new"))

    def test_empty_dashboard_adopts_its_first_committed_run(self):
        self.assertTrue(DashboardLiveService._accepts_committed_run(None, "run-new"))

    def test_register_applies_existing_sticky_failure_to_new_view(self):
        service = DashboardLiveService.__new__(DashboardLiveService)
        service._lock, service._views, service._sync_failed = threading.Lock(), {}, True
        class View:
            def __init__(self): self.failed = False
            def set_live_sync_failed(self): self.failed = True
        view = View()
        service._register_view("new-client", view)
        self.assertTrue(view.failed)
        self.assertIn("new-client", service._views)

    def test_delivery_exception_releases_latch_and_a_later_batch_runs(self):
        service = DashboardLiveService.__new__(DashboardLiveService)
        service._lock = threading.Lock()
        service._pending_chargers = {"run-a": {1}}
        service._delivery_scheduled = True
        attempts = []

        async def deliver(run_id, charger_ids):
            attempts.append((run_id, frozenset(charger_ids)))
            if len(attempts) == 1:
                raise RuntimeError("injected refresh failure")

        service._deliver = deliver
        asyncio.run(service._drain_pending())
        self.assertEqual(attempts, [("run-a", frozenset({1})), ("run-a", frozenset({1}))])
        self.assertFalse(service._delivery_scheduled)

        # This models a later successful notify_committed scheduling a new drain.
        service._pending_chargers = {"run-b": {2}}
        service._delivery_scheduled = True
        asyncio.run(service._drain_pending())
        self.assertEqual(attempts[-1], ("run-b", frozenset({2})))
        self.assertFalse(service._delivery_scheduled)

    def test_broken_client_does_not_block_healthy_client_or_later_recovery(self):
        class ClientContext:
            is_deleted = False
            has_socket_connection = True
            def __enter__(self): return self
            def __exit__(self, *_): return False

        class View:
            def __init__(self, fail=False):
                self.fail, self.applied, self.options = fail, 0, []
                self.snapshot = type("Snapshot", (), {"events": type("Events", (), {"run_id": "run-a"})()})()

            def apply_event_snapshot(self, snapshot, chargers, *, live):
                self.applied += 1
                if self.fail:
                    raise RuntimeError("injected page failure")

            def update_run_options(self, run_ids, **kwargs): self.options.append((run_ids, kwargs))

        class Query:
            def list_run_ids(self): return ("run-a",)
            def load_snapshot(self, run_id): return f"snapshot:{run_id}"

        service = DashboardLiveService.__new__(DashboardLiveService)
        service._lock = threading.Lock()
        service._delivery_lock = asyncio.Lock()
        service._query = Query()
        broken, healthy = View(fail=True), View()
        service._views = {
            "client-a": RegisteredView("client-a", broken),
            "client-b": RegisteredView("client-b", healthy),
        }
        clients = {"client-a": ClientContext(), "client-b": ClientContext()}
        with patch("view.dashboard_live.Client.instances", clients):
            asyncio.run(service._deliver("run-a", {17}))
            self.assertEqual(healthy.applied, 1)
            self.assertEqual(broken.applied, 1)
            # The same registered page can recover on a later committed event.
            broken.fail = False
            asyncio.run(service._deliver("run-a", {17}))
        self.assertEqual(broken.applied, 2)
        self.assertEqual(healthy.applied, 2)

    def test_new_run_follows_only_live_client_and_records_arrival_as_live_target(self):
        class ClientContext:
            is_deleted = False
            has_socket_connection = True
            def __enter__(self): return self
            def __exit__(self, *_): return False

        class View:
            def __init__(self, run_id, live_mode):
                self.live_mode, self.applied, self.options = live_mode, [], []
                self.snapshot = type("Snapshot", (), {"events": type("Events", (), {"run_id": run_id})()})()
            def apply_event_snapshot(self, snapshot, *_args, **_kwargs): self.applied.append(snapshot)
            def update_run_options(self, run_ids, **kwargs): self.options.append((run_ids, kwargs))

        class Query:
            # A is deliberately first by simulated time, while B is latest by arrival.
            def list_run_ids(self): return ("run-a", "run-b")
            def load_snapshot(self, run_id): return f"snapshot:{run_id}"

        service = DashboardLiveService.__new__(DashboardLiveService)
        service._lock = threading.Lock(); service._delivery_lock = asyncio.Lock(); service._query = Query()
        service._new_run_ids = {"run-b"}; service._latest_observed_run_id = "run-b"
        live, history = View("run-a", True), View("run-a", False)
        service._views = {"live": RegisteredView("live", live), "history": RegisteredView("history", history)}
        with patch("view.dashboard_live.Client.instances", {"live": ClientContext(), "history": ClientContext()}):
            asyncio.run(service._deliver("run-b", {1}))
        self.assertEqual(live.applied, ["snapshot:run-b"])
        self.assertEqual(history.applied, [])
        self.assertEqual(history.options[-1][1]["latest_live_run_id"], "run-b")
        self.assertNotIn("run-b", service._new_run_ids)

    def test_disconnected_client_is_not_mutated_and_can_resume_after_reconnect(self):
        class ClientContext:
            def __init__(self, connected):
                self.has_socket_connection, self.is_deleted = connected, False
            def __enter__(self): return self
            def __exit__(self, *_): return False

        class View:
            def __init__(self):
                self.snapshot = type("Snapshot", (), {"events": type("Events", (), {"run_id": "run-a"})()})()
                self.applied = 0
            def apply_event_snapshot(self, *_args, **_kwargs): self.applied += 1
            def update_run_options(self, *_args, **_kwargs): pass

        class Query:
            def list_run_ids(self): return ("run-a",)
            def load_snapshot(self, run_id): return f"snapshot:{run_id}"

        service = DashboardLiveService.__new__(DashboardLiveService)
        service._lock = threading.Lock(); service._delivery_lock = asyncio.Lock(); service._query = Query()
        service._new_run_ids = set(); service._latest_observed_run_id = "run-a"
        view, client = View(), ClientContext(False)
        service._views = {"client": RegisteredView("client", view)}
        with patch("view.dashboard_live.Client.instances", {"client": client}):
            asyncio.run(service._deliver("run-a", {1}))
            self.assertEqual(view.applied, 0)
            self.assertIn("client", service._views)
            client.has_socket_connection = True
            asyncio.run(service._deliver("run-a", {1}))
        self.assertEqual(view.applied, 1)


if __name__ == "__main__":
    unittest.main()
