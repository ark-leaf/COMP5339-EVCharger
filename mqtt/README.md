# LAN MQTT broker

This setup runs Mosquitto in Docker on A's computer. B can run on another computer
on the same Wi-Fi/LAN, or on A's computer.
Open Docker Desktop first, then run every command below from the repository root.

## Start the broker

```bash
docker compose -f compose.mqtt.yaml up -d
docker compose -f compose.mqtt.yaml ps
```

The publisher and B's subscriber use these settings:

| Setting | Value |
|---|---|
| Publisher host on A's computer | `127.0.0.1` |
| Subscriber host on B's computer | A's LAN IP, e.g. `192.168.1.3` |
| Subscriber host when running on A's computer | `127.0.0.1` |
| Port | `1883` |
| Subscription | `evc/#` |
| QoS | `1` |
| Username/password | None |
| TLS | Disabled |

The host port is bound to `0.0.0.0` by default to accept LAN connections. B must
use A's actual LAN IP, not `0.0.0.0` or `localhost`. These instructions assume the
Python programs run directly on their respective computers. The broker does not store event history; B stores
the received events in DuckDB. Keep Docker and the broker running during a replay.

Find A's IP in macOS System Settings > Wi-Fi > Details > TCP/IP. It was
`192.168.1.3` during setup on 2026-10-25, but it can change after reconnecting.
B does not need to start another broker. Allow Docker's incoming connections if
macOS asks. Guest/campus Wi-Fi may block communication between devices.
This anonymous broker is for a trusted LAN; do not forward port 1883 to the Internet.

To switch back to local-only access, run this command before the next replay:

```bash
MQTT_BIND_ADDRESS=127.0.0.1 docker compose -f compose.mqtt.yaml up -d
```

Changing the binding recreates the broker and disconnects existing clients. The
ordinary start command above restores LAN access unless `MQTT_BIND_ADDRESS` is
overridden in your environment or `.env`.

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

After enabling LAN access, a [LAN address check](../docs/ass2_mqtt_lan_validation.json)
also passed: three QoS 1 diagnostic messages were published through localhost and
received through `192.168.1.3`. Both clients ran on A's computer; B still needs to
confirm access from the second computer and verify database writes.

## Run B's database integration

Start B's subscriber on B's computer, using A's LAN IP and port 1883, and wait
until its `evc/#` subscription is acknowledged.
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
