# USYD CODE CITATION ACKNOWLEDGEMENT
# OpenAI Codex assisted with this real-broker integration check.
"""Replay the small fixture through a broker and verify delivery, not B's database."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event
import time

import paho.mqtt.client as mqtt

from data_generator.data_generator_daemon import publish_events
from data_generator.data_generator_utils import generate_evc_state_update
from repository.entity.ev_charger_state import EVChargerState
from repository.event.ev_charger_state_event import EVChargerStateEvent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--report", type=Path, default=Path("data/ass2_smoke/mqtt_validation.json"))
    args = parser.parse_args()
    args.report.unlink(missing_ok=True)
    fixture = Path("examples/ass2_mqtt")
    checklist = json.loads((fixture / "mqtt_check.json").read_text())
    expected = {e.event_id: e for e in generate_evc_state_update(fixture)}
    ready, finished = Event(), Event()
    received, states, counts, errors = set(), {}, Counter(), []
    duplicates = 0

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            errors.append(f"Connection rejected: {reason_code}")
            ready.set()
        else:
            client.subscribe("evc/#", qos=1)

    def on_subscribe(client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            errors.append("Subscription rejected")
        ready.set()  # Wait for SUBACK before the publisher sends its first event.

    def on_message(client, userdata, message):
        nonlocal duplicates
        try:
            event = EVChargerStateEvent.from_json(message.payload)
            if event.run_id != checklist["run_id"]:
                return
            assert message.topic == f"evc/{event.type}/{event.station_id}"
            assert event.to_dict() == expected[event.event_id].to_dict()
            if event.event_id in received:
                duplicates += 1
                return
            if event.station_id not in states:
                states[event.station_id] = EVChargerState(event.station_id, event.run_id)
            states[event.station_id].apply(event)
            received.add(event.event_id)
            counts[event.type] += 1
            if len(received) % 500 == 0:
                print(f"Received and verified {len(received)}/{len(expected)} events", flush=True)
            if len(received) == len(expected):
                finished.set()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            finished.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, reconnect_on_failure=False)
    client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
    started = time.monotonic()
    try:
        client.connect(args.host, args.port)
        client.loop_start()
        if not ready.wait(10) or errors:
            raise RuntimeError(f"Subscriber not ready: {errors}")
        print("Subscription acknowledged; publishing the sample at >= 0.1 s intervals.", flush=True)
        published = publish_events(iter(expected.values()), host=args.host, port=args.port)
        if not finished.wait(10) or errors:
            raise RuntimeError(f"Delivery failed: {len(received)}/{len(expected)}; {errors}")
        assert published == len(received) == checklist["total_unique_events"]
        assert dict(counts) == checklist["expected_unique_events"]
        assert len(states) == 2 and all(s.active_session_count == 0 for s in states.values())
        report = dict(tested_at=datetime.now(timezone.utc).isoformat(),
                      run_id=checklist["run_id"], host=args.host, port=args.port,
                      subscription="evc/#", qos=1, published=published,
                      unique_received=len(received), duplicates=duplicates, counts=dict(counts),
                      elapsed_seconds=round(time.monotonic() - started, 1),
                      payloads_match=True, final_active_sessions=0,
                      real_broker_sample_passed=True, b_database_integration_tested=False,
                      full_dataset_published=False)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
