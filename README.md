# NSW EV Charging Station Data Processing Pipeline

A comprehensive data processing pipeline for cleaning, augmenting, and loading NSW EV charging station data into a DuckDB database with spatial analysis capabilities.

## Project Overview

This project implements a three-stage data processing pipeline:

1. **Data Cleaning**: Validates and cleans raw NSW EV charging station data
2. **Data Augmentation**: Enriches data with external information and address details
3. **Data Loading**: Loads processed data into a DuckDB database with spatial support

## System Requirements

- **Python**: 3.10 or higher (tested with Python 3.14.3)
- **Operating System**: Windows, macOS, or Linux
- **Disk Space**: ~500MB for raw data and ~200MB for processed outputs
- **Memory**: 4GB RAM minimum (8GB recommended)

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

Run:
```
pip install -r requirements.txt
```

**Recommended dependency versions:**
- pandas==3.0.5 - Data manipulation and CSV processing
- geopandas==1.1.4 - Geospatial data handling
- duckdb==1.5.5 - Embedded SQL database with spatial extension
- pyogrio==0.13.0 - Vector data I/O for shapefiles
- numpy==2.5.3 - Numerical computing
- shapely==2.1.2 - Geometric operations

If requirements.txt is not available, install manually:
```
pip install pandas==3.0.5 geopandas==1.1.4 duckdb==1.5.5 pyogrio==0.13.0 numpy==2.5.3 shapely==2.1.2
```

### 4. Data Files

Place source data files in the data/src_data/ directory:
- nsw_ev_charging.csv

Other directories will be created automatically:
- data/clean_src_data/ - Cleaned output
- data/aug_data/ - Augmented output
- data/db/ - Database files
- data/result_data/ - Final results

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
ASS2_SMOKE_DATA_FILE_LOCATION = DATA_ROOT / "ass2_smoke"
ASS2_SAMPLE_DATA_FILE_LOCATION = PROJECT_ROOT / "examples" / "ass2_mqtt"
```

Database files are set in pipeline/data_load/nsw_evc_load_config.py:

```
DB_ROOT = PROJECT_ROOT / "db"
DB_SCHEMA = DB_ROOT / "schema" / "nsw_evc_schema.sql"                # Assignment 1 tables
DB_EVENTS_SCHEMA = DB_ROOT / "schema" / "nsw_evc_events_schema.sql"  # Assignment 2 charger_event
DB_DATA = DATA_ROOT / "db" / "nsw_evc.db"                            # one database for both
```

All paths are absolute and portable across different working directories and operating systems.

## Running the Pipeline

### Quick Start

Run the complete pipeline:
```
python main.py
```

This executes all stages sequentially:
1. Data cleaning
2. Data augmentation
3. Database loading

### Running Individual Stages

Stage 1 - Data Cleaning:
```
python pipeline/data_clean_script.py
```

Stage 2 - Data Augmentation:
```
python pipeline/data_aug_script.py
```

Stage 3 - Data Loading:
```
python pipeline/data_load_script.py
```

## Database Schema

The database consists of 5 normalized tables:

### operator
- operator_id (INTEGER, PRIMARY KEY)
- operator_name (VARCHAR)
- operator_name_normalised (VARCHAR)

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
- geom (GEOMETRY) - WGS84 point geometry

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

## Data Processing Details

### Address Enrichment

The pipeline enriches addresses using geolocation services:
- Converts latitude/longitude to detailed addresses
- Matches partial addresses to complete addresses
- Fills in missing postcode information

### Charger Location Storage

Charger locations are stored with:
- Spatial geometry (WGS84 points)
- Coordinates in EPSG:7844 (GDA2020/Australia Albers)
- Operator mapping
- Postcode and LGA information

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

## Project Structure

COMP5339-EVCharger/
├── main.py                      # Main entry point
├── config.py                    # Configuration
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── pipeline/                    # Processing stages
├── data_utils/                  # Utilities
├── db/
│   └── schema/
│       └── nsw_evc_schema.sql  # Database schema
├── data/                        # All data files (auto-created)
│   ├── src_data/               # Source data
│   ├── clean_src_data/         # Cleaned output
│   ├── aug_data/               # Augmented output
│   ├── result_data/            # Final results
│   └── db/                     # Database files

## References

- NSW EV Data: Transport for NSW (TfNSW)
- Spatial Reference: GDA2020 (EPSG:7844)
- DuckDB: https://duckdb.org/docs/
- GeoPandas: https://geopandas.org/

## Contact

For issues or questions, contact the project maintainers.

## Assignment 2: data generator

For B's integration, read the [A to B handoff](docs/ass2_a_to_b_handoff.md).
For a broker on A's computer, follow the [LAN MQTT setup](mqtt/README.md):
start Docker Desktop and run `docker compose -f compose.mqtt.yaml up -d`.
A connects to `127.0.0.1:1883`; B on another computer on the same LAN connects
to A's LAN IP on port `1883`.
The versioned [two-station sample](examples/ass2_mqtt) can be replayed directly
without regenerating data. The [full validation summary](docs/ass2_full_validation.json)
records offline results. The [real-broker sample check](docs/ass2_mqtt_validation.json)
passed with 4,191 published and received events on the earlier implementation.
The previous one-day dataset passed [offline acceptance checks](docs/ass2_a_acceptance.json)
and a [real MQTT-to-B integration
check](docs/ass2_mqtt_storage_validation.json). Its 00:00-04:00 AEST replay sent and
stored 1,893 unique events for all 433 DC stations, including a subscriber restart
and four duplicate-event checks. Artifacts are in `data/ass2_dc_1day/replay_00_04/`:
the prepared/published JSON, subscriber DuckDB and validation report. The full
one-day CSVs remain unchanged; the updated requirements allow a shorter replay.

The **three-day dashboard dataset** is described in the [v2 handoff](docs/ass2_dashboard_dataset_v2.md).
It retains all 433 DC stations, uses 31,176 hourly prices and exactly 4,000 sessions,
and covers every one of the 1,658 simulated ports. The 513 ports at 144 augmented
Sydney stations have activity every day. Two-minute meters provide a median of 13
points per session. Old datasets remain unchanged.

```bash
# Generate into a NEW output directory; the selected directory is overwritten on regeneration.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db /path/to/shared-ass1.duckdb --out data/ass2_dc_3day \
  --start 2026-09-14 --days 3 --seed 5339 --charger-type DC \
  --target-sessions 4000 --focus-region Sydney --meter-every 2 --export-events

