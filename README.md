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
```

Database files are set in config.py too:

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
To generate, publish, store and show events in one run, use `python main_ass_2.py`;
see the [unified entry point](docs/part_c_unified_entrypoint.md). The
[full validation summary](docs/ass2_full_validation.json) records offline results, and a
[real-broker check](docs/ass2_mqtt_validation.json) of an earlier two-station sample
passed with 4,191 published and received events. Full dataset publication remains pending.

The main generator files are in `transaction_scripts/data_generation_and_publishing/`
and follow Yeh's layout:

- `data_generator_config.py`: dates, paths, seed and simulation settings.
- `data_generator_utils.py`: station adaptation, AEMO prices, CSV generation and ordered events.
- `data_generator_daemon.py`: reads stations through `EVChargerInfoDAO`, runs generation,
  and optionally publishes events using Paho MQTT.

MQTT defaults come from `config.py` through `repository.repo_config.mqtt_config()`;
CLI options override them. The configuration keys match Yeh's helpers, while the
shared topic root remains `evc`. Shared DuckDB settings allow writes and include
`spatial` for those helpers; A's station repository stays read-only by default.

The supplied `generate_dataset.py` is kept separately in the same directory. The wrapper
calls its price loader, tariff, arrival sampler and session simulator instead of
maintaining a second implementation in `utils`. The supplied copy has documented
project adaptations for complete observed prices, macOS CA certificates, AC charging,
power caps and the final meter reading. Use the daemon above as the project entry point.

Run these commands from the repository root. The generator needs `duckdb`; publishing
also needs `paho-mqtt==2.1.0`, now listed in `requirements.txt`.
Pass the path to your existing Ass1 database with `--db`. The new default is
`data/db/nsw_evc.db`; an older `.duckdb` file is also supported and is not renamed.

```bash
# Small offline run for integration; replace --db with your snapshot's actual location.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db data/db/.duckdb --out data/ass2_small \
  --start 2026-09-15 --days 14 --limit 2 --meter-every 5

# Full offline run, kept separate from the small one.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db data/db/.duckdb --out data/ass2_generated \
  --start 2026-09-15 --days 14 --meter-every 5

# Start a subscriber first, e.g. `python -m view.dashboard_daemon`, then publish the small run.
# Replace localhost with the broker's reachable IP if it runs on another computer.
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_small --replay --publish --host localhost --port 1883

python -m unittest discover -s tests -v
```

Omit `--limit` to include all Ass1 stations. Defaults are 14 days and one meter reading
per minute. `--meter-every 5` reduces the number of meter events; every session retains
its last reading. Publication waits at least 0.1 seconds after each broker acknowledgement,
so millions of events can take several days to publish. The default command only
generates files. To publish the full dataset, use `--out data/ass2_generated` with
`--replay --publish`; the small run only verifies integration.

Outputs are `stations.csv`, `prices_hourly.csv`, `sessions.csv`, `session_metering.csv`
and `manifest.json`, plus an `aemo_cache` directory. The manifest records the run ID,
seed, period, source and counts. Replaying these files retains event IDs for subscriber
deduplication. Topics are `evc/<event_type>/<charger_id>`; payloads are JSON objects
matching `EVChargerStateEvent`. B can decode with `from_json()`, store/deduplicate the
event, and then call `EVChargerState.apply()`. B should subscribe to `evc/#` with QoS 2
(`MQTT_QOS` in `config.py`) and compare unique event `id` counts for the same `run_id`,
since replays resend the same event IDs. A message's `object_id` is the Ass1 `charger_id` as text;
`EVChargerStateEvent.charger_id` returns it as an integer.

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

## Compact dashboard dataset and replay

The optional coverage-controlled mode is documented in
[`docs/ass2_dashboard_dataset_v2.md`](docs/ass2_dashboard_dataset_v2.md). It supports
DC-only filtering, exact target session counts, Sydney focus-region coverage, stable
JSON export, and time-window replay with only the required preceding state context.
It preserves the existing Poisson-style generator when `--target-sessions` is omitted.

Use a new ignored output directory when generating data. The three-day dataset and
MQTT validation artifacts referenced by the documentation are not committed here:
their presence must be verified separately.
