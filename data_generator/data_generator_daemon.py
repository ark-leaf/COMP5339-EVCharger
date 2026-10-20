# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Generate offline by default; add --publish to send events to a local broker."""

import argparse
import json
import math
from pathlib import Path
from threading import Event
import time

from repository.duckdb_repo import DuckDBRepository
from repository.evc_dao import EVChargerDAO
from .data_generator_config import GenerationConfig
from .data_generator_utils import generate_dataset, generate_evc_state_update


def publish_events(events, *, host="localhost", port=1883, topic_prefix="evc", interval=0.1):
    """Publish one event at a time; stop if connection or QoS 1 delivery fails."""
    if not math.isfinite(interval) or interval < 0.1:
        raise ValueError("Publication interval must be at least 0.1 seconds")
    topic_prefix = topic_prefix.strip("/")
    if not topic_prefix or any(c in topic_prefix for c in "+#\0"):
        raise ValueError("Topic prefix must be nonempty and contain no wildcards")
    if not host.strip() or not 1 <= port <= 65535:
        raise ValueError("MQTT host and port must be valid")
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise RuntimeError("Install paho-mqtt==2.1.0 to use --publish") from exc

    connected = Event()
    connection_errors = []

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            connection_errors.append(str(reason_code))
        connected.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, reconnect_on_failure=False)
    client.on_connect = on_connect
    client.max_inflight_messages_set(1)
    count, last_sent = 0, None
    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        if not connected.wait(10):
            raise TimeoutError("MQTT broker did not acknowledge the connection")
        if connection_errors:
            raise ConnectionError(f"MQTT connection rejected: {connection_errors[0]}")
        for event in events:
            if last_sent is not None:
                time.sleep(max(0, interval - (time.monotonic() - last_sent)))
            topic = f"{topic_prefix}/{event.type}/{event.station_id}"
            message = client.publish(topic, event.to_json(), qos=1, retain=False)
            if message.rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError(f"MQTT publish failed: {mqtt.error_string(message.rc)}")
            message.wait_for_publish(timeout=10)
            if not message.is_published():
                raise TimeoutError(f"MQTT event was not acknowledged: {event.event_id}")
            last_sent = time.monotonic()  # Pace from broker ACK, not asynchronous enqueue.
            count += 1
    finally:
        client.disconnect()
        client.loop_stop()
        close = getattr(events, "close", None)
        if close is not None:
            close()
    return count


def main(argv=None):
    defaults = GenerationConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=defaults.db_path)
    parser.add_argument("--out", type=Path, default=defaults.output_dir)
    parser.add_argument("--start", default=defaults.start, help="Start date, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=defaults.days)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--meter-every", type=int, default=defaults.meter_every)
    parser.add_argument("--limit", type=int, help="Use only the first N stations for a demo")
    parser.add_argument("--publish", action="store_true", help="Send to MQTT after generation")
    parser.add_argument("--replay", action="store_true", help="Use existing CSV files in --out")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--topic-prefix", default="evc")
    parser.add_argument("--interval", type=float, default=0.1)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not math.isfinite(args.interval) or args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    config = GenerationConfig(db_path=args.db, output_dir=args.out, start=args.start,
                              days=args.days, seed=args.seed, meter_every=args.meter_every)
    if args.replay:
        print(f"Using existing dataset: {config.output_dir}")
    else:
        with DuckDBRepository(config.db_path, read_only=True) as repo:
            chargers = EVChargerDAO(repo).list_chargers()
        if args.limit is not None:
            chargers = chargers[:args.limit]
        summary = generate_dataset(chargers, config)
        print(json.dumps(summary, indent=2))
        print(f"Dataset saved to: {config.output_dir}")
    if args.publish:
        events = generate_evc_state_update(config.output_dir)
        count = publish_events(events, host=args.host, port=args.port,
                               topic_prefix=args.topic_prefix, interval=args.interval)
        print(f"Published {count} acknowledged MQTT events")
    else:
        print("Offline mode. Add --publish to send events; add --replay to reuse these CSVs.")


if __name__ == "__main__":
    main()
