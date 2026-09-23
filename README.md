# COMP5339 EV Charger — Current Data Processing Workflow

This README documents the current implementation status of Assignment 1. It
describes the workflow that is currently implemented and tested locally. The
final multi-source Task 3 workflow and its audit outputs are documented in
[`TASK3_README.md`](TASK3_README.md). The sections below retain the original
pipeline notes and historical OCM/Peclet trials for reference.

## Current status

| Component | Status |
|---|---|
| Task 1: load the NSW EV charging data | Implemented in the existing pipeline |
| Task 2: clean and transform the source data | Implemented and previously tested on 1,958 records |
| Task 3: augment records with external charger attributes | OCM + OSM + Charge@Large: 239 / 433 accepted enrichments (55.20%); 322 candidates in total |
| Task 3: identity and attribute review | 83 unaccepted candidates; 69 accepted rows with separate quality flags |
| Task 4: final relational schema and DuckDB storage | TODO |

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
Task 4: transform and load into DuckDB  [TODO]
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

The source URL is configured in `nsw_evc_cleaning_config.py` as
`NSW_EV_CHARGING_SRC_FILE_URL`.

### 2. ABS SA4 boundary data

The existing Task 2 pipeline can use the ABS SA4 shapefile to attach SA4
information through a spatial join. The expected file location is configured
by `AUS_ASGS_LV4_FILE` in `nsw_evc_cleaning_config.py`.

This is part of the cleaning/integration stage. It is not the source used for
Task 3 charger-attribute augmentation.

### 3. Open Charge Map external data and historical baseline

The final pipeline reads the checked-in tiled OCM, OSM-derived mirror and
Charge@Large snapshots without network calls. The two-pass retrieval described
below belongs to the retained OCM-only baseline, not the final Task 3 command.
See `TASK3_README.md` for the active snapshots and refresh commands.

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

On the first explicit OCM-only baseline run, the legacy interface
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

The cleaning logic is in `nsw_evc_data_cleaning.py`, configured by
`nsw_evc_cleaning_config.py`, and executed through the existing `DataCleaner`
framework. `config.py` retains compatibility imports for older scripts.

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

From the repository root, prepare the Task 2 input files:

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

For the reproducible checked-in-snapshot workflow, `main.py` runs Task 2 and
then Task 3. If Task 2 is already complete, use `python main-augmentation.py`
(equivalent to `python main.py --stage augment`). Task 3 regenerates matching
and audit from the cleaned input, validates the result and exports the final
CSV. There is no automatic OCM-only fallback. Custom input/output paths and
the stage interfaces are documented in [`TASK3_README.md`](TASK3_README.md).

The main pipeline can then be started with:

```bash
python main.py
```

The intended intermediate outputs are:

```text
clean_src_data/nsw_ev_charging.csv
aug_data/nsw_ev_charging.csv
```

The final DuckDB storage stage is not implemented on this branch. `main.py`
stops after validating and exporting the augmented data, leaving the schema and
loading logic as a manual TODO.

## Files relevant to the current implementation

| File | Purpose |
|---|---|
| `config.py` | compatibility imports for older scripts |
| `nsw_evc_cleaning_config.py` / `nsw_evc_data_cleaning.py` | Task 2 configuration / processors |
| `data_augmentation_config.py` | Task 3 configuration and reserved augmentation interfaces |
| `task3_pipeline.py` / `main-augmentation.py` | standalone Task 3 pipeline / command |
| `main.py` | cleaning, augmentation, and current pipeline orchestration |
| `data_utils/data_cleaner.py` | file/DataFrame cleaning framework |
| `data_utils/column_cleaner.py` | column-level transformations |
| `data_utils/address_enricher.py` | separate OSM address-enrichment experiment |
| `process_and_enrich_all.py` | previous address enrichment workflow |
| `data_utils/multisource_matching.py` | final OCM/OSM/Charge@Large matching |
| `data_utils/multisource_audit.py` | acceptance, review separation, integrity checks and manifests |
| `data_utils/multisource_augmentation.py` | accepted fields through ColumnCleaner |
| `task3_multisource_supplement_trial.py` / `task3_final_multisource_audit.py` | compatibility commands for matching / audit |
| `TASK3_README.md` | Task 3 result, methodology, coverage, provenance, and limitations |
| `result_data/task3_final_multisource_output/` | final Task 3 audit, queues, summary, and source manifest |
| `DAG_PIPELINE_SUMMARY.md` | existing DAG framework notes |
| `MATCHING_SUMMARY.txt` | earlier address-matching feasibility notes |

The OSM address-enrichment code is separate from the current OCM matching
logic. It reverse-geocodes/enriches addresses and should not be described as
the Task 3 external charger-attribute API.

## Remaining TODOs before submission

Task 3 meets the stated enrichment threshold with the 239 accepted rows.
Further manual review of the 83 candidate-only rows and 69 accepted quality
flags can improve validation; these candidates are not needed to reach 50%.
Include the final coverage and source-attribution notes in the assignment
report. Task 4 DuckDB storage and validation queries remain outside this
Task 3 branch work.

No external data should be silently mixed between Peclet and OCM. If the
source changes, the matching process and the coverage statistics must be
rerun and the report must identify the new source.
