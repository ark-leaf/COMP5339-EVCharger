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
| QoS | `2` (`MQTT_QOS` in `config.py`) |
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
`--topic-prefix` and `--interval` options override the shared defaults.

To switch back to local-only access, run this command before the next replay:

```bash
MQTT_BIND_ADDRESS=127.0.0.1 docker compose -f compose.mqtt.yaml up -d
```

Changing the binding recreates the broker and disconnects existing clients. The
ordinary start command above restores LAN access unless `MQTT_BIND_ADDRESS` is
overridden in your environment or `.env`.

## Recorded broker checks

A [real-broker check](../docs/ass2_mqtt_validation.json) of an earlier two-station
sample passed on 2026-10-25 with Mosquitto 2.1.2: 4,191 published and received events,
zero duplicates, and no active sessions at completion. The report records the exact
tested image digest. That sample and its checker have since been removed.

After enabling LAN access, a [LAN address check](../docs/ass2_mqtt_lan_validation.json)
also passed: three QoS 1 diagnostic messages were published through localhost and
received through `192.168.1.3`. Both clients ran on A's computer; B still needs to
confirm access from the second computer and verify database writes.

## Run the pipeline through this broker

With the broker running, run generation, storage and the dashboard against it:

```bash
python main_ass_2.py --external-broker
```

The generator publishes each event once with QoS 2, and the broker delivers it to both
the storage subscriber and the dashboard subscriber. `--host` and `--port` select another
broker; they default to `MQTT_HOST` and `MQTT_PORT`. See the
[unified entry point](../docs/part_c_unified_entrypoint.md), and the
[A to B handoff](../docs/ass2_a_to_b_handoff.md) for IDs and storage semantics.

## Compact replay validation

The generator also supports a bounded daytime replay that preserves the original event
IDs and emits preceding price/open-session context. See the
[dataset v2 handoff](../docs/ass2_dashboard_dataset_v2.md).

## Inspect or stop the broker

```bash
docker compose -f compose.mqtt.yaml logs --tail=30 mqtt
docker compose -f compose.mqtt.yaml down
```

Configuration reference: [Mosquitto configuration manual](https://mosquitto.org/man/mosquitto-conf-5.html).
OpenAI Codex assisted with this setup, verification script and documentation.
