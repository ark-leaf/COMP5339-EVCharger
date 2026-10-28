"""Unified Assignment 2 entry point: generator, MQTT storage and live Dashboard."""
from __future__ import annotations

import argparse
from collections import OrderedDict
from dataclasses import dataclass, field
import sys
import threading
import time
import traceback
from pathlib import Path

from config import ASS2_DEMO_DATA_FILE_LOCATION, DB_DATA
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.repo_config import mqtt_config
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository
from transaction_scripts.data_generation_and_publishing import data_generator_daemon
from transaction_scripts.stateful_event_storage.save_subscribed_data import EVChargerEventStore
from view.mqtt_commit_coordinator import MqttCommitCoordinator


DEMO_DAEMON_ARGS = ["--limit", "3", "--days", "1", "--meter-every", "5",
                    "--out", str(ASS2_DEMO_DATA_FILE_LOCATION)]
event_store = EVChargerEventStore()
_dashboard_live_service = None
# The retry worker must exist only while the Unified application is running.
# Tests may inject a coordinator directly; production initialises this in main().
_commit_coordinator: MqttCommitCoordinator | None = None
_reported_coordinator_gaps: OrderedDict[str, None] = OrderedDict()
_MAX_REPORTED_COORDINATOR_GAPS = 1_000
_fatal_persistence: dict | None = None
_fatal_persistence_lock = threading.Lock()
_replay_reconciliation = None
_publisher_cancel: threading.Event | None = None
_RECONCILIATION_TIMEOUT_SECONDS = 15.0


@dataclass
class _ReplayReconciliation:
    """Thread-safe, per-event accounting for a single unified replay.

    Broker acknowledgement is intentionally distinct from the two subscriber
    callbacks: an acknowledged publish may still be queued when Task B fails.
    """
    broker_acknowledged: set[str] = field(default_factory=set)
    task_b_received: set[str] = field(default_factory=set)
    task_b_committed: set[str] = field(default_factory=set)
    task_b_duplicates: set[str] = field(default_factory=set)
    task_b_failed: set[str] = field(default_factory=set)
    task_c_received: set[str] = field(default_factory=set)
    coordinator_matched: set[str] = field(default_factory=set)
    dashboard_notified: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, stage: str, event: EVChargerStateEvent) -> None:
        with self._lock:
            getattr(self, stage).add(event.id)

    def unresolved(self) -> dict[str, set[str]]:
        with self._lock:
            terminal_b = self.task_b_committed | self.task_b_duplicates | self.task_b_failed
            required_notifications = self.task_b_committed
            return {
                "task_b_outstanding": self.broker_acknowledged - terminal_b,
                "task_c_outstanding": self.broker_acknowledged - self.task_c_received,
                "dashboard_outstanding": required_notifications - self.dashboard_notified,
            }

    def successful(self) -> bool:
        with self._lock:
            terminal_b = self.task_b_committed | self.task_b_duplicates | self.task_b_failed
            return (bool(self.broker_acknowledged) and not self.task_b_failed and self.broker_acknowledged <= terminal_b
                    and self.broker_acknowledged <= self.task_c_received
                    and self.task_b_committed <= self.dashboard_notified)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {stage: len(getattr(self, stage)) for stage in (
                "broker_acknowledged", "task_b_received", "task_b_committed",
                "task_b_duplicates", "task_b_failed", "task_c_received", "dashboard_notified",
                "coordinator_matched",
            )}


def _record_replay_stage(stage: str, event: EVChargerStateEvent) -> None:
    if _replay_reconciliation is not None:
        _replay_reconciliation.record(stage, event)


def _notify_dashboard_after_join(event: EVChargerStateEvent) -> None:
    """The coordinator's only UI-side effect; it never writes DuckDB."""
    _record_replay_stage("coordinator_matched", event)
    if _dashboard_live_service is None:
        raise RuntimeError("Dashboard service is unavailable; notification was not accepted")
    # The service returns False when no NiceGUI loop can accept the work.  Do
    # not turn this into a successful browser-delivery claim; the coordinator
    # keeps it retryable and eventually requests bounded recovery.
    if not _dashboard_live_service.notify_committed(event):
        raise RuntimeError("Dashboard service could not schedule the notification")
    _record_replay_stage("dashboard_notified", event)


