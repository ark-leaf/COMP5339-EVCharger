# Assignment 2: current A-to-B handoff

Updated 2026-10-29. The delivery branch for this revision is `dengjie`. It replaces the old 433-station handoff with a 282-station dataset.
Yeh's subscriber, event store, event schema and entity/JSON contract are unchanged.
The dashboard is outside this revision.

## Source selection and identifiers

The team's input rule is now: a generated station must exist in `charger_location`,
`charger_characteristic`, `charger` AND `charger_connector`, have type DC, and have
a positive original `number_of_plugs`. The DAO uses `EXISTS` so multiple connector
TYPE rows do not duplicate a station. It excludes 151 of the source's 433 DC stations
because their augmentation/connector records are missing. This does not assert that
those real-world stations do not exist; they are outside this team's selected input.

| Identifier | Meaning |
|---|---|
| input `station_id`, CSV `charger_id`, MQTT `object_id` | The same original Ass1 station ID; MQTT encodes it as a string. |
| MQTT `connector_id`, B `connector_no` | A simulated physical port numbered 1 through that station's original plug count. |
| `(charger_id, connector_no)` | The pair identifying one simulated port; port numbers repeat between stations. |
| Ass1 `charger_connector_id` | A global connector-TYPE record key; it is **not** the simulated physical port number. |

For example, station 6 has 16 plugs but only one connector-type row (key 4). Its
simulation ports are 1–16, not just port 4. `station_source_audit.csv` preserves the
source connector-type IDs and labels for each station, and `connector_coverage.csv`
lists all generated station/port pairs. There is no fabricated one-to-one mapping
from physical ports to connector-type keys. B must keep its existing `connector_no`
meaning; do not add a foreign key from it to `charger_connector_id`.

## Current data and teacher requirements

Use **`data/ass2_registered_3day/`**, run
`ce30be5c1b314ffca5c7783fb4f408d5`, for this handoff. The source is the same shared
Ass1 snapshot used for the checks. The generator reads it without modifying it.

| Item | Current result |
|---|---:|
| Selected DC stations | 282 |
| Original-count simulated ports | 1,170 |
| Hourly price rows | 20,304 |
| Charging sessions | 4,000 |
| Meter samples | 59,394 |
| Full candidate events | 76,136 |
| Candidates by type: price / start / meter / end | 8,742 / 4,000 / 59,394 / 4,000 |
| Missing station references in `charger` or `charger_connector` | 0 |
| Invalid physical port references | 0 |

The teacher's latest clarification replaces the original 14-day requirement with
at least 10,000 hourly prices and about 4,000 sessions, allows replaying a few hours,
and requests the input/generated CSVs, 1–3 files representing actual MQTT events,
and the subscriber-side DuckDB. This profile meets the stated generation amounts.
The three simulated days are 14–16 September 2026, using real AEMO NSW1 hourly
averages, original station IDs/power/coordinates, and seed 5339.

Every selected port has a session. The 144 Sydney focus stations (513 ports) have
1–3 sessions per port per day; other ports have one session across the period.
Daily totals are 1,358 / 1,334 / 1,308. Meter interval is two minutes, with a final
sample at charge end; sessions have a median of 13 meter points. This deliberate
allocation is a documented simulation assumption. It preserves the supplied charging
physics and price sensitivity rather than claiming these are observed sessions.
No missing port counts are replaced by an invented port.

## Files and pipeline

1. `repository/evc_info_dao.py`: `list_generation_chargers()` reads eligible Ass1
   stations into `EVCharger`. General `list_chargers()` remains available unchanged.
2. `data_generator_config.py`: generation defaults, scope version and parameters.
3. `data_generator_schedule.py`: allocate the 4,000-session budget with daily coverage.
4. `data_generator_utils.py`: adapt station data, call the supplied simulator, write
   CSVs, then validate IDs/ports and convert rows to event entities.
5. `data_generator_replay.py`: retain original prices/session context for a time window.
6. `data_generator_daemon.py`: coordinate generation, JSON export and optional publish.
7. Yeh's existing `YSimpleMqttRepository` -> broker -> `YMqttEventSubscriber` ->
   `EVChargerEventStore` -> `charger_event`, `charger_state`, `connector_state`.

Generator modules above are under `transaction_scripts/data_generation_and_publishing/`.
The supplied `generate_dataset.py` remains the simulation helper. Use the project
daemon below, which applies the team's database selection before calling it.

`stations_input.csv` has the teacher's seven input columns. `stations.csv` adds
project metadata/assumptions. `prices_hourly.csv`, `sessions.csv` and
`session_metering.csv` are the complete generated data. The manifest records the
run ID, configuration and eligible station/port snapshot. The source audit and
coverage CSVs make the selection and physical-port coverage reviewable.

Generate into a **new** directory; an existing manifest is never overwritten:

```bash
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db /path/to/shared-ass1.duckdb --out data/ass2_registered_3day \
  --start 2026-09-14 --days 3 --seed 5339 --charger-type DC \
  --target-sessions 4000 --focus-region Sydney --meter-every 2 --export-events

python -m scripts.check_generator_coverage \
  --data-dir data/ass2_registered_3day --db /path/to/shared-ass1.duckdb
```

