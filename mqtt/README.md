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

When using Yeh's MQTT helpers, set `MQTT_HOST` in B's terminal before starting the
subscriber, for example `export MQTT_HOST=192.168.1.3`. Both sides use the shared
`mqtt_config()` settings with topic root `evc`, not Yeh's original `comp5339/evc`.
Restart the subscriber after changing its environment. A's `--host`, `--port`,
`--topic-prefix` and `--interval` options override the shared defaults. The default
publication delay is now 1 second per event, including the storage integration check.

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
.venv-mqtt/bin/python -m pip install duckdb==1.5.5 paho-mqtt==2.1.0 pytz
```

## Publish the current registered-station dataset

Use `data/ass2_registered_3day`, described in the [current handoff](../docs/ass2_a_to_b_handoff.md).
The bundled two-station example and old full-DC datasets are historical; the current
publisher rejects their unscoped manifests. Do not run the old sample transport check
as the current assignment acceptance test.

Start B's subscriber against the shared Ass1 snapshot and wait for SUBACK on `evc/#`.
Then publish from A's computer:

```bash
.venv-mqtt/bin/python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_registered_3day --replay --publish \
  --window-start 2026-09-15T09:00 --window-end 2026-09-15T11:00 \
  --events-out data/ass2_registered_3day/replay_to_b \
  --host 127.0.0.1 --port 1883
```

The exported `published_events.json` is the delivery list; compare its event IDs and
payloads against B's database. Replaying the same run must not add duplicate rows.
This window includes earlier original context messages for ongoing sessions.

For a local check of the publisher and Yeh's existing subscriber/store in a new DB copy:

```bash
.venv-mqtt/bin/python -m scripts.check_mqtt_storage \
  --data-dir data/ass2_registered_3day --db /path/to/shared-ass1.duckdb \
  --out data/ass2_registered_3day/new_mqtt_check \
  --window-start 2026-09-15T09:00 --hours 2 --host 127.0.0.1 --port 1883
```

The checker starts its own test subscriber, so run it on an isolated broker if B or
other clients are already consuming `evc/#`. Do not start `main_ass_2.py` on an occupied
broker port: the current dengjie entry point starts an inline broker. The standalone
A command above connects to an existing broker unless `--inline-broker` is supplied.

## Inspect or stop the broker

```bash
docker compose -f compose.mqtt.yaml logs --tail=30 mqtt
docker compose -f compose.mqtt.yaml down
```

Configuration reference: [Mosquitto configuration manual](https://mosquitto.org/man/mosquitto-conf-5.html).
OpenAI Codex assisted with this setup, verification script and documentation.
