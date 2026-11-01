# NSW EV Charging: Data Pipeline, Event Streaming and Live Dashboard

<!-- USYD CODE CITATION ACKNOWLEDGEMENT: Claude (Anthropic) assisted with revising this document. OpenAI Codex assisted with submission fixes and verification. -->

This project cleans, augments and loads NSW EV charging station data into a DuckDB database
with spatial support, then simulates charging activity on those stations and streams it as
events through MQTT to an event store and a live map dashboard.

## Project Overview

**Assignment 1: a three-stage data pipeline** (`main_ass_1.py`)

1. **Data Cleaning**: validates and cleans raw NSW EV charging station data
2. **Data Augmentation**: enriches it with external sources and address details
3. **Data Loading**: loads it into a DuckDB database with spatial support

**Assignment 2: an event-driven publish–subscribe system** (`main_ass_2.py`)

1. **Generate**: simulate charging sessions, meter readings and prices for the Assignment 1 stations
2. **Publish**: send each event to an MQTT broker
3. **Store**: a subscriber validates each event and saves it in DuckDB
4. **Show**: a second subscriber updates a live NiceGUI map dashboard

## System Requirements

- **Python**: 3.12 or higher (numpy 2.5 needs 3.12; tested with Python 3.14.3)
- **Operating System**: Windows, macOS, or Linux
- **Disk Space**: ~500MB for raw data and ~200MB for processed outputs
- **Memory**: 4GB RAM minimum (8GB recommended)
- **Optional**: Docker Desktop, to run a Mosquitto broker instead of the built-in one;
  Node.js is only needed for the included development tests

## Installation

### 1. Extract the Project

Extract the project .zip file to your desired location:

On Windows: Right-click the .zip file and select "Extract All..."
On macOS/Linux: unzip COMP5339-EVCharger.zip

### 2. Create Virtual Environment

On Windows:
```
python -m venv .venv
.\.venv\Scripts\activate
```

