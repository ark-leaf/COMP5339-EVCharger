# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this implementation.
"""Generate offline by default; add --publish to send events to a local broker."""

import argparse
from collections.abc import Iterable
import json
import math
from pathlib import Path
import time

from repository.duckdb_repo import DuckDBRepository
from repository.evc_dao import EVChargerDAO
from repository.event.y_event import YEvent
from repository.repo_config import mqtt_config
from repository.y_mqtt_simple_repo import YSimpleMqttRepository
from transaction_scripts.data_generation_and_publishing.data_generator_config import GenerationConfig
from transaction_scripts.data_generation_and_publishing.data_generator_utils import generate_dataset, generate_evc_state_update


def publish_events(events: Iterable[YEvent], *, host=None, port=None, topic_prefix=None,
                   interval=None, inline_broker=False, startup_wait=0.0):
    """Publish one event at a time; stop if connection or QoS 1 delivery fails."""
    try:
        with YSimpleMqttRepository(host=host, port=port, topic_prefix=topic_prefix,
                                   interval=interval, is_inline_broker=inline_broker) as repo:
            if startup_wait > 0:
                # A new inline broker has no subscribers yet; give them time to connect.
                print(f"Waiting {startup_wait:g} s for subscribers before publishing")
                time.sleep(startup_wait)
            for event in events:
                repo.send_event(event)
            return repo.msg_count_sent
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            close()


def main(argv: list[str] | None = None) -> None:
    # Configurations
    defaults = GenerationConfig()
    mqtt_defaults = mqtt_config()
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
    parser.add_argument("--host", default=mqtt_defaults["host"])
    parser.add_argument("--port", type=int, default=mqtt_defaults["port"])
    parser.add_argument("--topic-prefix", default=mqtt_defaults["topic_root"])
    parser.add_argument("--interval", type=float, default=mqtt_defaults["publish_interval_seconds"])
    parser.add_argument("--inline-broker", action="store_true",
                        help="Run an embedded amqtt broker on --host/--port while publishing")
    parser.add_argument("--startup-wait", type=float, default=0.0, metavar="SECONDS",
                        help="Seconds to wait after connecting, so subscribers can join an inline broker")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if not math.isfinite(args.interval) or args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    if not math.isfinite(args.startup_wait) or args.startup_wait < 0:
        parser.error("--startup-wait must be zero or more seconds")
    config = GenerationConfig(db_path=args.db, output_dir=args.out, start=args.start,
                              days=args.days, seed=args.seed, meter_every=args.meter_every)

    if args.replay:
        print(f"Using existing dataset: {config.output_dir}")
    else:
        # Load Chargers
        with DuckDBRepository(config.db_path, read_only=True) as repo:
            chargers = EVChargerDAO(repo).list_chargers()
        if args.limit is not None:
            chargers = chargers[:args.limit]
        # Generate dataset
        summary = generate_dataset(chargers, config)
        print(json.dumps(summary, indent=2))
        print(f"Dataset saved to: {config.output_dir}")
    if args.publish:
        # Initialize events
        events = generate_evc_state_update(config.output_dir)
        # Publish events on MQTT
        count = publish_events(events, host=args.host, port=args.port,
                               topic_prefix=args.topic_prefix, interval=args.interval,
                               inline_broker=args.inline_broker, startup_wait=args.startup_wait)
        print(f"Published {count} acknowledged MQTT events")
    else:
        print("Offline mode. Add --publish to send events; add --replay to reuse these CSVs.")


if __name__ == "__main__":
    main()
