# COMP5339 EV Charger — Current Data Processing Workflow

This README documents the current implementation status of Assignment 1. It
describes the workflow that is currently implemented and tested locally. The
final multi-source Task 3 workflow and its audit outputs are documented in
[`TASK3_README.md`](TASK3_README.md). The completed Task 4 DuckDB implementation
is documented in [`TASK4_README.md`](TASK4_README.md). The sections below retain
the original pipeline notes and historical OCM/Peclet trials for reference.

## Current status

| Component | Status |
|---|---|
| Task 1: load the NSW EV charging data | Implemented in the existing pipeline |
| Task 2: clean and transform the source data | Implemented and previously tested on 1,958 records |
| Task 3: augment records with external charger attributes | OCM + OSM + Charge@Large candidate audit completed: 322 / 433 DC rows (74.36%) |
| Task 3: manual review of address conflicts | Evidence queue generated; 7 address-only candidates remain pending |
| Task 4: final relational schema and DuckDB storage | Completed: reproducible six-table DuckDB with relational and spatial validation |

The current branch contains the compatible OCM adapter, the multi-source
matching scripts and the final row-level audit outputs. The Task 3 audit does
not modify the raw input file.

## End-to-end workflow

```text
NSW Transport EV charging CSV
        |
        v
Task 2: clean and standardise columns
        |
        v
clean_src_data/nsw_ev_charging.csv
        |
        v
Task 3: match each source row to the local external charger snapshot
        |
        +--> accepted matches with external attributes
        |
        +--> review candidates with evidence and review reason
        |
        v
aug_data/nsw_ev_charging.csv
        |
        v
Task 4: transform, load, and validate data/processed/task4.duckdb
```

## Input data

### 1. NSW Transport source data

The main source is the NSW Transport Open Data EV charging locations file.
The expected project layout is:

```text
src_data/
└── nsw_ev_charging.csv
```

The source dataset used in the current trial contains 1,958 records. The
Task 3 target population is the 433 records whose `Charger_Type` is `DC`.

The source URL is configured in `config.py` as
`NSW_EV_CHARGING_SRC_FILE_URL`.

### 2. ABS SA4 boundary data

The existing Task 2 pipeline can use the ABS SA4 shapefile to attach SA4
information through a spatial join. The expected file location is configured
by `AUS_ASGS_LV4_FILE` in `config.py`.

This is part of the cleaning/integration stage. It is not the source used for
Task 3 charger-attribute augmentation.

### 3. Open Charge Map external data

The current Task 3 implementation uses the Open Charge Map POI API. The
endpoint is configured as:

```text
https://api.openchargemap.io/v3/poi/
```

The API key is read from the local shell environment and is never stored in
the repository:

```bash
export OCM_API_KEY='your-real-api-key'
```

On the first Task 3 run, the program keeps the existing Task 3 interface and
uses two OCM retrieval passes for source rows whose `Charger_Type` is `DC`:

1. retrieve the complete NSW bounding-box OCM snapshot;
2. query OCM around each source coordinate as a supplemental pass.

The OCM records from both passes are merged by OCM station ID. The existing
matcher then compares the source address with OCM `AddressInfo` locally, so no
separate address service is required. The merged data is saved to the existing
local cache:

```text
result_data/ocm_ev_charging_snapshot.json
result_data/ocm_ev_charging_snapshot_metadata.json
```

Later runs reuse the two-pass snapshot by default. If the existing snapshot
was created by an earlier per-record-only trial, the loader refreshes it once
so that the cache scope matches the current implementation. Set
`OCM_REFRESH_SNAPSHOT=1` when a new API snapshot is required. The metadata file
records the NSW bounding box, full-snapshot count, coordinate-query count, UTC
retrieval time, endpoint, and record count; it never records the API key.

The response is normalised into station ID, name, address, coordinates,
operator, connector types, number of plugs, and power fields before the three
matching rules are applied. OCM opening hours are left blank because that
field is not consistently available in the POI response.

The earlier Peclet JSON snapshot remains useful as a comparison baseline, but
it is no longer the active external source in `get_ocm_details()`.

## Task 2: cleaning and integration

The cleaning logic is mainly defined in `config.py` and executed through the
existing `DataCleaner` framework.

The current transformations include:

- normalising address whitespace and line breaks;
- removing trailing `Australia` text from addresses;
- extracting state and four-digit postcode values;
- standardising street-type abbreviations such as `Rd`, `St`, `Ave`, and
  `Hwy`;
- normalising charger ratings such as `22` to `22 kW`;
- converting malformed postcode values such as `NSW 2500` to `2500`;
- standardising known operator-name variants;
- integrating ABS SA4 information through a spatial join when the boundary
  file is available.

The `DataCleaner` returns a lazy generator when processing a file. `main.py`
now consumes that generator explicitly so that the cleaned output file is
actually written.

