import sys
import threading
import time

from config import ASS2_DEMO_DATA_FILE_LOCATION, DB_DATA
from transaction_scripts.data_generation_and_publishing import data_generator_daemon
from transaction_scripts.stateful_event_storage.save_subscribed_data import EVChargerEventStore
from repository.event.ev_charger_state_event import EVChargerStateEvent
from data_utils.y_mqtt_event_subscriber import YMqttEventSubscriber
from repository.repo_config import mqtt_config
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository

# 3 stations x 1 day is a few hundred events, about a minute at 0.1 s per event.
DEMO_DAEMON_ARGS = ["--limit", "3", "--days", "1", "--meter-every", "5",
                    "--out", str(ASS2_DEMO_DATA_FILE_LOCATION)]
# Time for the last deliveries to reach subscribers after the daemon's final broker ACK.
DRAIN_SECONDS = 2.0

# Writes into the Assignment 1 database; it opens on the first event, after the daemon has
# read the stations read-only (DuckDB cannot hold both modes on one file in one process).
event_store = EVChargerEventStore()

# Define Subscribers
def sub_database_update(event: EVChargerStateEvent) -> None:
    """Task 4: Stateful Event Storage and Charging Session Analytics"""
    stored = event_store.save(event)
    where = event.charger_id if event.connector_id is None else f"{event.charger_id}/{event.connector_id}"
    print(f"[{threading.current_thread().name}] {'stored   ' if stored else 'duplicate'} "
          f"{event.ts:%Y-%m-%d %H:%M} UTC {event.type:<13} charger {where:<6} {event.payload}")


def sub_dashboard(event: EVChargerStateEvent) -> None:
    """Task 3: Data Subscription and Visualization"""
    # TODO: handle the event here
    pass


def main(argv: list[str] | None = None) -> None:
    settings = mqtt_config()
    host, port = settings["host"], settings["port"]
    daemon_args = (sys.argv[1:] if argv is None else argv) or DEMO_DAEMON_ARGS

    # Inline broker first, so the subscribers can connect before anything is published
    with YSimpleMqttRepository(host=host, port=port, is_inline_broker=True):
        subscribers = [
            YMqttEventSubscriber[EVChargerStateEvent]("database-update", sub_database_update, host, port),
            YMqttEventSubscriber[EVChargerStateEvent]("dashboard", sub_dashboard, host, port),
        ]
        for subscriber in subscribers:
            subscriber.start()
        try:
            for subscriber in subscribers:
                if not subscriber.ready.wait(15) or subscriber.error:
                    raise RuntimeError(f"{subscriber.name} did not subscribe: {subscriber.error}")
            # Run the data generator daemon, publishing to the broker above
            data_generator_daemon.main([*daemon_args, "--publish", "--host", host, "--port", str(port)])
            time.sleep(DRAIN_SECONDS)
        finally:
            # One at a time, so their shutdown messages do not interleave
            for subscriber in subscribers:
                subscriber.stopping.set()
                subscriber.join(timeout=10)

    for subscriber in subscribers:
        print(f"{subscriber.name} handled {subscriber.received} events")
    print(f"Stored {event_store.stored} new events in {DB_DATA}; skipped {event_store.duplicates} duplicates")
    for run_id in sorted(event_store.run_ids):
        print(f"  run {run_id}: {event_store.dao.run_summary(run_id)}")
    failed = [s for s in subscribers if s.error is not None]
    if failed:
        raise RuntimeError(f"{failed[0].name} failed: {failed[0].error!r}") from failed[0].error

if __name__ == "__main__":
    main()