# Validate all ports, daily coverage, prices, meters and the complete JSON event stream.
python -m scripts.check_generator_coverage \
  --data-dir data/ass2_dc_3day --db /path/to/shared-ass1.duckdb

# Export a daytime window and its required pre-window events, without publishing.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_dc_3day --replay --export-events \
  --window-start 2026-09-15T09:00 --window-end 2026-09-15T11:00 \
  --events-out data/ass2_dc_3day/window_09_11
```

`--target-sessions` enables coverage-controlled DC arrivals: one or two sessions per
focus port/day and one per other port over the period. Focus IDs come from accepted
Ass1 augmentation records joined to SA4 regions whose name starts with `--focus-region`.
This is a documented demonstration assumption. It replaces Poisson arrival counts;
charging physics, real AEMO prices and station ratings remain unchanged. Omitting
`--target-sessions` retains the previous Poisson mode. Bounds are checked against
actual selected ports; 4,000 is appropriate for this snapshot, not every possible input.

Window boundaries are inclusive start and exclusive end. Naive ISO times mean AEST.
The export includes original earlier prices and starts/latest meters for ongoing sessions,
so B can restore live state. That context is not complete historical data. Window JSON
requires a separate `--events-out`; add `--publish` only after B is subscribed.
The full three-day export is 81,459 events (at least 2.3 hours at 0.1 s each).
Use an intentional window for live demos. A full-history offline preview database is
provided for chart development and is clearly labelled **not MQTT publication evidence**.
The [compact dataset's real MQTT check](docs/ass2_dashboard_v2_mqtt_validation.json)
passed with 3,692 identical published, received and stored events, a subscriber restart
and four duplicate checks. Its separate `mqtt_09_11/subscriber.duckdb` contains 56
active sessions at the window boundary. The complete dataset is not fully published.

The generator files are in `transaction_scripts/data_generation_and_publishing/`:

- `data_generator_config.py`: dates, paths, seed and simulation settings.
- `data_generator_schedule.py`: bounded session allocation and daily port coverage.
- `data_generator_replay.py`: window selection with original context events.
- `data_generator_utils.py`: station adaptation, AEMO prices, CSV generation and ordered events.
- `data_generator_daemon.py`: reads stations through `EVChargerInfoDAO`, closes the database,
  runs generation, and optionally publishes events through `YSimpleMqttRepository`.

MQTT defaults come from `config.py` through `repository.repo_config.mqtt_config()`;
CLI options override them. The configuration keys match Yeh's helpers, while the
shared topic root remains `evc`. Shared DuckDB settings allow writes and include
`spatial` for those helpers; A's station repository stays read-only by default.

The supplied `generate_dataset.py` is kept separately in the same directory. The wrapper
calls its price loader, tariff, arrival sampler and session simulator instead of
maintaining a second implementation in `utils`. The supplied copy has documented
project adaptations for complete observed prices, macOS CA certificates, AC charging,
power caps and the final meter reading. Use the daemon above as the project entry point.

Run these commands from the repository root. The entry point imports `duckdb` and
`paho-mqtt==2.1.0`; the optional inline broker also needs `amqtt`.
Pass the path to your existing Ass1 database with `--db`. The new default is
`data/db/nsw_evc.db`; an older `.duckdb` file is also supported and is not renamed.

```bash
# Small offline run for integration; replace --db with your snapshot's actual location.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db data/db/.duckdb --out data/ass2_smoke/simplified \
  --start 2026-09-15 --days 1 --limit 2 --meter-every 5