## Task 3: final multi-source enrichment

The final Task 3 implementation enriches the cleaned TfNSW DC subset from Open
Charge Map, an OpenStreetMap-derived public API snapshot, and Charge@Large. It
reuses the existing `DataCleaner` / `ColumnCleaner` pipeline and does not
overwrite TfNSW source fields.

The current reproducible result is **239/433 DC rows (55.20%)** with at least
one new external attribute. The assignment minimum is 217 rows. OCM and OSM
alone cover 218 rows; Charge@Large raises the union to 239.

Candidate discovery allows a locally calculated distance up to 500 m or a
structured fuzzy-address score of at least 0.85. Automatic acceptance is more
conservative: distance must be at most 100 m, postcode safeguards must pass,
the nearest candidate must not be ambiguous within 20 m, and an address-favoured
candidate must not be materially farther than the nearest coordinate candidate.
Review-only attributes are never exported into the augmented table.

The final audit separates three concepts:

- 239 accepted identities used for enrichment;
- 83 unaccepted candidates in the identity-review queue;
- 69 accepted rows in a separate quality-flags file because another source has
  an alternative candidate or accepted sources disagree on plug count/power.

Conflicting scalar values remain blank, while source-specific values and
provenance remain in JSON. The final table also exposes connector types,
operator, plug count, power, capacity, status, access/cost/opening-hour fields,
matching evidence, identity-review flags, and accepted-row quality flags.

The full methodology, field coverage, source attribution, reproduction steps,
limitations, and output inventory are in [`TASK3_README.md`](TASK3_README.md).

## Running the current pipeline

From the repository root, prepare the input folders expected by `config.py`:

```text
src_data/
├── nsw_ev_charging.csv
└── SA4_2026_AUST_SHP_GDA2020.zip
```

An OCM key is needed only when refreshing the OCM snapshot. The key is not
written to `config.py` or committed:

```bash
export OCM_API_KEY='your-real-api-key'
```

For the reproducible checked-in-snapshot workflow, first regenerate the
multi-source matches and audit, then run `main.py`. The exact commands are
documented in [`TASK3_README.md`](TASK3_README.md). `main.py` uses the final
multi-source audit when present and retains the old OCM-only path only as a
compatibility fallback.

The main pipeline can then be started with:

```bash
python main.py
```

The intended intermediate outputs are:

```text
clean_src_data/nsw_ev_charging.csv
aug_data/nsw_ev_charging.csv
```

The final DuckDB storage stage is implemented separately from `main.py`. Run
`scripts/task4_load_duckdb.py` to rebuild and validate
`data/processed/task4.duckdb`; see [`TASK4_README.md`](TASK4_README.md).

## Files relevant to the current implementation

| File | Purpose |
|---|---|
| `config.py` | file paths, cleaning functions, matching rules, augmentation columns |
| `main.py` | cleaning, augmentation, and current pipeline orchestration |
| `data_utils/data_cleaner.py` | file/DataFrame cleaning framework |
| `data_utils/column_cleaner.py` | column-level transformations |
| `data_utils/address_enricher.py` | separate OSM address-enrichment experiment |
| `process_and_enrich_all.py` | previous address enrichment workflow |
| `task3_multisource_supplement_trial.py` | final OCM/OSM/Charge@Large matching and local-snapshot workflow |
| `task3_final_multisource_audit.py` | final acceptance, review separation, integrity checks, and source manifest |
| `TASK3_README.md` | Task 3 result, methodology, coverage, provenance, and limitations |
| `result_data/task3_final_multisource_output/` | final Task 3 audit, queues, summary, and source manifest |
| `TASK4_README.md` | Task 4 schema, build process, outputs, validation, and known data conditions |
| `scripts/task4_load_duckdb.py` | Task 4 DuckDB clean-rebuild entry point |
| `scripts/task4_loaders.py` | Task 4 table loading functions |
| `scripts/task4_validation.py` | Task 4 staged, relational, integration, and spatial validation functions |
| `data/processed/task4.duckdb` | final Task 4 database deliverable |
| `DAG_PIPELINE_SUMMARY.md` | existing DAG framework notes |
| `MATCHING_SUMMARY.txt` | earlier address-matching feasibility notes |

The OSM address-enrichment code is separate from the current OCM matching
logic. It reverse-geocodes/enriches addresses and should not be described as
the Task 3 external charger-attribute API.

## Remaining TODOs before submission

Task 3's automatic candidate audit and saved evidence are complete. Remaining
Task 3 work is to record final reviewer decisions for the seven address-only
rows, confirm provider attribution/licence text, and include the final coverage
table in the assignment report. Task 4 DuckDB storage and validation are
complete; its remaining work is documentation in the assignment report.

No external data should be silently mixed between Peclet and OCM. If the
source changes, the matching process and the coverage statistics must be
rerun and the report must identify the new source.
