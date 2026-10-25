# Local MQTT broker

This setup runs Mosquitto in Docker for A and B on the same computer.
Open Docker Desktop first, then run every command below from the repository root.

## Start the broker

```bash
docker compose -f compose.mqtt.yaml up -d
docker compose -f compose.mqtt.yaml ps
```

Both the publisher and B's subscriber use these settings:

| Setting | Value |
|---|---|
| Host | `127.0.0.1` |
| Port | `1883` |
| Subscription | `evc/#` |
| QoS | `1` |
| Username/password | None |
| TLS | Disabled |

The host port is bound to localhost. These instructions assume both Python programs
run directly on this computer. The broker does not store event history; B stores
the received events in DuckDB. Keep Docker and the broker running during a replay.

## Prepare the Python environment

```bash
python3 -m venv .venv-mqtt
.venv-mqtt/bin/python -m pip install duckdb==1.5.5 paho-mqtt==2.1.0
```

## Check A's publishing through the real broker

```bash
.venv-mqtt/bin/python -m scripts.check_mqtt
```

This command starts a verification subscriber, waits for its subscription
acknowledgement, and publishes the bundled two-station sample. It checks all
4,191 unique events, topics, JSON payloads and final station states. It takes
at least seven minutes because the publisher waits at least 0.1 seconds between
messages. Do not start another publisher during this check.

The report is saved to `data/ass2_smoke/mqtt_validation.json`. This checks transport
and decoding; it does not test B's database or publish the full dataset.
The [recorded check](../docs/ass2_mqtt_validation.json) passed on 2026-10-25 with
Mosquitto 2.1.2: 4,191 published and received events, zero duplicates, and no active
sessions at completion. The Compose image tag tracks version 2; the report records
the exact tested image digest.

## Run B's database integration

Start B's subscriber first and wait until its `evc/#` subscription is acknowledged.
Then run only the publisher in another terminal:

```bash
.venv-mqtt/bin/python -m data_generator.data_generator_daemon \
  --out examples/ass2_mqtt --replay --publish --host 127.0.0.1 --port 1883
```

B should store 386 price updates, 278 session starts, 3,249 meter readings and
278 session ends for this sample run: 4,191 unique events in total. Replaying
the sample must not increase the unique event count. See the
[A to B handoff](../docs/ass2_a_to_b_handoff.md) for IDs and storage semantics.

## Inspect or stop the broker

```bash
docker compose -f compose.mqtt.yaml logs --tail=30 mqtt
docker compose -f compose.mqtt.yaml down
```

Configuration reference: [Mosquitto configuration manual](https://mosquitto.org/man/mosquitto-conf-5.html).
OpenAI Codex assisted with this setup, verification script and documentation.