# One day for every DC station; keep the old data/ass2_generated dataset intact.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db data/db/.duckdb --out data/ass2_dc_1day \
  --start 2026-09-15 --days 1 --seed 5339 --charger-type DC \
  --sessions-per-connector-day 3 2 --meter-every 5

# Export the existing one-day dataset as event JSON, without MQTT or regeneration.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_dc_1day --replay --export-events

# Start B's subscriber first, then publish the small sample.
# Replace localhost with the broker's reachable IP if it runs on another computer.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_smoke/simplified --replay --publish --host localhost --port 1883

python -m unittest discover -s tests -v
```

The updated course target is at least 10,000 hourly prices and around 4,000 sessions;
14 days are no longer required. The one-day command above uses all 433 DC stations
in our Ass1 snapshot and generates 10,392 prices and 4,724 sessions. Counts depend on
the station snapshot, date and seed. The two session-rate values apply to urban and
regional sites respectively; our current simulation assumes urban sites.

`--charger-type` accepts `all` (default), `AC` or `DC`; `--limit` applies after that
filter. Omit the limit to include every matching station. The existing defaults remain
14 days and one meter reading per minute, so use the explicit one-day command above.
`--meter-every 5` reduces meter records while retaining every session's final reading
and all tail events for sessions that start before midnight. Generation is offline
unless `--publish` is supplied. The teacher permits replaying a shorter period; the
default replay publishes the entire dataset. Use the window options described below
to replay a daytime interval with its required earlier state. Both modes wait at least
0.1 seconds after each QoS 1 acknowledgement.

Outputs are `stations_input.csv`, `stations.csv`, `prices_hourly.csv`, `sessions.csv`,
`session_metering.csv` and `manifest.json`, plus an `aemo_cache` directory.
`stations_input.csv` contains the simulation's station inputs in the teacher's exact
column order: `station_id,name,lat,lon,site_type,connectors,max_kw`. Its `station_id`
is the same Ass1 identifier as `charger_id` in the project CSVs and `object_id` in MQTT.
Submit this file with the generated CSVs. It is also accepted by the supplied script's
`--stations` option. The project wrapper uses the same station records in memory;
`stations.csv` additionally retains charger type, simulation assumptions and base price
for the report. The report should describe this adapter and the generation parameters.
Existing Ass1 station names are retained; missing names use operator and address
(or the charger ID when an address is unavailable).
The manifest records the run ID,
seed, period, source and counts. Replaying these files retains event IDs for subscriber
deduplication. Topics are `evc/<event_type>/<charger_id>`; payloads are JSON objects
matching `EVChargerStateEvent`. B can decode with `from_json()`, store/deduplicate the
event, and then call `EVChargerState.apply()`. B should subscribe to `evc/#` with QoS 1
and compare unique event `id` counts for the same `run_id`, since retransmissions
can duplicate delivery. A message's `object_id` is the Ass1 `charger_id` as text;
`EVChargerStateEvent.charger_id` returns it as an integer.

