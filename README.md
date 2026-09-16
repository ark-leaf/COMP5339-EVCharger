# COMP5339 EV Charger — Current Data Processing Workflow

This README documents the current implementation status of Assignment 1. It
describes the workflow that is currently implemented and tested locally. The
Task 3 external-source matching is still experimental and must be reviewed
before it is treated as the final submission solution.

## Current status

| Component | Status |
|---|---|
| Task 1: load the NSW EV charging data | Implemented in the existing pipeline |
| Task 2: clean and transform the source data | Implemented and previously tested on 1,958 records |
| Task 3: augment records with external charger attributes | First local trial implemented |
| Task 3: manual review of address conflicts | Required; not completed yet |
| Task 4: final relational schema and DuckDB storage | TODO |

The current branch contains a first Task 3 trial. It does not push data to an
external service and does not modify the raw input files.

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

### 3. Peclet local charger snapshot

The current Task 3 trial uses a local JSON snapshot containing approximately
2,038 charger records. The snapshot provides fields such as:

```text
ev_station_id
station_name
station_address
operator
number_of_plugs
charger_capacities
opening_hours
latitude
longitude
tesla
type_2
j_1772
```

The current local configuration points to this snapshot through
`PECLET_REFERENCE_FILE`.

The downloaded team preprocessing document identifies the source as the
Peclet EV charging stations dataset and gives the following API endpoint:

<https://data.peclet.com.au/explore/dataset/ev-charging-stations/api/?disjunctive.lganame&disjunctive.suburb_2&location=11,-33.13525,151.2093&basemap=jawg.streets>

The local files `ev-charging-stations.json` and `ev-charging-stations.csv`
are the saved snapshot used by the current trial. The download archive records
the files as modified on 12 September 2026. This timestamp is useful for
reproducibility, but it should not be treated as a confirmed API retrieval
timestamp unless the team verifies it.

Current provenance record:

| Item | Current value |
|---|---|
| Provider | Peclet Technology Pty Ltd / Peclet Data Portal |
| Dataset | EV Charging Stations |
| Dataset identifier | `ev-charging-stations` |
| Source/API page | [Peclet EV Charging Stations](https://data.peclet.com.au/explore/dataset/ev-charging-stations/api/) |
| Local snapshot | `ev-charging-stations.json` and `ev-charging-stations.csv` |
| Snapshot record count | 2,038 JSON records |
| Archive file timestamp | 12 September 2026; not yet verified as API retrieval time |
| JSON SHA-256 | `c968f56f3aee080cc0c3393a13200cfbeb4ad286cbc25ad839f602df9d18e5bd` |
| CSV SHA-256 | `cef52476c7a3a4b5cc212c72365c840147fca30c6a11010847f4c503582e7142` |
| Dataset licence | Not identified in the downloaded notes or the dataset page |

The dataset-specific licence is still unresolved. The general Peclet website
terms say that website materials are subject to copyright and may be used for
non-commercial or personal purposes unless otherwise indicated or permission
has been obtained. This is not the same as a confirmed licence for the EV
Charging Stations dataset. The team should therefore check the dataset's
licence metadata or contact Peclet before claiming that the snapshot is an
openly licensed dataset.

Important: this trial uses Peclet data, not a live Open Charge Map request.
`OCM_ENDPOINT` and `OCM_API_KEY` are currently empty. The function name
`get_ocm_details()` is therefore misleading and should eventually be renamed
to something such as `get_peclet_reference_details()`, or replaced by the
team's final external-source implementation.

The source is now documented in the team preprocessing notes. Before
submission, the team still needs to verify the actual retrieval date and
dataset-specific licence/attribution. If Peclet cannot confirm suitable reuse
rights, the Task 3 implementation should be changed to Open Charge Map and
rerun from the beginning.

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

## Current Task 3 trial result

The current trial was run against the 433 DC records:

| Result | Count |
|---|---:|
| Exact coordinate matches | 49 |
| Unique structured-address matches | 151 |
| Clear near-coordinate matches | 46 |
| Accepted matches in the trial | 246 |
| Review candidates | 187 |
| DC coverage | 246 / 433 = 56.8% |

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

The current output files contain the evidence needed for this review:

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

Then update `PECLET_REFERENCE_FILE` in `config.py` to a path that exists on
the current machine. The present value is an absolute path used for local
experimentation and is not portable between team members.

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
| `result_data/task3_trial_three_rules.csv` | current three-rule trial output |
| `DAG_PIPELINE_SUMMARY.md` | existing DAG framework notes |
| `MATCHING_SUMMARY.txt` | earlier address-matching feasibility notes |

The OSM address-enrichment code is separate from the current Peclet matching
logic. It reverse-geocodes/enriches addresses and should not be described as
the Task 3 external charger-attribute API unless the team explicitly chooses
to use it for that purpose.

## Remaining TODOs before submission

1. Verify the Peclet retrieval date and dataset-specific licence/attribution;
   the current snapshot checksums are recorded above.
2. Rename or replace `get_ocm_details()` so the code matches the actual source.
3. Manually review the 46 near-coordinate/address-conflict candidates.
4. Add review decision, reviewer, date, and notes to the audit output.
5. Recalculate final accepted coverage after manual review.
6. Freeze the augmentation schema and external-source policy.
7. Design the relational schema and load the final augmented data into DuckDB.
8. Add final validation queries and document the Task 4 results.

No external data should be silently mixed between Peclet and OCM. If the
source changes, the matching process and the coverage statistics must be
rerun and the report must identify the new source.