def _report_coordinator_gap(event, reason: str) -> None:
    """Bounded, observable signal; committed-event notification triggers snapshot reload."""
    key = f"{getattr(event, 'id', 'none')}:{reason}"
    if key not in _reported_coordinator_gaps:
        _reported_coordinator_gaps[key] = None
        while len(_reported_coordinator_gaps) > _MAX_REPORTED_COORDINATOR_GAPS:
            _reported_coordinator_gaps.popitem(last=False)
        print(f"MQTT coordinator gap: {reason}", file=sys.stderr)
    if event is not None and _dashboard_live_service is not None:
        # This is a committed-event recovery signal: DashboardLiveService reloads
        # its snapshot from the sole writer's DuckDB history.
        _dashboard_live_service.request_snapshot_resync(event)


def sub_dashboard(event: EVChargerStateEvent) -> None:
    """Task C's independent MQTT callback: record arrival, never write DuckDB."""
    if _commit_coordinator is None:
        raise RuntimeError("MQTT coordinator is not running")
    _record_replay_stage("task_c_received", event)
    _commit_coordinator.dashboard_received(event)


def sub_database_update(event: EVChargerStateEvent) -> None:
    """Task B's sole-writer MQTT callback, independent from Task C."""
    where = event.charger_id if event.connector_id is None else f"{event.charger_id}/{event.connector_id}"
    if _commit_coordinator is None:
        raise RuntimeError("MQTT coordinator is not running")
    _record_replay_stage("task_b_received", event)
    try:
        stored = event_store.save(event)
    except Exception as exc:
        _commit_coordinator.rejected_event(event)
        _record_replay_stage("task_b_failed", event)
        global _fatal_persistence
        with _fatal_persistence_lock:
            if _fatal_persistence is None:
                _fatal_persistence = dict(exception=exc, traceback=traceback.format_exc(),
                    event_id=event.id, run_id=event.run_id, charger_id=event.charger_id,
                    connector_no=event.connector_id, event_type=event.type,
                    thread=threading.current_thread().name, operation="event_store.save")
                print(f"FATAL persistence failure at event_store.save: {_fatal_persistence}", file=sys.stderr)
                print("LIVE synchronization FAILED: committed dashboard updates are no longer healthy.",
                      file=sys.stderr)
                report_failure = getattr(_dashboard_live_service, "report_sync_failed", None)
                if report_failure is not None:
                    report_failure()
        # Stop this subscriber so main can surface the fatal condition; the
        # publisher wrapper observes the shared signal before its next send.
        raise
    outcome = "stored   " if stored else "duplicate"
    print(f"[{threading.current_thread().name}] {outcome} "
          f"{event.ts:%Y-%m-%d %H:%M} UTC {event.type:<13} charger {where:<6} {event.payload}")
    if stored:
        _record_replay_stage("task_b_committed", event)
        _commit_coordinator.committed(event)
    else:
        _record_replay_stage("task_b_duplicates", event)


def _parse_args(argv: list[str] | None):
    settings = mqtt_config()
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--dashboard-host", default="127.0.0.1")
    parser.add_argument("--dashboard-port", type=int, default=8080)
    parser.add_argument("--host", default=settings["host"], help="MQTT broker host")
    parser.add_argument("--port", type=int, default=settings["port"], help="MQTT broker port")
    parser.add_argument("--external-broker", action="store_true",
                        help="Connect to an already-running broker instead of starting Yeh's inline broker")
    parser.add_argument("--dashboard-delay", type=float, default=10.0, metavar="SECONDS",
                        help="Wait after NiceGUI startup before replaying prepared events")
    parser.add_argument("--help", action="store_true")
    args, generator_args = parser.parse_known_args(argv)
    if args.help:
        parser.print_help()
        data_generator_daemon.main(["--help"])
        raise SystemExit(0)
    if args.dashboard_port < 1 or args.dashboard_port > 65535:
        parser.error("--dashboard-port must be a valid TCP port")
    if args.dashboard_delay < 0:
        parser.error("--dashboard-delay must be zero or more seconds")
    return args, generator_args or list(DEMO_DAEMON_ARGS)