The teacher's clarification (Question 6) asks for the prepared/published event list,
expecting 1-3 JSON files. `--export-events` writes `prepared_events.json` in `--out`:
one JSON array of complete event messages, in replay order, with unchanged prices
already removed. It does not publish messages. Add it to a generation command, or use
`--replay --export-events` to export existing CSVs without changing them.

`--publish` automatically exports the prepared list and records broker-confirmed
messages in `published_events.json`. A failed send is excluded; earlier confirmed
records remain a readable JSON array if publishing raises an exception or is interrupted
with Ctrl+C. Broker confirmation does not prove that B has stored the event; compare
event IDs with B's DuckDB after integration. A successful complete run has matching
prepared and published lists. Exports use the same event IDs and fields as the MQTT
payloads. Each attempt replaces its export files in the selected directory; preserve
earlier attempts separately if needed. Offline export does not create or change the
published list. The actual published list is produced only when publishing is run.

The completed four-hour replay's two submission event lists are
`replay_00_04/prepared_events.json` and `replay_00_04/published_events.json`.
`duplicate_check_events.json` records a separate four-message replay used to verify
deduplication. The parent directory's 43,769-event prepared list is the full day's
offline candidate list; it is not the list actually sent in this run.
`replay_00_04/subscriber.duckdb` contains the original Ass1 tables plus Yeh's received
event and current-state tables. Nine sessions remain active at the window boundary;
each of the 433 DC chargers has a current price and three historical price points.

To repeat the check with an existing isolated broker, use a new output directory:

```bash
python -m scripts.check_mqtt_storage --data-dir data/ass2_dc_1day \
  --db /path/to/shared-ass1.duckdb --out data/ass2_smoke/storage_check \
  --hours 4 --host 127.0.0.1 --port 18884
```

This command really publishes MQTT messages, starts Yeh's subscriber, and writes
only to a copy of the Ass1 database. It restarts the subscriber and its database
connection halfway through, then compares event IDs, payloads and current states.
It does not start a broker; prepare one on the supplied host/port first.

Prices use real AEMO `TRADE`/`ACTUAL` five-minute observations, averaged hourly and
converted from AUD/MWh to AUD/kWh. Missing intervals cause an error instead of silently
filling prices. The default period starts on the 15th of the previous completed month;
select a newer complete period explicitly when needed. All source times use fixed
AEST (UTC+10); event entities normalize them to UTC. Only the first price and actual
retail-price changes are published. Event ordering preserves final meter readings,
session endings and subsequent reuse of the same connector.

Simulation assumptions are explicit: all sites use the configured urban/regional
default; missing connector count defaults to 1, missing power to 7 kW AC or 50 kW DC.
Unknown/Upcoming sites are included as hypothetical AC stations. Each station's
assumptions are recorded in `stations.csv`. AC uses an assumed 11 kW onboard limit,
90% efficiency and a 16-hour cap; DC follows the supplied teaching script's vehicle
mix and taper model. These are synthetic assumptions, not observed station behaviour.

The implementation adapts the supplied COMP5339 `generate_dataset.py`, with AI
assistance acknowledged in the source files. References for the time convention and
MQTT acknowledgement API: [AEMO market time](https://markets-portal-help.docs.public.aemo.com.au/Content/MSATSb2bValidationModule/RulesProcedures.htm),
[Paho Python client](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
