"""Post-commit notification contract used by the live dashboard bridge."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import unittest
from uuid import uuid4

from repository.event.ev_charger_state_event import EVChargerStateEvent
from transaction_scripts.stateful_event_storage.save_subscribed_data import EVChargerEventStore
from view.dashboard_live import DashboardLiveService


class _Dao:
    def __init__(self):
        self.committed = False
        self.ids = set()

    def ensure_tables(self): pass
    def event_exists(self, event_id): return event_id in self.ids
    def list_events(self, run_id, charger_id): return []
    def insert_event(self, event): self.ids.add(event.id); return True
    def update_latest_state(self, event, state): pass

    @contextmanager
    def transaction(self):
        yield
        self.committed = True


class EventStoreNotificationTests(unittest.TestCase):
    def _event(self):
        return EVChargerStateEvent(
            id=str(uuid4()), run_id="live-test-run", type="price_update",
            ts=datetime(2026, 10, 28, tzinfo=timezone.utc), object_id="1",
            payload={"price_per_kwh": 0.42},
        )

    def test_dashboard_wrapper_notifies_only_after_commit_and_not_for_a_duplicate(self):
        dao, calls = _Dao(), []
        service = DashboardLiveService.__new__(DashboardLiveService)
        service.store = EVChargerEventStore(dao)
        service.notify_committed = lambda event: calls.append((event.id, dao.committed))
        event = self._event()
        self.assertTrue(service._save_and_notify(event))
        self.assertEqual(calls, [(event.id, True)])
        self.assertFalse(service._save_and_notify(event))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