On macOS/Linux:
```
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```
pip install -r requirements.txt
pip install -r requirements-dashboard.txt
```

| Package | Used for |
|---|---|
| pandas, numpy | Data manipulation and CSV processing |
| geopandas, shapely, pyogrio, pyproj | Geospatial data, shapefiles and coordinate conversion |
| duckdb | Embedded SQL database with the spatial extension |
| requests, pytz | Downloads and time zones |
| paho-mqtt | MQTT client for publishing and subscribing |
| amqtt | Built-in (inline) MQTT broker used by `main_ass_2.py` |
| nicegui (`requirements-dashboard.txt`) | Live dashboard |

Dependency versions are specified in the two requirements files. The dashboard has been checked with NiceGUI 3.18.0.

### 4. Data Files

The Assignment 2 database and replay data are included; no Assignment 1 rerun is needed.
The Assignment 1 code and station CSVs are retained for provenance. Rebuilding Assignment 1
requires its full external/reference assets, including the SA4 boundary dataset.

Assignment 1 station source files use the data/src_data/ directory:
- nsw_ev_charging.csv

Included data and runtime output directories:
- data/clean_src_data/ - Cleaned output
- data/aug_data/ - Augmented output
- data/db/ - Database files
- data/result_data/ - Final results
- data/ass2_generated/ - Submitted generated source data
- data/replay/ - Submitted MQTT event records
- data/ass2_demo/ - Created when the default demo is run

## Configuration

File locations are centralized in config.py. Key settings:

```
PROJECT_ROOT = Path(__file__).parent.resolve()
DATA_ROOT = PROJECT_ROOT / "data"
SRC_DATA_FILE_LOCATION = DATA_ROOT / "src_data"
CLEAN_SRC_DATA_FILE_LOCATION = DATA_ROOT / "clean_src_data"
AUG_DATA_FILE_LOCATION = DATA_ROOT / "aug_data"
RESULT_DATA_FILE_LOCATION = DATA_ROOT / "result_data"
# Assignment 2
ASS2_GENERATED_DATA_FILE_LOCATION = DATA_ROOT / "ass2_generated"
ASS2_DEMO_DATA_FILE_LOCATION = DATA_ROOT / "ass2_demo"
```

Database files are set in config.py too:

```
DB_ROOT = PROJECT_ROOT / "db"
DB_SCHEMA = DB_ROOT / "schema" / "nsw_evc_schema.sql"                # Assignment 1 tables
DB_EVENTS_SCHEMA = DB_ROOT / "schema" / "nsw_evc_events_schema.sql"  # Assignment 2 event tables
DB_DATA = DATA_ROOT / "db" / "nsw_evc.db"                            # one database for both
```

Assignment 2 settings:

```
MQTT_HOST = "localhost"            # broker host
MQTT_PORT = 1883
MQTT_TOPIC_ROOT = "evc"            # topics are evc/{event_type}/{charger_id}
MQTT_QOS = 2                       # every publisher and subscriber
MQTT_PUBLISH_INTERVAL_SECONDS = 0.2  # minimum gap between published events
DASHBOARD_PORT = 8081
```

These environment variables override config.py without editing it:

| Variable | Overrides |
|---|---|
| `COMP5339_DB_DATA` | `DB_DATA`, the database file |
| `MQTT_HOST`, `MQTT_PORT` | The broker address, e.g. another computer's LAN IP |
| `DASHBOARD_PORT` | The dashboard's HTTP port |
| `ADDRESS_ENRICHER_ALLOW_NETWORK` | Set to `1` to let address enrichment call online geocoding; otherwise it uses its cache |

All paths are absolute and portable across different working directories and operating systems.

## Assignment 1: Running the Pipeline

Run every command from the repository root.

### Quick Start

Run the complete pipeline:
```
python main_ass_1.py
```

This executes all stages sequentially:
1. Data cleaning
2. Data augmentation
3. Database loading

### Running Individual Stages

```
python main_ass_1.py --stage clean
python main_ass_1.py --stage augment
python main_ass_1.py --stage load
```

## Database Schema

Assignment 1 creates 6 tables ([`db/schema/nsw_evc_schema.sql`](db/schema/nsw_evc_schema.sql)):

### operator
- operator_id (INTEGER, PRIMARY KEY)
- operator_name (VARCHAR)
- operator_name_normalised (VARCHAR)

### sa4_region
- sa4_code (VARCHAR, PRIMARY KEY)
- sa4_name (VARCHAR)
- geometry (GEOMETRY) - ABS SA4 boundary

### charger_location
- charger_id (INTEGER, PRIMARY KEY)
- source_objectid (BIGINT)
- station_name (VARCHAR)
- station_address (VARCHAR)
- operator_id (INTEGER, FOREIGN KEY → operator.operator_id)
- latitude (DOUBLE)
- longitude (DOUBLE)
- postcode (VARCHAR)
- lga_name (VARCHAR)
- source_category (VARCHAR)
- geom (GEOMETRY) - point geometry in GDA2020 (EPSG:7844)
- sa4_code (VARCHAR, FOREIGN KEY → sa4_region.sa4_code; NULL when no region was confirmed)

### charger_characteristic
- charger_id (INTEGER, PRIMARY KEY, FOREIGN KEY → charger_location.charger_id)
- charger_type (VARCHAR)
- number_of_plugs (INTEGER)
- rating_raw (VARCHAR)
- rating_kw (DOUBLE) - Normalized power rating

### charger_connector
- charger_connector_id (INTEGER, PRIMARY KEY)
- charger_id (INTEGER, FOREIGN KEY → charger_location.charger_id)
- connector_type (VARCHAR)
- UNIQUE(charger_id, connector_type)

### charger (Augmentation Records)
- augmentation_id (INTEGER, PRIMARY KEY)
- charger_id (INTEGER, FOREIGN KEY → charger_location.charger_id)
- external_source (VARCHAR)
- external_station_id (VARCHAR)
- external_operator (VARCHAR)
- external_number_of_plugs (INTEGER)
- external_power_kw_min (DOUBLE)
- external_power_kw_max (DOUBLE)
- external_usage_cost (VARCHAR)
- augmentation_match_method (VARCHAR)
- augmentation_match_confidence (DOUBLE)
- augmentation_quality_review_reason (VARCHAR)
- external_opening_hours (VARCHAR)
- external_network (VARCHAR)
- external_access_condition (VARCHAR)
- external_is_free (BOOLEAN)
- augmentation_quality_review (BOOLEAN)
- external_attributes_json (JSON)

### Assignment 2 event tables

Assignment 2 adds `charger_event` (the event log), `charger_state` and `connector_state`
(the latest state of each charger and connector) to the same database
([`db/schema/nsw_evc_events_schema.sql`](db/schema/nsw_evc_events_schema.sql)). They are
created automatically on the first `main_ass_2.py` run. The DDL contains the payload columns,
foreign keys and indexes used for station/time/type/connector queries.

## Data Processing Details

### Address Enrichment

The pipeline enriches addresses using geolocation services:
- Converts latitude/longitude to detailed addresses
- Matches partial addresses to complete addresses
- Fills in missing postcode information

Results are cached in `data/result_data/task2_nominatim_cache.json`. Online lookups run only
when `ADDRESS_ENRICHER_ALLOW_NETWORK=1`.

### Charger Location Storage

Charger locations are stored with:
- Point geometry in GDA2020 (EPSG:7844), converted from the source's WGS84 (EPSG:4326) coordinates
- Operator mapping
- Postcode, LGA and SA4 region

## Output Files

After running the pipeline:

1. **data/clean_src_data/nsw_ev_charging.csv** (~8MB)
   - Cleaned NSW data with validated columns
   - Enriched addresses
   - Standardized data types

2. **data/aug_data/nsw_ev_charging.csv** (~15MB)
   - Augmented data with external sources
   - Match confidence scores
   - Review flags

3. **data/db/nsw_evc.db** (~30MB)
   - Complete DuckDB database
   - Spatial indexes

## Assignment 2: Event Streaming and Dashboard

### Quick Start

The database must hold the Assignment 1 tables. The committed `data/db/nsw_evc.db` has them;
otherwise run `python main_ass_1.py` first. Then:

```
python main_ass_2.py
```

One process then:

1. starts a built-in MQTT broker (amqtt) on `localhost:1883`;
2. starts two subscribers to `evc/#`: `database-update`, which stores events, and
   `dashboard-update`, which feeds the dashboard;
