"""Publish one slow, isolated MQTT charging session for Dashboard observation.

This script never writes DuckDB. Start the Dashboard's embedded subscriber first;
it is the only component that persists the MQTT events.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from time import sleep
from uuid import uuid4

from repository.event.ev_charger_state_event import EVChargerStateEvent
from repository.repo_config import mqtt_config
from data_utils.y_mqtt_simple_repo import YSimpleMqttRepository


def build_demo_events(run_id: str, charger_id: int, *, meter_count: int = 10,
                      started_at: datetime | None = None) -> tuple[EVChargerStateEvent, ...]:
    """Build an ordered, valid price/start/meter/end sequence for one connector."""
    if meter_count < 10:
        raise ValueError("meter_count must be at least 10 for the live curve demonstration")
    started_at = (started_at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    connector_id, session_id, price = 1, f"live-demo-{run_id[:8]}", 0.55
    event = lambda kind, ts, payload, session=None: EVChargerStateEvent(
        run_id=run_id, id=uuid4().hex, type=kind, ts=ts, object_id=str(charger_id),
        connector_id=connector_id if session else None, session_id=session, payload=payload,
    )
    events = [
        event("price_update", started_at, {"price_per_kwh": price}),
        event("session_start", started_at + timedelta(seconds=1),
              {"price_per_kwh": price, "vehicle_model": "Controlled demo EV"}, session_id),
    ]
    # 50 kW for 90 simulated seconds yields exactly 1.25 kWh. MQTT playback
    # remains slow enough to observe (two real seconds between meter messages).
    simulated_meter_seconds = 90
    for reading in range(1, meter_count + 1):
        events.append(event(
            "meter", started_at + timedelta(seconds=1 + reading * simulated_meter_seconds),
            {"power_kw": 50.0, "energy_kwh": reading * 1.25, "soc_pct": 20 + reading * 5}, session_id,
        ))
    last_meter = events[-1]
    end_at = last_meter.ts + timedelta(seconds=1)
    total_energy = float(last_meter.payload["energy_kwh"])
    events.append(event(
        "session_end", end_at,
        {"charge_end_ts": last_meter.ts, "charge_minutes": (last_meter.ts - events[1].ts).total_seconds() / 60,
         "energy_kwh": total_energy, "price_per_kwh": price, "cost_aud": total_energy * price,
         "avg_kw": 50.0, "peak_kw": 50.0}, session_id,
    ))
    return tuple(events)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    settings = mqtt_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Fresh UUID/hex run ID; never reuse a historical run")
    parser.add_argument("--charger-id", required=True, type=int, help="Existing mapped NSW charger ID (for this demo use 4)")
    parser.add_argument("--host", default=settings["host"])
    parser.add_argument("--port", type=int, default=settings["port"])
    parser.add_argument("--prepare", action="store_true", help="Print the dashboard URL without publishing")
    parser.add_argument("--publish", action="store_true", help="Publish the controlled sequence through MQTT")
    parser.add_argument("--wait-for-ready", action="store_true",
                        help="After price/start, wait for terminal Enter before publishing any Meter events")
    parser.add_argument("--pause-after-start", type=float, default=45.0)
    parser.add_argument("--meter-interval", type=float, default=2.0)
    args = parser.parse_args(argv)
    if args.charger_id <= 0 or args.pause_after_start < 45 or args.meter_interval < 2:
        parser.error("charger ID must be positive; pause must be >=45 s and meter interval >=2 s")
    if args.prepare == args.publish:
        parser.error("Choose exactly one of --prepare or --publish")
    if args.prepare and args.wait_for_ready:
        parser.error("--wait-for-ready is only meaningful with --publish")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = f"http://127.0.0.1:8080/?run_id={args.run_id}"
    print(f"Run ID: {args.run_id}\nCharger ID: {args.charger_id}\nDashboard URL: {url}")
    if args.prepare:
        print("Start the Dashboard and broker, then run this command again with --publish.")
        return 0
    events = build_demo_events(args.run_id, args.charger_id)
    with YSimpleMqttRepository(host=args.host, port=args.port, interval=0.1, is_inline_broker=False) as publisher:
        publisher.send_event(events[0])
        publisher.send_event(events[1])
        message = (
            "Published price_update and session_start.\n"
            f"Run ID: {args.run_id}\nCharger ID: {args.charger_id}\nDashboard URL: {url}\n"
            "Select this new Run once in the Dashboard dropdown, then select Station #4.\n"
        )
        if args.wait_for_ready:
            print(message + "Press Enter here only after Charging Progress is visible. Ctrl+C exits without Meter or session_end events.")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                print("Demo stopped before Meter publishing; no Meter or session_end event was sent.")
                return 130
        else:
            print(message + f"Meter publishing begins in {args.pause_after_start:g} seconds.")
            sleep(args.pause_after_start)
        for event in events[2:-1]:
            publisher.send_event(event)
            print(f"Published meter {event.payload['energy_kwh']:.2f} kWh at simulated {event.ts:%H:%M:%S} UTC")
            sleep(args.meter_interval)
        publisher.send_event(events[-1])
        print("Published session_end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
