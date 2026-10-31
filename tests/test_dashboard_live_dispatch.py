"""MQTT-driven pages: each page reads the database once when it opens, then follows the subscriber."""
from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from entity.ev_charger import EVCharger
from event.ev_charger_state_event import EVChargerStateEvent
from view.dashboard_data import DashboardStation
from view.dashboard_live import DashboardLiveService
from view.dashboard_model import DashboardRunModel

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
STATIONS = (DashboardStation(EVCharger(1, charger_type="DC", number_of_plugs=2, rating_kw=50), ()),
            DashboardStation(EVCharger(2, charger_type="AC", number_of_plugs=1, rating_kw=7), ()))


def price(run_id, charger, minute, value=0.5):
    return EVChargerStateEvent(run_id=run_id, id=uuid4().hex, type="price_update",
                               ts=START + timedelta(minutes=minute), object_id=str(charger),
                               payload={"price_per_kwh": value})


def start(run_id, charger, minute, session="s1", connector=1):
    return EVChargerStateEvent(run_id=run_id, id=uuid4().hex, type="session_start",
                               ts=START + timedelta(minutes=minute), object_id=str(charger),
                               connector_id=connector, session_id=session, payload={"price_per_kwh": 0.5})


def meter(run_id, charger, minute, energy, session="s1", connector=1):
    return EVChargerStateEvent(run_id=run_id, id=uuid4().hex, type="meter",
                               ts=START + timedelta(minutes=minute), object_id=str(charger),
                               connector_id=connector, session_id=session,
                               payload={"power_kw": 50.0, "energy_kwh": energy})


class FakeDatabase:
    """Stands in for the DAO-backed loaders: stored events per run, and every run read."""
    def __init__(self, **stored):
        self.stored = {run_id: list(events) for run_id, events in stored.items()}
        self.reads = []

    def load_stations(self):
        return STATIONS, len(STATIONS)

    def load_run_ids(self):
        return tuple(sorted(self.stored, reverse=True))

    def load_run(self, run_id, charger_ids):
        self.reads.append(run_id)
        run_ids = self.load_run_ids()
        run_id = run_id if run_id is not None else next(iter(run_ids), None)
        if run_id is None:
            return run_ids, None
        model = DashboardRunModel(run_id, charger_ids)
        for item in self.stored.get(run_id, ()):
            model.apply(item)
        return run_ids, model


class FakeClient:
    def __init__(self):
        self.is_deleted, self.has_socket_connection = False, True
    def __enter__(self): return self
    def __exit__(self, *_): return False


class FakeView:
    def __init__(self, live_mode=True, fail=False):
        self.live_mode, self.fail = live_mode, fail
        self.rendered, self.run_options, self.sync_failed = [], [], False

    def apply_event_snapshot(self, events, changed=None, *, live=False):
        if self.fail:
            raise RuntimeError("injected page failure")
        self.rendered.append((events, changed))

    def update_run_options(self, run_ids, *, latest_live_run_id=None):
        self.run_options.append((tuple(run_ids), latest_live_run_id))

    def set_live_sync_failed(self):
        self.sync_failed = True