3. serves the dashboard at <http://127.0.0.1:8081/>;
4. generates a small demo dataset (3 stations, 1 day) in `data/ass2_demo/`, waits 10 seconds
   so you can open the dashboard, and publishes each event once.

The dashboard stays open after publishing; stop it with Ctrl+C. Each default run replaces the
previous demo dataset but keeps its downloaded AEMO prices.

| Option | Effect |
|---|---|
| `--external-broker` | Use a broker that is already running (e.g. Mosquitto) instead of the built-in one |
| `--host`, `--port` | The broker address |
| `--dashboard-port`, `--dashboard-host` | Where the dashboard listens |
| `--dashboard-delay SECONDS` | Wait before publishing (default 10) |
| Any generator option | Passed to the generator instead of the demo settings, e.g. `--out data/ass2_generated --days 3` |

More detail: [unified entry point](docs/part_c_unified_entrypoint.md).

### Architecture

```mermaid
flowchart LR
    A1[("DuckDB<br/>Assignment 1 stations")] -->|"EVChargerInfoDAO"| GEN("Generator<br/>data_generator_daemon")
    GEN -->|"PUBLISH evc/{type}/{charger_id}<br/>QoS 2"| BROKER["MQTT broker<br/>amqtt inline or Mosquitto"]
    BROKER --> SUB1("database-update subscriber<br/>save_event()")
    BROKER --> SUB2("dashboard-update subscriber<br/>DashboardLiveService")
    SUB1 -->|"EVChargerEventDAO"| EV[("DuckDB<br/>event tables")]
    EV -->|"history when a page opens"| UI["NiceGUI dashboard"]
    SUB2 -->|"live events"| UI
```

The broker decouples the generator from the two subscribers, and each subscriber receives its
own copy of every event. Only `database-update` writes to DuckDB. The generator and the
dashboard read through the same process-wide connection, because DuckDB lets only one process
open the file read-write. The diagram above shows the runtime data flow; SQL access is encapsulated in the DAOs.

The code is layered:

| Layer | Folder | Contents |
|---|---|---|
| Presentation | `view/` | NiceGUI dashboard |
| Application | `transaction_scripts/`, `main_ass_2.py` | Generate and publish; store events; wiring |
| Domain | `event/`, `entity/` | `YEvent`, `EVChargerStateEvent`, `EVCharger`, `EVChargerState` |
| Data access | `repository/` | `EVChargerEventDAO`, `EVChargerInfoDAO`, shared DuckDB connection |
| Infrastructure | `data_utils/` | MQTT client, inline broker and subscribers; DuckDB connection wrappers; file helpers |

