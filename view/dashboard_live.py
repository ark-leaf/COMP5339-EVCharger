"""Event-driven bridge from the committed MQTT store to connected NiceGUI views."""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from nicegui import Client, core, ui

from config import DB_DATA
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.repo_config import mqtt_config
from repository.utils import duckdb_utils
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber
from transaction_scripts.stateful_event_storage.save_subscribed_data import EVChargerEventStore
from view.dashboard_queries import DashboardQueryService
from view.dashboard_data import DashboardSnapshot, load_dashboard_snapshot


logger = logging.getLogger(__name__)


class SharedWriterQueryRepository:
    """Read via DuckDB's already-open shared writer connection, under its lock."""
    def fetch_all(self, sql, params=None) -> list[dict]:
        with duckdb_utils.cursor() as cursor:
            result = cursor.execute(sql, params or [])
            columns = [column[0] for column in result.description]
            return [dict(zip(columns, row)) for row in result.fetchall()]


@dataclass
class RegisteredView:
    client_id: str
    view: object


class DashboardLiveService:
    """Broadcast committed events, optionally owning the MQTT/EventStore writer."""
    def __init__(self, *, host: str | None = None, port: int | None = None, db_path=None,
                 start_subscriber: bool = True):
        settings = mqtt_config()
        self.host, self.port = host or settings["host"], port or settings["port"]
        self._lock = threading.Lock()
        self._views: dict[str, RegisteredView] = {}
        self._pending_chargers: dict[str, set[int]] = {}
        self._known_run_ids: set[str] = set()
        self._new_run_ids: set[str] = set()
        self._latest_observed_run_id: str | None = None
        self._reported_delivery_errors: set[tuple[str, str, str]] = set()
        self._delivery_scheduled = False
        self._db_path = Path(db_path or DB_DATA).resolve()
        # Yeh's repository owns one configured shared writer connection and
        # deliberately has no runtime database-path override.  A different
        # ``--db`` would otherwise let the page read one file while EventStore
        # persisted MQTT events into another.
        if self._db_path != Path(DB_DATA).resolve():
            raise ValueError("Dashboard --db must match config.DB_DATA when live MQTT storage is enabled")
        self._writer_reads_ready = False
        self._static_snapshot: DashboardSnapshot | None = None
        self._delivery_lock = asyncio.Lock()
        self._query = DashboardQueryService(SharedWriterQueryRepository())
        self._owns_subscriber = start_subscriber
        self.store = EVChargerEventStore() if start_subscriber else None
        self.subscriber = (YMqttEventSubscriber[EVChargerStateEvent](
            "dashboard-live-store", self._save_and_notify, self.host, self.port, EVChargerStateEvent)
            if start_subscriber else None)

    def start(self) -> None:
        # Read static data before the subscriber opens DuckDB's shared writer.
        # This cache makes a browser reconnect compatible with that writer.
        try:
            self._load_static_snapshot()
        except Exception:
            # The page factory will render its existing actionable database
            # error state. Do not make NiceGUI itself fail to start first.
            logger.exception("Could not preload dashboard static data")
        # Subsequent event reads must use Yeh's one shared writer connection.
        # It is opened lazily by the EventStore or the first dashboard query.
        self._writer_reads_ready = True
        try:
            # This baseline is arrival-independent: subsequent first commits
            # are the only events permitted to move a Live view to a new run.
            initial_runs = self._query.list_run_ids()
            self._known_run_ids = set(initial_runs)
            # Before this process receives a new commit, the persisted query's
            # selected default is the only sensible fallback.
            self._latest_observed_run_id = initial_runs[0] if initial_runs else None
        except Exception:
            logger.exception("Could not establish dashboard run baseline")
        if self.subscriber is not None and not self.subscriber.is_alive():
            self.subscriber.start()

    def stop(self) -> None:
        if self.subscriber is None:
            return
        self.subscriber.stopping.set()
        if self.subscriber.is_alive():
            self.subscriber.join(timeout=10)

    def load_snapshot(self, db_path, *, run_id: str | None = None) -> DashboardSnapshot:
        """Return a reconnect-safe initial snapshot for a NiceGUI page.

        Static charger metadata is cached before the shared event writer opens.
        Event state is subsequently read through that same writer connection,
        avoiding DuckDB's read-only/read-write file-lock conflict.
        """
        static = self._load_static_snapshot(db_path)
        if not self._writer_reads_ready:
            snapshot = load_dashboard_snapshot(db_path, run_id=run_id)
            logger.info("Live dashboard loader requested run_id=%s resolved run_id=%s", run_id, snapshot.events.run_id)
            return snapshot
        events = self._query.load_snapshot(run_id)
        logger.info("Live dashboard loader requested run_id=%s resolved run_id=%s", run_id, events.run_id)
        return DashboardSnapshot(
            total_chargers=static.total_chargers,
            stations=static.stations,
            events=events,
        )

    def _save_and_notify(self, event: EVChargerStateEvent) -> bool:
        """Notify views only after Yeh's EventStore has committed one new event.

        Yeh's EventStore intentionally exposes no observer constructor hook.
        This Dashboard-owned wrapper preserves that boundary: a failed,
        invalid, or duplicate event returns without scheduling any UI update.
        """
        if self.store is None:
            raise RuntimeError("This DashboardLiveService receives externally committed events")
        stored = self.store.save(event)
        if stored:
            self.notify_committed(event)
        return stored

    def _load_static_snapshot(self, db_path=None) -> DashboardSnapshot:
        if self._static_snapshot is None:
            self._static_snapshot = load_dashboard_snapshot(db_path or self._db_path)
        return self._static_snapshot

    def register(self, view) -> None:
        client = ui.context.client
        with self._lock:
            self._views[client.id] = RegisteredView(client.id, view)

    def notify_committed(self, event: EVChargerStateEvent) -> None:
        """Called by the subscriber thread after ``save`` commits successfully."""
        if core.loop is not None and core.loop.is_running():
            with self._lock:
                if event.run_id not in self._known_run_ids:
                    self._known_run_ids.add(event.run_id)
                    self._new_run_ids.add(event.run_id)
                    self._latest_observed_run_id = event.run_id
                self._pending_chargers.setdefault(event.run_id, set()).add(event.charger_id)
                if self._delivery_scheduled:
                    return
                self._delivery_scheduled = True
            future = asyncio.run_coroutine_threadsafe(self._drain_pending(), core.loop)
            future.add_done_callback(self._report_delivery_error)

    @staticmethod
    def _report_delivery_error(future) -> None:
        try:
            future.result()
        except Exception as exc:
            # This callback is outside the original exception context. Logging
            # a full nested traceback here can recursively re-enter NiceGUI's
            # exception reporting when the browser socket is already gone.
            logger.error("Could not deliver a committed dashboard update: %s: %s",
                         type(exc).__name__, exc)

    def _report_delivery_failure(self, context: str, exc: Exception) -> None:
        """Record one bounded, non-recursive diagnostic per distinct failure."""
        signature = (context, type(exc).__name__, str(exc))
        reported = getattr(self, "_reported_delivery_errors", None)
        if reported is None:
            self._reported_delivery_errors = reported = set()
        if signature in reported:
            return
        reported.add(signature)
        logger.error("%s: %s: %s", context, type(exc).__name__, exc)

    @staticmethod
    def _accepts_committed_run(selected_run_id: str | None, committed_run_id: str) -> bool:
        """Only an unselected page may adopt its first newly committed run."""
        return selected_run_id is None or selected_run_id == committed_run_id

    async def _drain_pending(self) -> None:
        """Coalesce a short MQTT burst into one snapshot/UI update per run.

        This is event-triggered batching, not database polling. It prevents fast
        meter streams from scheduling thousands of full snapshots on the loop.
        """
        retries: dict[str, int] = {}
        try:
            await asyncio.sleep(0.10)
            while True:
                with self._lock:
                    pending, self._pending_chargers = self._pending_chargers, {}
                if not pending:
                    return
                retry_once: dict[str, set[int]] = {}
                for run_id, charger_ids in pending.items():
                    try:
                        await self._deliver(run_id, charger_ids)
                    except Exception as exc:
                        # One run's failed UI/database refresh must not prevent
                        # other runs from being delivered in the same batch.
                        self._report_delivery_failure(f"Could not deliver live update for run {run_id}", exc)
                        if retries.get(run_id, 0) == 0:
                            retries[run_id] = 1
                            retry_once[run_id] = charger_ids
                if retry_once:
                    # Preserve a failed batch once, but never spin forever.
                    await asyncio.sleep(0.25)
                    with self._lock:
                        for run_id, charger_ids in retry_once.items():
                            self._pending_chargers.setdefault(run_id, set()).update(charger_ids)
        finally:
            # Always release the scheduling latch. Events received in the tiny
            # gap before this block are explicitly scheduled on this loop.
            with self._lock:
                reschedule = bool(self._pending_chargers)
                self._delivery_scheduled = reschedule
            if reschedule:
                task = asyncio.create_task(self._drain_pending())
                task.add_done_callback(self._report_delivery_error)

    async def _deliver(self, committed_run_id: str, changed_charger_ids: set[int]) -> None:
        # MQTT deliveries are serialised at the UI boundary. This prevents a
        # slower earlier query from overwriting a later committed snapshot.
        async with self._delivery_lock:
            with self._lock:
                registrations = tuple(self._views.values())
            snapshots = {}
            # Querying DuckDB is synchronous. Keep it off NiceGUI's event loop;
            # UI mutation below remains on that loop and in the client context.
            run_ids = await asyncio.to_thread(self._query.list_run_ids)
            with self._lock:
                is_new_run = committed_run_id in getattr(self, "_new_run_ids", set())
                latest_live_run_id = getattr(self, "_latest_observed_run_id", None)
            for registration in registrations:
                client = Client.instances.get(registration.client_id)
                if client is None or client.is_deleted:
                    with self._lock:
                        self._views.pop(registration.client_id, None)
                    continue
                # NiceGUI keeps a disconnected Client instance during its
                # reconnect grace period. Do not mutate that client's element
                # tree or queue browser work while it has no socket; retaining
                # the registration lets the same browser resume live updates
                # after reconnecting.
                if not client.has_socket_connection:
                    continue
                view = registration.view
                requested_run = view.snapshot.events.run_id
                try:
                    # History is pinned per browser. Live follows only the
                    # first committed event of a run observed after startup;
                    # delayed historical events therefore cannot steal focus.
                    follows = getattr(view, "live_mode", True) and (requested_run is None or is_new_run)
                    if requested_run != committed_run_id and not follows:
                        with client:
                            view.update_run_options(run_ids, latest_live_run_id=latest_live_run_id)
                        continue
                    snapshot_key = committed_run_id if follows else requested_run
                    if snapshot_key not in snapshots:
                        snapshots[snapshot_key] = await asyncio.to_thread(
                            self._query.load_snapshot, snapshot_key)
                    with client:
                        view.apply_event_snapshot(snapshots[snapshot_key], changed_charger_ids, live=True)
                        view.update_run_options(run_ids, latest_live_run_id=latest_live_run_id)
                except Exception as exc:
                    # A disconnected/broken page must not prevent another
                    # registered client from receiving this committed update.
                    self._report_delivery_failure(
                        f"Could not deliver live update to client {registration.client_id} for run {committed_run_id}", exc)
                await asyncio.sleep(0)
            # "New" means the first observed committed event only. Retaining
            # this flag would let delayed events from an old run hijack Live
            # mode later in the same server lifetime.
            if is_new_run:
                with self._lock:
                    getattr(self, "_new_run_ids", set()).discard(committed_run_id)