The formal `--target-sessions 4000` is explicit. Defaults without that parameter
retain random arrivals for small demos. All staged event station IDs and session
port ranges are checked before the first event is yielded. Old manifests without
the new selection scope are rejected. Do not manually mark old data as eligible.
Run the coverage checker against B's intended Ass1 database to verify the snapshot
before sharing; a manifest alone does not prove a different database has those IDs.

## Real MQTT replay and B handoff

The verified window is 15 September, 09:00–11:00 AEST. It includes earlier original
context events so ongoing sessions can be reconstructed. Source timestamps use
AEST (UTC+10); event JSON timestamps use UTC. A two-hour replay is a subset of the
three-day source data. The full 76,136-event candidate JSON is not an actual-publication
record. Only initial/changed prices are sent, with QoS 1 and a default one-second delay
between messages. The CLI `--interval` override remains available; the assignment
minimum is 0.1 seconds. At the new default, 4,058 events take at least about 68 minutes.

The recorded full-window test used the previous 0.1-second interval. It has not
been repeated in full at one second. The isolated test passed using `scripts.check_mqtt_storage.py` with Yeh's actual
subscriber and store, a fresh copy of Ass1, and a temporary Mosquitto broker.
All 4,058 events were stored: 564 price updates, 261 starts, 3,036 meters and 197
ends, including 368 context events. Stored IDs/payloads and current states match.
After 2,029 events, the subscriber and DB connection were restarted with 50 sessions
active; delivery resumed successfully. Four deliberately repeated events were
deduplicated, leaving 4,058 unique rows from 4,062 received messages. At the end,
64 sessions are still active. Every one of the 282 stations has price history.
The check took 436.1 seconds. Its temporary broker has been stopped.

Results and the actual database are in `mqtt_09_11/`. Its
prepared/published/duplicate-check JSONs are the three event JSON files to submit
with the full CSV inputs and output. The source Ass1 file and 23 archived data files
were hash-checked and remain unchanged. This local test does not verify B's LAN
connection from another computer.

For another real replay, B first starts its subscriber on `evc/#` using the shared
Ass1 snapshot. Wait for SUBACK, then A runs:

```bash
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_registered_3day --replay --publish \
  --window-start 2026-09-15T09:00 --window-end 2026-09-15T11:00 \
  --events-out data/ass2_registered_3day/replay_to_b \
  --host 127.0.0.1 --port 1883
```

Use a fresh `--events-out` to preserve previous publication evidence. A connects to
localhost; B on another computer connects to A's current LAN IP, using the same
broker/port. See [broker setup](../mqtt/README.md). A's `--db` controls source reads;
it does not configure B's database. Do not run two writers against one DuckDB file.
The standalone A entry connects to an existing broker unless `--inline-broker` is
specified. The unchanged `main_ass_2.py` entry starts an inline broker itself.

Topics remain `evc/<type>/<object_id>`; the event JSON contract remains schema
version 1 with `run_id,id,type,ts,object_id,connector_id,session_id,payload`. Price
events have null connector/session IDs. Stable event IDs make same-run replay
idempotent. Broker ACK is recorded in `published_events.json`; compare that list
with B's stored IDs, payloads and type counts to establish successful storage.

Meter energy is cumulative within a session, not an increment to sum across readings.
`session_end.ts` is unplug time; `charge_end_ts` is charge completion. Prices are
AUD/kWh, energy is kWh, power is kW, cost is AUD and SoC is a percentage.

## Verification and delivery

See [generation audit](ass2_registered_validation.json),
[real MQTT result](ass2_registered_mqtt_validation.json), and
[acceptance/reference checks](ass2_registered_acceptance.json).
After changing the default to one second, all 52 offline tests passed again. A
[five-message real-broker timing check](ass2_registered_1s_validation.json) confirmed
all publish gaps were at least one second and all payloads arrived unchanged.
The two-hour B-storage replay above remains the earlier 0.1-second validation.
The 52 relevant offline tests cover entities, DAO selection, port rules, budget,
non-overlap, replay, event conversion and publishing:

```bash
PYTHONPATH=tests python -m unittest test_data_generator test_dashboard_dataset \
  test_entities test_generator_publisher.PublisherTests test_station_repository -v
```

Despite its historical filename, `test_dashboard_dataset` checks A's dataset and
replay, not the UI. The test command excludes the four embedded-broker tests; the
real integration check uses external Mosquitto. No dashboard behavior is claimed
by this revision, and no full three-day MQTT replay is claimed.

Generated data and DuckDB files are Git-ignored and must be shared separately. Use
`data/ass2_registered_3day/ass2_registered_3day_1s_handoff.zip`, together with the
code revision on `dengjie`. The dated acceptance reports describe the earlier
validation snapshot; their MQTT timing and pre-push status are historical. Earlier one-day/433-station
results and datasets are preserved as historical records, not current replay input.
The old two-station example is historical too; its station 1 is outside this selection.

OpenAI Codex assisted with implementation, tests and documentation. Retain the source
acknowledgements, describe the selection/allocation/replay in the report, and include
the course AI usage form. Those report/submission items remain the team's responsibility.