Design patterns used:

- **Publish–subscribe** over MQTT (Eugster et al., 2003; Hohpe & Woolf, 2003).
- **Transaction Script** for storing events, and **Domain Model** for the state rules in
  `EVChargerState.apply()` (Fowler, 2002).
- **Data Access Object** for all SQL (Alur et al., 2003).
- **Event log with stored state**: `charger_event` is append-only, the state tables are
  updated in the same transaction, and a charger's state is rebuilt by replaying its events
  after a restart (Fowler, 2005).
- **Idempotent receiver**: event ids are stable, so replays and redeliveries are skipped
  (Hohpe & Woolf, 2003).
- **Observer** callbacks for subscribers and **Adapter** around the supplied generator
  (Gamma et al., 1994).

`YSimpleMqttRepository`, `DuckDBRepository` and `SharedDuckDBRepository` are named
"Repository" but act as gateways and connection wrappers, not Repositories in the
Domain-Driven Design sense; the DAOs do the data access.

### Dashboard

The dashboard shows the NSW charging network on a map, with markers coloured by status
(available, charging, full, unknown). Selecting a station shows its connectors, current
session, price and connector timeline. It also has live charging monitoring, historical
analytics (events by type, top stations by completed sessions) and a run selector with a
Live button.

To run the dashboard on its own against an already-running broker (it reads the database but
stores nothing):

```
python -m view.dashboard_daemon
```

### Events

Topics are `evc/<event_type>/<charger_id>`, published and subscribed at QoS 2. Each payload is
a JSON `EVChargerStateEvent` with `run_id`, `id`, `type`, `ts`, `object_id`, `session_id`,
`connector_id` and `payload`. The four types are `price_update`, `session_start`, `meter` and
`session_end`. `object_id` is the Assignment 1 `charger_id` as text;
`EVChargerStateEvent.charger_id` returns it as an integer. Each event id is a UUID derived
from the run, type, charger, session, connector and time, so replaying a run resends the same
ids; compare unique `id` counts for the same `run_id`.

### Using a Mosquitto broker on the LAN

For a broker on A's computer, follow the [LAN MQTT setup](mqtt/README.md): start Docker
Desktop and run `docker compose -f compose.mqtt.yaml up -d`. A connects to `127.0.0.1:1883`;
B on another computer on the same LAN connects to A's LAN IP on port `1883` (set `MQTT_HOST`).
Run `main_ass_2.py --external-broker` to use it. The submitted event IDs and station mapping
are described in the Events and Submitted dataset sections below.

### Data generator

The generator files are in `transaction_scripts/data_generation_and_publishing/`
and follow Yeh's layout:

- `data_generator_config.py`: dates, paths, seed and simulation settings.
- `data_generator_utils.py`: station adaptation, AEMO prices, CSV generation and ordered events.
- `data_generator_replay.py`: turns a dataset back into events, optionally for a time window.
- `data_generator_daemon.py`: reads stations through `EVChargerInfoDAO`, runs generation,
  and optionally publishes events using Paho MQTT.

MQTT defaults come from `config.py` through `repository.repo_config.mqtt_config()`;
CLI options override them. The configuration keys match Yeh's helpers, while the
shared topic root remains `evc`. Station reads through `DuckDBRepository` are read-only;
inside `main_ass_2.py` the generator reads through the shared connection instead.

The supplied `generate_dataset.py` is kept separately in the same directory. The wrapper
calls its price loader, tariff, arrival sampler and session simulator instead of
maintaining a second implementation in `utils`. The supplied copy has documented
project adaptations for complete observed prices, macOS CA certificates, AC charging,
power caps and the final meter reading. Use the daemon or `main_ass_2.py` as the entry point.

Run these commands from the repository root. The database defaults to `data/db/nsw_evc.db`;
pass `--db` to use another Assignment 1 database.