class DashboardLiveServiceTests(unittest.TestCase):
    def serve(self, scenario, database, clients):
        """Run scenario(service) on an event loop, as NiceGUI would, with the database faked."""
        async def run():
            with ExitStack() as stack:
                for name in ("load_stations", "load_run", "load_run_ids"):
                    stack.enter_context(patch(f"view.dashboard_live.{name}", getattr(database, name)))
                stack.enter_context(patch("view.dashboard_live.Client.instances", clients))
                service = DashboardLiveService()
                service.COALESCE_SECONDS = 0
                await scenario(service)
        asyncio.run(run())

    @staticmethod
    async def open(service, client_id, view, run_id=None):
        snapshot = await service.open_page(client_id, run_id)
        service.attach(client_id, view)
        return snapshot

    @staticmethod
    async def settle(service):
        """Wait until the batches receive() scheduled have been applied."""
        for _ in range(200):
            await asyncio.sleep(0.01)
            with service._lock:
                if not service._drain_scheduled and not service._inbox:
                    break
        await asyncio.sleep(0.02)

    def test_a_page_reads_the_database_once_then_follows_mqtt(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0), start("run-a", 1, 1)]})
        view, opened = FakeView(), []

        async def scenario(service):
            service.start()
            opened.append(await self.open(service, "page", view))
            service.receive(meter("run-a", 1, 2, 1.5))
            await self.settle(service)

        self.serve(scenario, database, {"page": FakeClient()})
        self.assertEqual(opened[0].events.active_session_count, 1)
        self.assertEqual(database.reads, ["run-a"])  # opening read the run; the meter reading did not
        events, changed = view.rendered[-1]
        self.assertEqual(changed, {1})
        self.assertEqual(events.active_sessions[0].energy_kwh, 1.5)
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 1, "s1")]], [1.5])

    def test_repeated_and_rejected_events_leave_the_page_alone(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0), start("run-a", 1, 1)]})
        view, reading = FakeView(), meter("run-a", 1, 2, 1.5)

        async def scenario(service):
            service.start()
            await self.open(service, "page", view)
            service.receive(reading)
            await self.settle(service)
            renders = len(view.rendered)
            for item in (reading,                                 # MQTT redelivery
                         meter("run-a", 1, 3, 1.0),               # energy decreases; storage rejects it
                         start("run-a", 1, 4, session="s2"),      # connector 1 is occupied
                         price("run-a", 99, 5)):                  # not a station in the database
                service.receive(item)
            await self.settle(service)
            self.assertEqual(len(view.rendered), renders)

        self.serve(scenario, database, {"page": FakeClient()})

    def test_a_live_page_follows_a_new_run_and_a_history_page_only_lists_it(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0)]})
        live, history = FakeView(), FakeView(live_mode=False)

        async def scenario(service):
            service.start()
            await self.open(service, "live", live)
            await self.open(service, "history", history, run_id="run-a")
            for item in (price("run-b", 2, 0, 0.7), start("run-b", 2, 1)):
                service.receive(item)
            await self.settle(service)

        self.serve(scenario, database, {"live": FakeClient(), "history": FakeClient()})
        events, changed = live.rendered[-1]
        self.assertEqual((events.run_id, changed), ("run-b", None))
        self.assertEqual(events.active_session_count, 1)  # from MQTT, though storage has saved none of run B
        self.assertEqual(live.run_options[-1], (("run-b", "run-a"), "run-b"))
        self.assertEqual(history.rendered, [])
        self.assertEqual(history.run_options[-1], (("run-b", "run-a"), "run-b"))

    def test_a_page_opened_mid_run_includes_events_storage_has_not_saved(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0)]})
        saved, unsaved = [price("run-b", 1, 0), start("run-b", 1, 1)], meter("run-b", 1, 2, 0.8)
        opened = []

        async def scenario(service):
            service.start()
            for item in saved + [unsaved]:
                service.receive(item)
            await self.settle(service)
            database.stored["run-b"] = saved  # storage is one event behind the dashboard subscriber
            opened.append(await self.open(service, "late", FakeView()))

        self.serve(scenario, database, {"late": FakeClient()})
        events = opened[0].events
        self.assertEqual((events.run_id, events.run_ids[0]), ("run-b", "run-b"))
        self.assertEqual(events.analytics.total_events, 3)  # two stored and one replayed, none twice
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 1, "s1")]], [0.8])

    def test_a_disconnected_page_keeps_up_and_renders_fully_when_back(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0), start("run-a", 1, 1)]})
        view, client = FakeView(), FakeClient()

        async def scenario(service):
            service.start()
            await self.open(service, "page", view)
            client.has_socket_connection = False
            service.receive(meter("run-a", 1, 2, 0.4))
            await self.settle(service)
            self.assertEqual(view.rendered, [])
            client.has_socket_connection = True
            service.receive(meter("run-a", 1, 3, 0.9))
            await self.settle(service)

        self.serve(scenario, database, {"page": client})
        events, changed = view.rendered[-1]
        self.assertIsNone(changed)  # a render was missed, so the whole page is refreshed
        self.assertEqual([point.energy_kwh for point in events.meter_points[(1, 1, "s1")]], [0.4, 0.9])

    def test_a_broken_page_does_not_stop_the_others(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0)]})
        broken, healthy = FakeView(fail=True), FakeView()

        async def scenario(service):
            service.start()
            await self.open(service, "broken", broken)
            await self.open(service, "healthy", healthy)
            service.receive(price("run-a", 2, 3, 0.6))
            await self.settle(service)

        self.serve(scenario, database, {"broken": FakeClient(), "healthy": FakeClient()})
        self.assertEqual(healthy.rendered[-1][1], {2})

    def test_a_storage_failure_marks_open_and_later_pages(self):
        database = FakeDatabase(**{"run-a": [price("run-a", 1, 0)]})
        early, late = FakeView(), FakeView()

        async def scenario(service):
            service.start()
            await self.open(service, "early", early)
            service.report_sync_failed()
            await self.settle(service)
            await self.open(service, "late", late)

        self.serve(scenario, database, {"early": FakeClient(), "late": FakeClient()})
        self.assertTrue(early.sync_failed)
        self.assertTrue(late.sync_failed)

    def test_events_received_before_the_server_starts_reach_the_first_page(self):
        database, opened = FakeDatabase(), []

        async def scenario(service):
            service.receive(price("run-a", 1, 0))  # NiceGUI's loop is not running yet
            service.start()
            await self.settle(service)
            opened.append(await self.open(service, "page", FakeView()))

        self.serve(scenario, database, {"page": FakeClient()})
        self.assertEqual(opened[0].events.run_id, "run-a")
        self.assertEqual(opened[0].events.analytics.total_events, 1)


if __name__ == "__main__":
    unittest.main()
