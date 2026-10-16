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

All configuration is centralized in config.py. Key settings:

```
PROJECT_ROOT = Path(__file__).parent.resolve()
DATA_ROOT = PROJECT_ROOT / "data"
SRC_DATA_FILE_LOCATION = DATA_ROOT / "src_data"
CLEAN_SRC_DATA_FILE_LOCATION = DATA_ROOT / "clean_src_data"
AUG_DATA_FILE_LOCATION = DATA_ROOT / "aug_data"
RESULT_DATA_FILE_LOCATION = DATA_ROOT / "result_data"
DB_SCHEMA = PROJECT_ROOT / "db" / "schema" / "nsw_evc_schema.sql"
DB_DATA = DATA_ROOT / "db" / ".duckdb"
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

3. **data/db/.duckdb** (~30MB)
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