```bash
# Small offline run for integration.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_small --start 2026-09-15 --days 1 --limit 2 --meter-every 5

# Full offline run, kept separate from the small one.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_new --start 2026-09-14 --days 3 --charger-type DC \
  --target-sessions 4000 --focus-region Sydney --meter-every 2 --export-events

# Publish an existing dataset to a running broker. Start a subscriber first, e.g.
# `python -m view.dashboard_daemon`. Replace localhost with the broker's IP if it is remote.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_small --replay --publish --host localhost --port 1883
```

Without options, the generator writes 3 days starting on the 15th of the previous completed
month, for every eligible DC station, with a meter reading every 2 minutes, to
`data/ass2_generated/`. `--charger-type all` includes AC stations, and `--limit N` keeps the
first N stations. Every session keeps its last meter reading. An existing dataset is never
overwritten: use a new `--out`, or `--replay` to reuse it.

Publishing sends one event at a time and waits for the broker's acknowledgement. Events are at
least `MQTT_PUBLISH_INTERVAL_SECONDS` (0.2 seconds) apart; `--interval` can lower this to 0.1
seconds. A large dataset can therefore take days to publish.

Outputs are `stations_input.csv`, `stations.csv`, `prices_hourly.csv`, `sessions.csv`,
`session_metering.csv` and `manifest.json`, plus an `aemo_cache` directory. With `--publish`
or `--export-events`, `prepared_events.json` holds every event; with `--publish`,
`published_events.json` holds the acknowledged ones. The manifest records the run ID, seed,
period, source and counts.

Prices use real AEMO `TRADE`/`ACTUAL` five-minute observations, averaged hourly and
converted from AUD/MWh to AUD/kWh. Missing intervals cause an error instead of silently
filling prices. All source times use fixed AEST (UTC+10); event entities normalize them to
UTC. Only the first price and actual retail-price changes are published. Event ordering
preserves final meter readings, session endings and subsequent reuse of the same connector.

Simulation assumptions are explicit. Only stations of type AC or DC with a positive plug
count, at least one connector record and an augmentation record generate events, and each
plug becomes one simulated connector. All sites use the configured urban default. A missing
power rating defaults to 7 kW AC or 50 kW DC, and each station's assumptions are recorded in
`stations.csv`. AC uses an assumed 11 kW onboard limit, 90% efficiency and a 16-hour cap; DC
follows the supplied teaching script's vehicle mix and taper model with a 4-hour cap. These
are synthetic assumptions, not observed station behaviour.

The submitted replay was checked through the actual broker and both subscribers: all
8,037 acknowledged events matched the stored IDs, payloads and current states. Only initial
and changed prices were sent; the full three-day source dataset need not be replayed.

