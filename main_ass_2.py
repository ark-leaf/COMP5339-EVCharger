"""Unified Assignment 2 entry point: generator, MQTT storage and live Dashboard."""
from __future__ import annotations

import argparse
import sys
import threading
from functools import partial
from pathlib import Path

from config import ASS2_DEMO_DATA_FILE_LOCATION, DASHBOARD_PORT, DB_DATA
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber, subscribed
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository
from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.repo_config import mqtt_config
from transaction_scripts.data_generation_and_publishing import data_generator_daemon
from transaction_scripts.stateful_event_storage.save_subscribed_data import prepare_event_storage, sub_database_update
from view.dashboard_daemon import DashboardDaemon, dashboard_port_problem

DEMO_DAEMON_ARGS = ["--limit", "3", "--days", "1", "--meter-every", "5",
                    "--out", str(ASS2_DEMO_DATA_FILE_LOCATION)]


def _parse_args(argv: list[str] | None):
    settings = mqtt_config()
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--dashboard-host", default="127.0.0.1")
    parser.add_argument("--dashboard-port", type=int, default=DASHBOARD_PORT)
    parser.add_argument("--host", default=settings["host"], help="MQTT broker host")
    parser.add_argument("--port", type=int, default=settings["port"], help="MQTT broker port")
    parser.add_argument("--external-broker", action="store_true",
                        help="Connect to an already-running broker instead of starting Yeh's inline broker")
    parser.add_argument("--dashboard-delay", type=float, default=10.0, metavar="SECONDS",
                        help="Wait after generating, before publishing, so the dashboard can be opened first")
    parser.add_argument("--help", action="store_true")
    args, generator_args = parser.parse_known_args(argv)
    if args.help:
        parser.print_help()
        data_generator_daemon.main(["--help"])
        raise SystemExit(0)
    if args.dashboard_delay < 0:
        parser.error("--dashboard-delay must be zero or more seconds")
    if "--inline-broker" in generator_args:
        parser.error("--inline-broker cannot be used: main_ass_2 runs the broker the generator publishes to")
    # uvicorn binds only after NiceGUI's startup hooks have started the generator, so
    # a bad or taken port must be reported here, before anything starts.
    problem = dashboard_port_problem(args.dashboard_host, args.dashboard_port)
    if problem is not None:
        parser.error(f"--dashboard-port {problem}")
    return args, generator_args or list(DEMO_DAEMON_ARGS)


def _assert_generator_database(arguments: list[str]) -> None:
    """Do not let generation read one database while the sole writer uses another."""
    for index, argument in enumerate(arguments):
        value = None
        if argument == "--db" and index + 1 < len(arguments):
            value = arguments[index + 1]
        elif argument.startswith("--db="):
            value = argument.split("=", 1)[1]
        if value is not None and Path(value).resolve() != DB_DATA:
            raise ValueError("Unified Dashboard requires generator --db to match config.DB_DATA")


def _clear_previous_demo_dataset(folder: Path) -> None:
    """Let a default run generate a new demo dataset where the previous one was.

    Explicit ``--out`` folders keep the generator's refusal to overwrite a dataset.
    """
    if data_generator_daemon.remove_dataset(folder):
        print(f"Replacing the previous demo dataset in {folder} (AEMO price cache kept)")


def main(argv: list[str] | None = None) -> None:
    args, generator_args = _parse_args(sys.argv[1:] if argv is None else argv)
    _assert_generator_database(generator_args)
    if generator_args == DEMO_DAEMON_ARGS:
        _clear_previous_demo_dataset(ASS2_DEMO_DATA_FILE_LOCATION)
    prepare_event_storage()

    dashboard = DashboardDaemon(host=args.dashboard_host, port=args.dashboard_port)
    generator_error: list[BaseException] = []

    def generate_and_publish() -> None:
        # The only generator run: it generates the dataset and publishes each event once to this
        # process's broker. Dashboard pages and the event store share this process's read-write
        # DuckDB connection, and DuckDB will not open the file again read-only, so the generator
        # reads the stations through that connection too.
        try:
            data_generator_daemon.main([*generator_args, "--publish", "--host", args.host, "--port", str(args.port),
                                        "--startup-wait", str(args.dashboard_delay)], shared_connection=True)
        except BaseException as exc:
            generator_error.append(exc)
            dashboard.stop()  # serve() returns, and main raises the error
        else:
            print("Publishing finished. Dashboard remains running; press Ctrl+C to stop it.")

    # NiceGUI starts the generator from its startup hook, once both subscribers have subscribed.
    generator = threading.Thread(target=generate_and_publish, name="generator", daemon=True)

    subscribers = (
        YMqttEventSubscriber[EVChargerStateEvent](
            "database-update", partial(sub_database_update, on_failure=dashboard.report_sync_failed),
            args.host, args.port, EVChargerStateEvent),
        YMqttEventSubscriber[EVChargerStateEvent](
            "dashboard-update", dashboard.receive, args.host, args.port, EVChargerStateEvent),
    )
    with (YSimpleMqttRepository(host=args.host, port=args.port, is_inline_broker=not args.external_broker),
          subscribed(*subscribers)):
        dashboard.serve(on_startup=generator.start)

    if generator_error:
        raise generator_error[0]


if __name__ == "__main__":
    main()
