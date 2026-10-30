"""Live state for every open dashboard page, advanced only by the dashboard-update subscriber.

A page reads its stations and its run's stored history when it opens. After that, the
MQTT events that DashboardDaemon's subscriber passes to receive() are batched onto
NiceGUI's event loop, where each page applies them to its own DashboardRunModel and
re-renders. No database query runs per event.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass

from nicegui import Client

from repository.event.ev_charger_state_event import EVChargerStateEvent
from view.dashboard_data import DashboardSnapshot, DashboardStation, load_run, load_run_ids, load_stations
from view.dashboard_model import DashboardEventSnapshot, DashboardRunModel


logger = logging.getLogger(__name__)


@dataclass
class DashboardPage:
    """One open browser page and the run model it renders."""
    client_id: str
    stations: tuple[DashboardStation, ...] = ()
    total_chargers: int = 0
    run_ids: tuple[str, ...] = ()
    model: DashboardRunModel | None = None
    view: object | None = None  # Set by attach() once the page is built.
    stale: bool = False         # A render was skipped while the browser was disconnected.

    @property
    def run_id(self) -> str | None:
        return None if self.model is None else self.model.run_id

    @property
    def charger_ids(self) -> tuple[int, ...]:
        return tuple(station.charger.charger_id for station in self.stations)

    def snapshot(self) -> DashboardSnapshot:
        events = DashboardEventSnapshot.no_event_data() if self.model is None else self.model.snapshot(self.run_ids)
        return DashboardSnapshot(self.total_chargers, self.stations, events)


def _read_page(run_id: str | None):
    """The database reads for a page that is opening; runs in a worker thread."""
    stations, total_chargers = load_stations()
    run_ids, model = load_run(run_id, (station.charger.charger_id for station in stations))
    return stations, total_chargers, run_ids, model


class DashboardLiveService:
    """Batches MQTT events onto NiceGUI's event loop and keeps every open page current."""

    COALESCE_SECONDS = 0.10  # One render per page for a burst of meter events.
    RECENT_EVENTS = 10_000   # Replayed into pages that open before storage has caught up.

    def __init__(self):
        # The lock guards what the subscriber and storage threads share with the event loop.
        self._lock = threading.Lock()
        self._inbox: list[EVChargerStateEvent] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drain_scheduled = False
        self._sync_failed = False
        # Only NiceGUI's event loop touches the rest.
        self._pages: dict[str, DashboardPage] = {}
        self._recent: deque[EVChargerStateEvent] = deque(maxlen=self.RECENT_EVENTS)
        self._known_runs: set[str] = set()
        self._observed_runs: list[str] = []
        self._latest_run_id: str | None = None
        self._reported_failures: set[tuple[str, str, str]] = set()

    # Called from other threads.

    def receive(self, event: EVChargerStateEvent) -> None:
        """The dashboard-update subscriber's callback: queue the event for every page."""
        with self._lock:
            self._inbox.append(event)
            loop = None if self._drain_scheduled else self._loop
            self._drain_scheduled = self._drain_scheduled or loop is not None
        if loop is not None:
            asyncio.run_coroutine_threadsafe(self._drain(), loop).add_done_callback(self._log_task_error)

    def report_sync_failed(self) -> None:
        """Storage has stopped: mark every page, including pages opened later, as out of sync."""
        with self._lock:
            self._sync_failed = True
            loop = self._loop
        if loop is not None:
            asyncio.run_coroutine_threadsafe(self._mark_sync_failed(), loop).add_done_callback(self._log_task_error)

    # Called on NiceGUI's event loop.

    def start(self) -> None:
        """NiceGUI startup hook: learn the stored runs, then deliver events that arrived earlier."""
        try:
            run_ids = load_run_ids()
        except Exception:
            logger.exception("Could not read the stored runs")
            run_ids = ()
        self._known_runs.update(run_ids)
        self._latest_run_id = next(iter(run_ids), None)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._loop = loop
            pending = bool(self._inbox) and not self._drain_scheduled
            self._drain_scheduled = self._drain_scheduled or pending
        if pending:
            loop.create_task(self._drain()).add_done_callback(self._log_task_error)

    async def open_page(self, client_id: str, run_id: str | None = None) -> DashboardSnapshot:
        """Read a page's stations and run history from the database; attach() then makes it live.

        Without a known run_id the page opens on the run this server most recently started
        receiving, or else on the latest stored run.
        """
        page = self._pages[client_id] = DashboardPage(client_id)
        target = run_id if run_id in self._known_runs else self._latest_run_id
        page.stations, page.total_chargers, page.run_ids, page.model = await asyncio.to_thread(_read_page, target)
        self._catch_up(page)
        return page.snapshot()

    def attach(self, client_id: str, view) -> None:
        """Hand an opened page its view; MQTT events update it from now on."""
        page = self._pages.get(client_id)
        if page is None:
            return
        page.view = view
        with self._lock:
            failed = self._sync_failed
        if failed:
            # attach() runs in the page's NiceGUI context, before its browser connects.
            try:
                view.set_live_sync_failed()
            except Exception as exc:
                self._report_failure("Could not show LIVE synchronization failure", exc)

    def close_page(self, client_id: str) -> None:
        self._pages.pop(client_id, None)

    def select_run(self, client_id: str, run_id: str) -> DashboardSnapshot:
        """A page's run selector or Live button: read that run's history from the database."""
        page = self._pages[client_id]
        page.run_ids, page.model = load_run(run_id, page.charger_ids)
        self._catch_up(page)
        return page.snapshot()

    def _with_observed_runs(self, run_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Stored runs, preceded by runs seen on MQTT that storage has not saved yet, newest first."""
        return tuple(run for run in reversed(self._observed_runs) if run not in run_ids) + tuple(run_ids)

    def _catch_up(self, page: DashboardPage) -> None:
        """Add recent MQTT events that storage may not have saved yet (repeats are ignored)."""
        if page.model is not None:
            for event in self._recent:
                page.model.apply(event)
        page.run_ids = self._with_observed_runs(page.run_ids)

    async def _drain(self) -> None:
        """Apply a burst of MQTT events to every open page, then re-render each page once."""
        try:
            await asyncio.sleep(self.COALESCE_SECONDS)
            while True:
                with self._lock:
                    events, self._inbox = self._inbox, []
                if not events:
                    return
                new_runs = self._track(events)
                for page in tuple(self._pages.values()):
                    await self._update_page(page, events, new_runs)
        finally:
            # Events that arrived after the last batch was taken still need a drain.
            with self._lock:
                self._drain_scheduled = again = bool(self._inbox)
            if again:
                asyncio.get_running_loop().create_task(self._drain()).add_done_callback(self._log_task_error)

    def _track(self, events: list[EVChargerStateEvent]) -> list[str]:
        """Keep recent events and return the runs this server sees for the first time."""
        new_runs = []
        for event in events:
            self._recent.append(event)
            if event.run_id not in self._known_runs:
                self._known_runs.add(event.run_id)
                self._observed_runs.append(event.run_id)
                self._latest_run_id = event.run_id
                new_runs.append(event.run_id)
        return new_runs

    async def _update_page(self, page: DashboardPage, events: list[EVChargerStateEvent], new_runs: list[str]) -> None:
        client = Client.instances.get(page.client_id)
        if client is None or client.is_deleted:
            self._pages.pop(page.client_id, None)
            return
        if page.view is None:
            return  # Still opening; it catches up from the recent events before attach().
        try:
            follow = new_runs[-1] if new_runs and getattr(page.view, "live_mode", True) else None
            if follow is not None and follow != page.run_id:
                # A Live page moves to a run that started while it was open. History pages stay
                # pinned, and delayed events of an older run never take a Live page back.
                page.run_ids, page.model = await asyncio.to_thread(load_run, follow, page.charger_ids)
                self._catch_up(page)
                changed = None  # Every marker may change.
            else:
                changed = {event.charger_id for event in events if page.model is not None and page.model.apply(event)}
                if new_runs:
                    page.run_ids = self._with_observed_runs(page.run_ids)
                elif not changed and not page.stale:
                    return
            if not client.has_socket_connection:
                # NiceGUI keeps a disconnected client during its reconnect grace period. Leave its
                # elements alone and render the whole page once the browser is back.
                page.stale = True
                return
            with client:
                if changed is None or changed or page.stale:
                    page.view.apply_event_snapshot(page.snapshot().events, None if page.stale else changed, live=True)
                page.view.update_run_options(page.run_ids, latest_live_run_id=self._latest_run_id)
            page.stale = False
        except Exception as exc:
            # One broken page must not stop the others from updating.
            self._report_failure(f"Could not update dashboard page {page.client_id}", exc)

    async def _mark_sync_failed(self) -> None:
        for page in tuple(self._pages.values()):
            client = Client.instances.get(page.client_id)
            if page.view is None or client is None or client.is_deleted or not client.has_socket_connection:
                continue
            try:
                with client:
                    page.view.set_live_sync_failed()
            except Exception as exc:
                self._report_failure("Could not show LIVE synchronization failure", exc)

    def _report_failure(self, context: str, exc: Exception) -> None:
        """Log each distinct failure once, without a traceback that could re-enter NiceGUI's reporting."""
        signature = context, type(exc).__name__, str(exc)
        if signature not in self._reported_failures:
            self._reported_failures.add(signature)
            logger.error("%s: %s: %s", *signature)

    @staticmethod
    def _log_task_error(future) -> None:
        if not future.cancelled() and future.exception() is not None:
            exc = future.exception()
            logger.error("Dashboard update failed: %s: %s", type(exc).__name__, exc)