The implementation adapts the supplied COMP5339 `generate_dataset.py`, with AI
assistance acknowledged in the source files. References for the time convention and
MQTT acknowledgement API: [AEMO market time](https://markets-portal-help.docs.public.aemo.com.au/Content/MSATSb2bValidationModule/RulesProcedures.htm),
[Paho Python client](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).

### Submitted dataset and replay

The teacher's Ed clarification replaces the original 14-day target with at least 10,000
hourly prices and about 4,000 sessions, and allows a selected replay window. This package
contains 282 eligible DC stations, 1,170 simulated ports, 20,304 hourly prices, 4,000 sessions
and 59,394 meter samples for 14–16 September 2026. The 151 other DC locations lack the team's
required augmentation/connector records and are excluded. No missing port counts are invented.

The exact-budget schedule gives the 513 Sydney focus ports 1–3 sessions per day and every
other selected port one session over the period. Daily totals are 1,358 / 1,334 / 1,308.
This is a documented synthetic coverage assumption; charging physics remain the supplied model.

| Path | Contents |
|---|---|
| `data/ass2_generated/stations_input.csv` | Teacher-format station input CSV |
| `data/ass2_generated/stations.csv` | Station metadata and simulation assumptions |
| `data/ass2_generated/prices_hourly.csv` | Complete hourly prices |
| `data/ass2_generated/sessions.csv` | Complete charging sessions |
| `data/ass2_generated/session_metering.csv` | Complete meter samples |
| `data/ass2_generated/manifest.json`, `aemo_cache/` | Generation parameters and real AEMO source data |
| `data/replay/prepared_events.json`, `published_events.json` | The events prepared and actually published for the submitted replay |
| `data/replay/manifest.json` | Replay window, counts and database checksum |
| `data/db/nsw_evc.db` | Ass1 data and the matching subscriber-side event/state tables |

The submitted replay selects 15 September 09:00–13:00 AEST plus necessary original prior
context. It contains 564 price updates (initial and changed prices), 473 session starts,
6,570 meters and 430 session ends. All 8,037 events are stored; 43 sessions remain active at the
window boundary. Every simulated station has two different price observations. Source CSVs
and event JSON use the same run ID, `ce30be5c1b314ffca5c7783fb4f408d5`.

`connector_id` in MQTT is a station-local physical port number, stored as `connector_no`.
It is not the Ass1 `charger_connector_id`, which identifies a connector-type row. Meter energy
is cumulative within a session and should not be summed as increments. Message times use UTC;
source generation/replay boundaries use fixed AEST; the dashboard labels its display zone.

To replay the included data through Yeh's unchanged unified entry point:

```bash
python main_ass_2.py --replay --out data/ass2_generated \
  --window-start 2026-09-15T09:00 --window-end 2026-09-15T13:00 \
  --events-out data/replay_again --interval 0.2
```

The default 0.2-second interval makes this about a 27–30-minute replay. A repeated run is deduplicated
by stable event IDs. To watch new state being built from empty event tables, prepare a database
copy, then select it with the existing `COMP5339_DB_DATA` override:

```bash
python -c "from pathlib import Path; import shutil, duckdb; shutil.copy2('data/db/nsw_evc.db', 'data/db/replay_copy.db'); db=duckdb.connect('data/db/replay_copy.db'); db.execute(Path('db/schema/nsw_evc_events_schema.sql').read_text()); db.close()"
```

On macOS/Linux, prefix the replay command with `COMP5339_DB_DATA=data/db/replay_copy.db`.
On Windows PowerShell, first run `$env:COMP5339_DB_DATA='data/db/replay_copy.db'`.
Use an unused copy filename/output directory for each run. The source database remains the
submitted evidence. Stop programs using a database before opening it in another process.

The marker popup now includes a completed-session count and an active session's energy curve;
the existing detail-panel charts remain available. FIND uses the Leaflet map-method API to
centre on the selected station. The group's report and AI usage form are submitted separately.
The application uses `data/db/nsw_evc.db`, which contains the Assignment 1 data and the
matching formal event/state tables. Formal replay counts and checksums are recorded in
`data/replay/manifest.json`. The default three-station demo creates `data/ass2_demo/`
when run; its generated files are not included in the submission.

## Project Structure

```text
COMP5339-EVCharger/
├── main_ass_1.py                # Assignment 1: clean → augment → load
├── main_ass_2.py                # Assignment 2: broker, generator, storage and dashboard in one run
├── config.py                    # Paths, MQTT and dashboard settings
├── README.md                    # This file
├── requirements.txt             # Pipeline, generator and MQTT dependencies
├── requirements-dashboard.txt   # NiceGUI for the dashboard
├── compose.mqtt.yaml            # Optional Mosquitto broker (Docker)
├── pipeline/                    # Assignment 1 stages: data_clean, data_aug, data_load
├── event/                       # Event types: YEvent, EVChargerStateEvent
├── entity/                      # Domain entities: EVCharger, EVChargerState
├── repository/                  # DAOs and the shared DuckDB connection (utils/)
├── transaction_scripts/
│   ├── data_generation_and_publishing/  # Generator, replay and publisher
│   └── stateful_event_storage/          # Event storage for the database-update subscriber
├── view/                        # NiceGUI dashboard
├── data_utils/                  # MQTT client, broker and subscribers; DuckDB and file helpers
├── db/
│   └── schema/
│       ├── nsw_evc_schema.sql          # Assignment 1 tables
│       └── nsw_evc_events_schema.sql   # Assignment 2 event tables
├── mqtt/                        # Mosquitto configuration and LAN setup guide
├── docs/                        # Event schema, data flow and unified-entry usage
└── data/                        # Submitted data and runtime output directories
    ├── src_data/                # Source data
    ├── clean_src_data/          # Cleaned output
    ├── aug_data/                # Augmented output
    ├── result_data/             # Final results
    ├── db/                      # Database files
    ├── ass2_generated/          # Submitted three-day generated dataset
    └── replay/                  # Actual published events and replay manifest
```
