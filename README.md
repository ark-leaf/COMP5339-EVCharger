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
ASS2_GENERATED_DATA_FILE_LOCATION = DATA_ROOT / "ass2_registered_3day"
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

The current A workflow uses only operational stations present in both Ass1
`charger` and `charger_connector`, with a matching `charger_location` and a positive
`charger_characteristic.number_of_plugs`. General DAO reads remain available for B.
Unknown/Upcoming stations and unknown/zero port counts are excluded, not invented.
See the [current A-to-B handoff](docs/ass2_a_to_b_handoff.md) for files, IDs and evidence.

The registered-station dataset lives in `data/ass2_registered_3day/`: 282 DC stations,
1,170 simulated ports, 20,304 hourly prices and exactly 4,000 sessions across
14–16 September 2026 (AEST). Real AEMO NSW1 observations are averaged hourly. The
original Ass1 IDs, coordinates, power ratings and port counts are preserved.
The former 433-station dataset is archived and is not the current handoff.

### Generate and validate

Run from the repository root with DuckDB and Paho MQTT installed. Use the same Ass1
snapshot as B. The output directory must not contain an existing dataset manifest;
choose a fresh directory to generate another run. The commands below do not publish.

```bash
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --db /path/to/shared-ass1.duckdb --out data/ass2_registered_3day \
  --start 2026-09-14 --days 3 --seed 5339 --charger-type DC \
  --target-sessions 4000 --focus-region Sydney --meter-every 2 --export-events

python -m scripts.check_generator_coverage \
  --data-dir data/ass2_registered_3day --db /path/to/shared-ass1.duckdb
```

`stations_input.csv` is the teacher's seven-column input (`station_id,name,lat,lon,
site_type,connectors,max_kw`). `stations.csv` retains project metadata and explicit
simulation assumptions. Prices, sessions and meters are in `prices_hourly.csv`,
`sessions.csv` and `session_metering.csv`. The validation writes
`station_source_audit.csv` (original connector-type keys) and
`connector_coverage.csv` (all simulated physical ports and daily activity).

`--target-sessions` enables a documented allocation: 144 Sydney focus stations /
513 ports have 1–3 sessions per port per day; each other port has one session over
three days. Daily counts are 1,358 / 1,334 / 1,308. The simulator retains the supplied
charging physics, price sensitivity and final meter sample. This allocation is a
synthetic coverage assumption, not observed utilisation. Omitting `--target-sessions`
uses the existing random arrival mode for small smoke runs. Default dates span three
days, default type is DC and default meters are every two minutes; the target of
4,000 must be supplied explicitly for the formal profile.

### Prepare a replay window

```bash
python -m transaction_scripts.data_generation_and_publishing.data_generator_daemon \
  --out data/ass2_registered_3day --replay --export-events \
  --window-start 2026-09-15T09:00 --window-end 2026-09-15T11:00 \
  --events-out data/ass2_registered_3day/window_09_11
```

The full prepared list has 76,136 events; it is not an actual-publication record.
Only initial and changed retail prices become price events. A replay window retains
original prior prices and the starts/latest meters needed to recover ongoing sessions.
Source timestamps use AEST; event JSON timestamps use UTC. Each run's event IDs remain
stable on replay. A manifest stores the selected station/port scope. All staged event
IDs and port ranges are checked before the first event is yielded. Old manifests
without this scope are rejected: regenerate from the database, do not add a scope
marker to the old files manually. The old datasets themselves remain untouched.

### Publish and verify B's storage

Start the [broker](mqtt/README.md), then B's subscriber, and wait for its subscription
acknowledgement. To publish the same window, add `--publish --host HOST --port PORT`
to the window command. QoS is 1 and the default inter-event delay is now 1 second.
The CLI can override it with `--interval`; the assignment minimum remains 0.1 seconds.
The 4,058-event replay therefore takes at least about 68 minutes at the new default.
The recorded full-window MQTT validation used the former 0.1-second setting.
`published_events.json` records broker-acknowledged events; B's stored IDs must still
be compared with that file. Do not run two subscribers writing the same DuckDB file.

For an isolated local test using Yeh's existing subscriber and a new database copy:

```bash
python -m scripts.check_mqtt_storage \
  --data-dir data/ass2_registered_3day --db /path/to/shared-ass1.duckdb \
  --out data/ass2_registered_3day/mqtt_09_11 --window-start 2026-09-15T09:00 \
  --hours 2 --host 127.0.0.1 --port 18885
```

This check needs an already running broker, owns its test subscriber, copies the
source database, restarts the subscriber halfway through and checks duplicates,
payloads, IDs and current states. Its `--out` must be new. It does not involve the
dashboard. The submission package uses the actual replay's prepared, published and
duplicate-check JSON files, together with the generated/input CSVs and subscriber DB.

### Shared IDs and implementation

- CSV `charger_id` = input `station_id` = MQTT `object_id` (text) = Ass1 station ID.
- MQTT `connector_id` = B's `connector_no`, a local port number within that station.
- `(charger_id, connector_no)` identifies a simulated physical port.
- Ass1 `charger_connector_id` identifies a connector-type row, not a physical port.
  Those original keys are preserved in `station_source_audit.csv`; they are not
  substituted into message port numbers. No B schema or entity change is required.

| File | Responsibility |
|---|---|
| `repository/evc_info_dao.py` | Read eligible stations using both source tables; keep general reads separate. |
| `data_generator_config.py` | Dates, paths, profile parameters and scope version. |
| `data_generator_schedule.py` | Exact session budget and bounded daily port coverage. |
| `data_generator_utils.py` | Adapt station data, call supplied physics, write CSVs and validate/convert events. |
| `data_generator_replay.py` | Select a window while retaining necessary original context events. |
| `data_generator_daemon.py` | Coordinate read, generation, export and optional MQTT publishing. |
| `scripts/check_generator_coverage.py` | Verify original IDs, counts, source prices, ports, timing and complete events. |
| `scripts/check_mqtt_storage.py` | Verify real MQTT delivery and Yeh's storage using a copied database. |

Generator modules are under `transaction_scripts/data_generation_and_publishing/`.
The supplied `generate_dataset.py` remains the physics/wholesale helper; invoke the
project daemon for the eligibility rules above. Missing names use operator/address;
missing power retains an explicitly documented default, but missing ports do not.

```bash
PYTHONPATH=tests python -m unittest test_data_generator test_dashboard_dataset \
  test_entities test_generator_publisher.PublisherTests test_station_repository -v
```

The data directories are Git-ignored and must be shared separately. Earlier
[one-day](docs/ass2_mqtt_storage_validation.json) and [433-station three-day](docs/ass2_dashboard_dataset_v2.md)
results describe archived inputs. The bundled `examples/ass2_mqtt` is also historical;
its AC station 1 and unscoped manifest are not valid current replay input.
OpenAI Codex assisted with the implementation, tests and documentation. Retain the
source acknowledgements and submit the course AI usage form with the report.
