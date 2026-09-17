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
| Task 3: augment records with external charger attributes | OCM + OSM + Charge@Large candidate audit completed: 322 / 433 DC rows (74.36%) |
| Task 3: manual review of address conflicts | Evidence queue generated; 7 address-only candidates remain pending |
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

## Task 3: current matching strategy

Only the following three rules currently produce accepted matches. Fuzzy
address matches are not automatically accepted.

### Rule 1 — exact coordinate match

Coordinates are rounded to six decimal places. If exactly one external record
has the same rounded latitude/longitude, the match is accepted as:

```text
match_method = coordinate_exact
match_confidence = high
```

### Rule 2 — unique structured address match

If no exact coordinate match exists, the implementation extracts a structured
street key and postcode-related keys. A record is accepted only when the
address key identifies one external candidate uniquely.

This is not necessarily a raw whole-string equality. It allows normalised
forms such as `Road`/`Rd` and differences in punctuation or whitespace. The
result is recorded as:

```text
match_method = address_exact_unique
match_confidence = high
```

### Rule 3 — near coordinate with a clear nearest candidate

If no exact coordinate or unique structured-address match exists, the nearest
external coordinate may be accepted only when both conditions hold:

```text
nearest_distance <= 5 metres
second_nearest_distance - nearest_distance >= 20 metres
```

The second condition prevents an arbitrary choice when two external stations
are close to the same source location.

The result is recorded as:

```text
match_method = coordinate_near_clear
match_confidence = medium
manual_review = true
```

The near-coordinate rule is strong spatial evidence, but it does not prove
that the two address strings are correct. Address conflicts are therefore
retained for manual review.

## Previous Peclet baseline

The first local trial used the Peclet snapshot and was run against the 433 DC
records:

| Result | Count |
|---|---:|
| Exact coordinate matches | 49 |
| Unique structured-address matches | 151 |
| Clear near-coordinate matches | 46 |
| Accepted matches in the trial | 246 |
| Review candidates | 187 |
| DC coverage | 246 / 433 = 56.8% |

This is a historical Peclet baseline, not the final OCM result. The final
multi-source Task 3 result is documented in [`TASK3_README.md`](TASK3_README.md)
and stored under `result_data/task3_final_multisource_output/`.

The minimum target for 50% coverage is 217 DC records. The trial therefore
has a buffer of 29 records. After manual review, at least 17 of the 46
near-coordinate candidates need to remain accepted to keep the result at or
above 50%.

For the 246 accepted trial matches, the external fields currently available
are approximately:

| External attribute | Non-empty accepted rows |
|---|---:|
| Station ID/name/address | 246 / 246 |
| Operator | 245 / 246 |
| Plug types | 140 / 246 |
| Number of plugs | 246 / 246 |
| Charger capacity | 246 / 246 |
| Opening hours | 127 / 246 |

The external fields augment the original NSW data. They should not silently
replace the original source values, and the matching evidence should remain
available for auditing.

## Address-conflict manual review

The following fields are generated to support review:

```text
source_row
source_address
external_station_id
external_station_address
source_latitude
source_longitude
external_latitude
external_longitude
augmentation_match_distance_m
augmentation_nearest_distance_m
augmentation_nearest_gap_m
augmentation_match_method
augmentation_review_reason
```

For every `coordinate_near_clear` row, the reviewer should:

1. compare both coordinates on a map;
2. compare street number, street name, suburb, and postcode;
3. check whether one address is a venue/parking entrance and the other is a
   more specific charger address;
4. use station name and operator only as supporting evidence;
5. check whether multiple external records are located at the same site;
6. record a final decision and a short explanation.

Recommended review decisions are:

```text
accepted
accepted_with_note
manual_review
rejected
```

An address conflict alone does not automatically prove a false match. However,
different street names, different house numbers, different suburbs, or
different postcodes should not be accepted without map or other independent
evidence.

The previous Peclet trial output files contain the evidence needed for the
baseline review:

```text
result_data/task3_trial_three_rules.csv
result_data/task3_trial_coordinate_exact.csv
```

The standalone feasibility probe used during development also produced:

```text
task3_probe_output/dc_match_results.csv
task3_probe_output/dc_accepted_augmentation.csv
task3_probe_output/dc_review_candidates.csv
task3_probe_output/task3_probe_report.json
```

These files should not be treated as final submission outputs until the source
choice and manual review decisions are frozen.

## Task 3 output fields

The augmentation stage currently adds external data and matching evidence,
including:

```text
augmentation_match_status
augmentation_match_method
augmentation_match_confidence
augmentation_manual_review
augmentation_reference_row
augmentation_match_distance_m
augmentation_nearest_distance_m
augmentation_nearest_gap_m
external_source
external_data_provider
external_station_id
external_station_name
external_station_address
external_operator
external_plug_types
external_number_of_plugs
external_charger_capacity
external_opening_hours
external_latitude
external_longitude
augmentation_review_reason
```

Rows with `match_status = review` retain their candidate evidence but should
not be used to claim accepted Task 3 coverage until manually reviewed.

## Running the current pipeline

From the repository root, prepare the input folders expected by `config.py`:

```text
src_data/
├── nsw_ev_charging.csv
└── SA4_2026_AUST_SHP_GDA2020.zip
```

Set the OCM key in the same shell used to start the pipeline. The key is not
written to `config.py` or committed:

```bash
export OCM_API_KEY='your-real-api-key'
```

The legacy `main.py` pipeline retrieves the NSW OCM bounding box, makes one
supplemental OCM coordinate query per usable DC source row, and caches the
merged snapshot. The final multi-source Task 3 commands are documented in
[`TASK3_README.md`](TASK3_README.md).

The main pipeline can then be started with:

```bash
python main.py
```

The intended intermediate outputs are:

```text
clean_src_data/nsw_ev_charging.csv
aug_data/nsw_ev_charging.csv
```

The final DuckDB storage stage is not implemented yet. `main.py` currently
stops after reading the augmented data and leaves the database schema and
loading logic as a manual TODO.

## Files relevant to the current implementation

| File | Purpose |
|---|---|
| `config.py` | file paths, cleaning functions, matching rules, augmentation columns |
| `main.py` | cleaning, augmentation, and current pipeline orchestration |
| `data_utils/data_cleaner.py` | file/DataFrame cleaning framework |
| `data_utils/column_cleaner.py` | column-level transformations |
| `data_utils/address_enricher.py` | separate OSM address-enrichment experiment |
| `process_and_enrich_all.py` | previous address enrichment workflow |
| `result_data/task3_trial_three_rules.csv` | previous Peclet three-rule trial output |
| `DAG_PIPELINE_SUMMARY.md` | existing DAG framework notes |
| `MATCHING_SUMMARY.txt` | earlier address-matching feasibility notes |

The OSM address-enrichment code is separate from the current OCM matching
logic. It reverse-geocodes/enriches addresses and should not be described as
the Task 3 external charger-attribute API.

## Remaining TODOs before submission

Task 3's automatic candidate audit and saved evidence are complete. Remaining
Task 3 work is to record final reviewer decisions for the seven address-only
rows, confirm provider attribution/licence text, and include the final coverage
table in the assignment report. Task 4 DuckDB storage and validation queries
remain outside this Task 3 branch work.

No external data should be silently mixed between Peclet and OCM. If the
source changes, the matching process and the coverage statistics must be
rerun and the report must identify the new source.
