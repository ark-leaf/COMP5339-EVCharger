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
from repository.evc_info_dao import EVChargerInfoDAO
from repository.event.y_event import YEvent
from repository.repo_config import mqtt_config
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository
from transaction_scripts.data_generation_and_publishing.data_generator_config import GenerationConfig
from transaction_scripts.data_generation_and_publishing.data_generator_replay import replay_events
from transaction_scripts.data_generation_and_publishing.data_generator_utils import (
    generate_dataset, write_events_json,
)


def publish_events(events: Iterable[YEvent], *, host=None, port=None, topic_prefix=None,
                   interval=None, inline_broker=False, startup_wait=0.0, published_path=None):
    """Publish one event at a time; stop if connection or QoS 1 delivery fails."""
    try:
        with YSimpleMqttRepository(host=host, port=port, topic_prefix=topic_prefix,
                                   interval=interval, is_inline_broker=inline_broker) as repo:
            if startup_wait > 0:
                # A new inline broker has no subscribers yet; give them time to connect.
                print(f"Waiting {startup_wait:g} s for subscribers before publishing")
                time.sleep(startup_wait)
            def acknowledged_events():
                for event in events:
                    repo.send_event(event)
                    yield event  # Record only after send_event has received the broker ACK.

            if published_path is None:
                for _ in acknowledged_events():
                    pass
            else:
                write_events_json(acknowledged_events(), published_path)
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
    parser.add_argument("--charger-type", choices=("all", "AC", "DC"), default=defaults.charger_type,
                        help="Select station type before applying --limit")
    parser.add_argument("--sessions-per-connector-day", type=float, nargs=2,
                        metavar=("URBAN", "REGIONAL"), default=defaults.sessions_per_connector_day,
                        help="Expected sessions per connector per day for urban and regional sites")
    parser.add_argument("--limit", type=int, help="Use only the first N stations for a demo")
    parser.add_argument("--target-sessions", type=int,
                        help="Allocate an exact total with daily focus-port coverage (DC only)")
    parser.add_argument("--focus-region", default="Sydney",
                        help="SA4 name prefix for accepted augmented focus stations")
    parser.add_argument("--publish", action="store_true", help="Send to MQTT after generation")
    parser.add_argument("--replay", action="store_true", help="Use existing CSV files in --out")
    parser.add_argument("--export-events", action="store_true",
                        help="Save prepared_events.json without needing MQTT; automatic with --publish")
    parser.add_argument("--window-start", help="Replay start in ISO time; naive times use AEST")
    parser.add_argument("--window-end", help="Exclusive replay end in ISO time; naive times use AEST")
    parser.add_argument("--events-out", type=Path, help="Separate directory for window JSON files")
    parser.add_argument("--host", default=mqtt_defaults["host"])
    parser.add_argument("--port", type=int, default=mqtt_defaults["port"])
    parser.add_argument("--topic-prefix", default=mqtt_defaults["topic_root"])
    parser.add_argument("--interval", type=float, default=mqtt_defaults["publish_interval_seconds"])
    parser.add_argument("--inline-broker", action="store_true",
                        help="Run an embedded amqtt broker on --host/--port while publishing")
    parser.add_argument("--startup-wait", type=float, default=0.0, metavar="SECONDS",
                        help="Seconds to wait after connecting, so subscribers can join an inline broker")
    args = parser.parse_args(argv)
    if bool(args.window_start) != bool(args.window_end):
        parser.error("--window-start and --window-end must be supplied together")
    if args.window_start and args.events_out is None:
        parser.error("Use --events-out for a window to keep the full event export intact")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if any(not math.isfinite(rate) or rate < 0 for rate in args.sessions_per_connector_day):
        parser.error("--sessions-per-connector-day values must be finite and nonnegative")
    if not math.isfinite(args.interval) or args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    if not math.isfinite(args.startup_wait) or args.startup_wait < 0:
        parser.error("--startup-wait must be zero or more seconds")
    config = GenerationConfig(db_path=args.db, output_dir=args.out, start=args.start,
                              days=args.days, seed=args.seed, meter_every=args.meter_every,
                              charger_type=args.charger_type,
                              target_sessions=args.target_sessions, focus_region=args.focus_region,
                              sessions_per_connector_day=tuple(args.sessions_per_connector_day))

    if args.replay:
        print(f"Using existing dataset: {config.output_dir}")
    else:
        # Load Chargers
        with DuckDBRepository(config.db_path, read_only=True) as repo:
            dao = EVChargerInfoDAO(repo)
            chargers = dao.list_chargers()
            if config.target_sessions is not None:
                config.focus_charger_ids = dao.list_augmented_charger_ids(config.focus_region)
        if config.charger_type != "all":
            chargers = [c for c in chargers if (c.charger_type or "").upper() == config.charger_type]
        if args.limit is not None:
            chargers = chargers[:args.limit]
        selected_ids = {c.charger_id for c in chargers}
        config.focus_charger_ids = tuple(cid for cid in config.focus_charger_ids if cid in selected_ids)
        # Generate dataset
        summary = generate_dataset(chargers, config)
        print(json.dumps(summary, indent=2))
        print(f"Dataset saved to: {config.output_dir}")
    if args.export_events or args.publish:
        events_dir = args.events_out or config.output_dir
        events_dir.mkdir(parents=True, exist_ok=True)
        prepared_path = events_dir / "prepared_events.json"
        count = write_events_json(replay_events(config.output_dir, args.window_start, args.window_end), prepared_path)
        print(f"Prepared {count} events in {prepared_path}")
    if args.publish:
        # Initialize events
        events = replay_events(config.output_dir, args.window_start, args.window_end)
        # Publish events on MQTT
        count = publish_events(events, host=args.host, port=args.port,
                               topic_prefix=args.topic_prefix, interval=args.interval,
                               inline_broker=args.inline_broker, startup_wait=args.startup_wait,
                               published_path=events_dir / "published_events.json")
        print(f"Published {count} acknowledged MQTT events")
    else:
        print("Offline mode. Add --publish to send events; add --replay to reuse these CSVs.")


if __name__ == "__main__":
    main()