def _without_flags(arguments: list[str], flags: set[str]) -> list[str]:
    """Remove boolean generator flags that would create a second publisher/broker."""
    return [argument for argument in arguments if argument not in flags]


def _assert_generator_database(arguments: list[str]) -> None:
    """Do not let generation read one database while the sole writer uses another."""
    for index, argument in enumerate(arguments):
        value = None
        if argument == "--db" and index + 1 < len(arguments):
            value = arguments[index + 1]
        elif argument.startswith("--db="):
            value = argument.split("=", 1)[1]
        if value is not None and Path(value).resolve() != Path(DB_DATA).resolve():
            raise ValueError("Unified Dashboard requires generator --db to match config.DB_DATA")


def _prepare_arguments(generator_args: list[str]) -> list[str]:
    # Generation happens before the writer exists. Publishing is deferred until
    # NiceGUI is running; ``--replay`` remains valid for an existing dataset.
    return _without_flags(generator_args, {"--publish", "--inline-broker"})


def _replay_arguments(generator_args: list[str], host: str, port: int) -> list[str]:
    base = _without_flags(generator_args, {"--publish", "--inline-broker"})
    if "--replay" not in base:
        base.append("--replay")
    return [*base, "--publish", "--host", host, "--port", str(port)]


def _wait_for_reconciliation(reconciliation: _ReplayReconciliation, cancel: threading.Event,
                             timeout: float = _RECONCILIATION_TIMEOUT_SECONDS) -> bool:
    """Wait off the NiceGUI loop for both subscriber queues to reach terminal state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reconciliation.successful():
            return True
        if cancel.is_set() or _fatal_persistence is not None:
            return False
        time.sleep(.02)
    return reconciliation.successful()


def _format_reconciliation(reconciliation: _ReplayReconciliation) -> str:
    counts = reconciliation.snapshot()
    unresolved = {name: len(ids) for name, ids in reconciliation.unresolved().items()}
    return f"counts={counts}; outstanding={unresolved}"


def main(argv: list[str] | None = None) -> None:
    global _dashboard_live_service, _commit_coordinator, _fatal_persistence
    global _replay_reconciliation, _publisher_cancel
    _fatal_persistence = None
    _replay_reconciliation = _ReplayReconciliation()
    _publisher_cancel = threading.Event()
    args, generator_args = _parse_args(sys.argv[1:] if argv is None else argv)
    _assert_generator_database(generator_args)

    # This is the only phase that opens Assignment 1 through a read-only
    # repository. It finishes before EventStore/Dashboard obtains its writer.
    data_generator_daemon.main(_prepare_arguments(generator_args))

    from nicegui import app, ui
    from view.dashboard_daemon import run_dashboard
    from view.dashboard_live import DashboardLiveService

    publisher_thread: threading.Thread | None = None
    publisher_error: list[BaseException] = []
    with YSimpleMqttRepository(host=args.host, port=args.port,
                               is_inline_broker=not args.external_broker):
        # The Dashboard service is UI-only in unified mode. It cannot create
        # a third subscriber or an EventStore writer.
        _dashboard_live_service = DashboardLiveService(host=args.host, port=args.port,
                                                        db_path=DB_DATA, start_subscriber=False)
        _commit_coordinator = MqttCommitCoordinator(_notify_dashboard_after_join,
                                                     on_gap=_report_coordinator_gap)
        database_subscriber = YMqttEventSubscriber[EVChargerStateEvent](
            "database-update", sub_database_update, args.host, args.port, EVChargerStateEvent)
        dashboard_subscriber = YMqttEventSubscriber[EVChargerStateEvent](
            "dashboard-update", sub_dashboard, args.host, args.port, EVChargerStateEvent)
        subscribers = (database_subscriber, dashboard_subscriber)
        started_subscribers = []
        try:
            for subscriber in subscribers:
                subscriber.start()
                started_subscribers.append(subscriber)
            for subscriber in subscribers:
                if not subscriber.ready.wait(15) or subscriber.error:
                    raise RuntimeError(f"{subscriber.name} did not subscribe: {subscriber.error}")
        except BaseException:
            for subscriber in started_subscribers:
                subscriber.stopping.set()
            for subscriber in started_subscribers:
                subscriber.join(timeout=10)
            _commit_coordinator.close()
            _dashboard_live_service = None
            raise

        def publish_after_dashboard_start() -> None:
            nonlocal publisher_thread

            def replay() -> None:
                try:
                    if args.dashboard_delay:
                        print(f"Dashboard is available at http://{args.dashboard_host}:{args.dashboard_port}/; "
                              f"replay starts in {args.dashboard_delay:g} seconds")
                        time.sleep(args.dashboard_delay)
                    original_publish = data_generator_daemon.publish_events
                    def fail_fast_publish(events, **kwargs):
                        def guarded():
                            for event in events:
                                with _fatal_persistence_lock:
                                    failure = _fatal_persistence
                                if _publisher_cancel.is_set() or failure is not None:
                                    raise RuntimeError(f"Replay aborted after fatal persistence failure: {failure}")
                                yield event
                                # ``publish_events`` asks for the next item only after
                                # send_event has received the QoS-1 broker ACK.
                                _record_replay_stage("broker_acknowledged", event)
                        return original_publish(guarded(), **kwargs)
                    data_generator_daemon.publish_events = fail_fast_publish
                    try:
                        data_generator_daemon.main(_replay_arguments(generator_args, args.host, args.port))
                    finally:
                        data_generator_daemon.publish_events = original_publish
                    if not _wait_for_reconciliation(_replay_reconciliation, _publisher_cancel):
                        raise RuntimeError("Replay did not reconcile: " +
                                           _format_reconciliation(_replay_reconciliation))
                    print("Replay synchronized: " + _format_reconciliation(_replay_reconciliation) +
                          ". Dashboard remains running; press Ctrl+C to stop it.")
                except BaseException as exc:
                    publisher_error.append(exc)
                    print(f"Publisher failed: {exc!r}", file=sys.stderr)

            publisher_thread = threading.Thread(target=replay, name="dashboard-publisher", daemon=True)
            publisher_thread.start()

        try:
            run_dashboard(ui, app, _dashboard_live_service, host=args.dashboard_host,
                          port=args.dashboard_port, db_path=Path(DB_DATA),
                          on_startup=publish_after_dashboard_start)
        finally:
            # Do not stop the consumers while the publisher can still append
            # acknowledged messages to their queues.
            _publisher_cancel.set()
            if publisher_thread is not None:
                publisher_thread.join(timeout=10)
                if publisher_thread.is_alive():
                    print("Publisher did not stop within 10 seconds; queued events will be reported.", file=sys.stderr)
            # Give already ACKed queue contents a bounded chance to reach a
            # terminal Task B/C outcome; any residue is reported below.
            _wait_for_reconciliation(_replay_reconciliation, threading.Event(), timeout=1.0)
            for subscriber in started_subscribers:
                subscriber.stopping.set()
            for subscriber in started_subscribers:
                subscriber.join(timeout=10)
            _commit_coordinator.close()
            _dashboard_live_service = None

    for subscriber in subscribers:
        if subscriber.error:
            raise RuntimeError(f"{subscriber.name} failed: {subscriber.error!r}") from subscriber.error
    if _fatal_persistence is not None:
        print("LIVE synchronization failed; dashboard updates are no longer healthy: " +
              _format_reconciliation(_replay_reconciliation), file=sys.stderr)
        raise RuntimeError(f"Fatal Task B persistence failure: {_fatal_persistence}") from _fatal_persistence["exception"]
    if publisher_error:
        raise RuntimeError("Dashboard publisher failed") from publisher_error[0]


if __name__ == "__main__":
    main()
