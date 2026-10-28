"""Unified Assignment 2 entry point: generator, MQTT storage and live Dashboard."""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from config import ASS2_DEMO_DATA_FILE_LOCATION, DB_DATA
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.repo_config import mqtt_config
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository
from transaction_scripts.data_generation_and_publishing import data_generator_daemon
from transaction_scripts.stateful_event_storage.save_subscribed_data import EVChargerEventStore


DEMO_DAEMON_ARGS = ["--limit", "3", "--days", "1", "--meter-every", "5",
                    "--out", str(ASS2_DEMO_DATA_FILE_LOCATION)]
event_store = EVChargerEventStore()
_dashboard_live_service = None


def sub_dashboard(event: EVChargerStateEvent) -> None:
    """Queue a thread-safe UI refresh for one event already committed to DuckDB.

    This callback is intentionally invoked only by ``sub_database_update``
    after ``event_store.save`` returns ``True``. It never writes DuckDB and is
    not a second MQTT subscriber.
    """
    if _dashboard_live_service is not None:
        _dashboard_live_service.notify_committed(event)


def sub_database_update(event: EVChargerStateEvent) -> None:
    """Task 4 storage, followed by the Part C post-commit notification."""
    stored = event_store.save(event)
    where = event.charger_id if event.connector_id is None else f"{event.charger_id}/{event.connector_id}"
    print(f"[{threading.current_thread().name}] {'stored   ' if stored else 'duplicate'} "
          f"{event.ts:%Y-%m-%d %H:%M} UTC {event.type:<13} charger {where:<6} {event.payload}")
    if stored:
        sub_dashboard(event)


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


def main(argv: list[str] | None = None) -> None:
    global _dashboard_live_service
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
        subscriber = YMqttEventSubscriber[EVChargerStateEvent](
            "database-update", sub_database_update, args.host, args.port, EVChargerStateEvent)
        subscriber.start()
        if not subscriber.ready.wait(15) or subscriber.error:
            raise RuntimeError(f"{subscriber.name} did not subscribe: {subscriber.error}")

        # In unified mode the existing subscriber above is the sole writer.
        _dashboard_live_service = DashboardLiveService(host=args.host, port=args.port,
                                                        db_path=DB_DATA, start_subscriber=False)

        def publish_after_dashboard_start() -> None:
            nonlocal publisher_thread

            def replay() -> None:
                try:
                    if args.dashboard_delay:
                        print(f"Dashboard is available at http://{args.dashboard_host}:{args.dashboard_port}/; "
                              f"replay starts in {args.dashboard_delay:g} seconds")
                        time.sleep(args.dashboard_delay)
                    data_generator_daemon.main(_replay_arguments(generator_args, args.host, args.port))
                    print("Publisher finished. Dashboard remains running; press Ctrl+C to stop it.")
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
            subscriber.stopping.set()
            subscriber.join(timeout=10)
            _dashboard_live_service = None
            if publisher_thread is not None:
                publisher_thread.join(timeout=10)

    if subscriber.error:
        raise RuntimeError(f"{subscriber.name} failed: {subscriber.error!r}") from subscriber.error
    if publisher_error:
        raise RuntimeError("Dashboard publisher failed") from publisher_error[0]


if __name__ == "__main__":
    main()
