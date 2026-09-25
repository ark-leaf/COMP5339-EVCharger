# NSW EV Charging Station Data Processing Pipeline

The team pipeline cleans and integrates TfNSW/ABS data (Tasks 1–2), augments DC locations (Task 3), and loads the results into DuckDB (Task 4).

This version integrates `ark-yeh` commit `874eb5b` and the student's revised Task 3 implementation. It runs the four tasks through one `main.py` pipeline. The bundled external API snapshots were retrieved on 24 September 2026.

## Install and run

Python 3.12.4 was tested with the pinned dependencies in `requirements.txt`, including the team's pandas 3.0.5 and NumPy 2.5.3.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py --stage all
```

Windows activation: `.venv\Scripts\activate`.

Available stages:

```bash
python main.py --stage clean
python main.py --stage augment
python main.py --stage load
python main.py --stage all
```

The default is `all`. The load stage rebuilds the project's DuckDB tables inside a transaction; a loading or validation error rolls back the rebuild. The DuckDB spatial extension must be available; its first installation requires internet access. Augmentation uses saved snapshots and requires no API key or network connection.

The bundled source files make cleaning replayable offline. If either source is absent, the clean stage downloads it from the configured official TfNSW/ABS URL. Downloads use a timeout and a validated temporary file so an interrupted request cannot replace a good cache. Missing or corrupt required sources cause an error rather than a silently incomplete result.

## Team structure

```text
main.py
config.py
data_utils/                       shared ColumnCleaner and DataCleaner
pipeline/
  data_clean_script.py            nsw_evc_cleaning()
  data_clean/                     teammate Task 1/2 logic
  data_aug_script.py              nsw_evc_augmentation()
  data_aug/                       Task 3 config, matching, audit and export
  data_load_script.py             nsw_evc_load()
  data_load/                      teammate database loading and validation
data/
  src_data/                       TfNSW CSV and ABS boundary ZIP
  clean_src_data/                  Task 2 output
  reference/                      API snapshots and historical web notes
  aug_data/                       Task 3 output
  result_data/                    audit tables, manifests and geocoding cache
  db/                             generated DuckDB database
```

Shared paths remain in `config.py`. Task 3 settings live in `pipeline/data_aug/nsw_evc_aug_config.py`; database settings live in `pipeline/data_load/nsw_evc_load_config.py`. The two reserved `GET_NSW_EV_COLUMN_AUGMENTATION_*` functions use the same audited implementation.

The Task 3 stage calls the team's reserved `ColumnCleaner` and `DataCleaner` interfaces. The submitted pipeline retains its runtime checks for input integrity, matching coverage, field preservation and database consistency.

Unused augmentation placeholders were removed from the cleaning configuration. Experimental root-level scripts are not part of the submission ZIP; local copies were preserved. Use the stage commands above or `python -m pipeline.data_aug_script --help`.

## Task 2 replay and Task 3 handoff

The latest teammate cleaning stage was rerun against the bundled TfNSW data and the saved reverse-geocoding responses. It produces 1,958 rows and 54 columns, including 433 DC rows. Under the original validation environment its CSV is byte-identical to the previous Task 2 snapshot. Task 3 preserves all source columns, values and row order and appends 19 columns.

Task 2 uses the saved `data/result_data/task2_nominatim_cache.json` by default. If new inputs need reverse geocoding, explicitly set `ADDRESS_ENRICHER_ALLOW_NETWORK=1`; successful requests are rate-limited and cached. Task 3 does not rerun or modify Task 2.

## Task 3: sources, matching and assumptions

The augmentation stage reads the saved OCM, OSM-derived Opendatasoft and Charge@Large responses from `data/reference/task3_live_20260924/`. The three independent collection scripts (`task3_ocm_tiled_snapshot.py`, `task3_osm_snapshot.py` and `task3_chargelarge_snapshot.py`) document and implement API retrieval; the normal pipeline uses the saved responses so it does not require an API key. OCM uses tiled requests with the key in the `X-API-Key` header. The OSM-derived records came from a paginated Opendatasoft mirror, not from Overpass. Charge@Large exposes nested device and port data; its saved query covered 0–350 kW and participating operators only. Raw responses, query metadata, timestamps and hashes are included.

Only TfNSW DC rows and external sites with CCS or CHAdeMO evidence are considered. OCM sites explicitly marked non-operational are excluded. Distances are calculated locally in **metres**. The strict rule accepts a candidate within 100 m, or within 500 m when a fuzzy-matched numbered street address corroborates it. Street abbreviations, house numbers and postcodes are normalized for comparison. Explicit postcode or house-number conflicts, similarly close alternatives and incompatible reuse of an external site ID require review. Address-only matches beyond 500 m remain review-only.

An additional documented rule applies to strict-review rows with a historical web note labelled high or medium, a supporting URL, and a current DC candidate within 500 m that supplies a new attribute. The note is tied to the current source address; an OCM note must also have the same OCM ID. The nearest eligible candidate is selected. A note can concern a different provider from that candidate, and an opened webpage is not required. Existing address conflicts and shared-ID concerns remain quality warnings. This rule does **not** independently verify that both records describe the same physical station.

The cleaned input has **433 DC rows**. The strict rule accepts **224/433 (51.73%)**; the historical-web rule adds **58**, giving **282/433 (65.13%)** policy-accepted rows, with 37 review-only and 114 unmatched. All 282 accepted rows gain normalized connector types absent from TfNSW; the assignment's 50% threshold is 217 rows. These percentages measure policy coverage, not matching accuracy. Of the accepted rows, 164 retain quality warnings, including the additional 58; 35 external-ID groups are shared by multiple source rows. The 125 OCM and 104 supplemental historical search notes are preserved in `data/reference/web_review/`.

Task 3 appends 19 columns without changing the 54 Task 2 columns or AC rows. Among accepted DC rows, 177 have an external maximum power value, 176 a minimum, 34 an explicit DC port count, 121 usage-cost text and 32 opening-hours text. Power is expressed in kW, but its original scope remains in `external_attributes_json`: OCM and Charge@Large provide DC connection/port ratings, while OSM reports a site maximum. OCM `NumberOfPoints` and OSM charge-point counts are **not** treated as physical plugs or parking bays. `external_number_of_plugs` is the loader-compatible name for an explicit DC port count only. Unknown or conflicting values remain blank as confirmed scalar fields; source claims and warnings remain in the audit. No calibrated probability is available for `augmentation_match_confidence`, so it stays NULL.

For a separate strict-only replay that leaves the default output untouched:

```bash
python -m pipeline.data_aug_script --strict-only --results-dir data/result_data/strict_baseline --output data/aug_data/strict_baseline.csv
```

To fetch new external responses, choose a **new** snapshot directory and run:

```bash
export OCM_API_KEY='YOUR_REAL_API_KEY'
export TASK3_NEW_SNAPSHOT_DIR='data/reference/task3_new_snapshot'
python task3_ocm_tiled_snapshot.py
python task3_osm_snapshot.py --output-dir "$TASK3_NEW_SNAPSHOT_DIR" --refresh
python task3_chargelarge_snapshot.py
python -m pipeline.data_aug_script --snapshot-dir "$TASK3_NEW_SNAPSHOT_DIR" --results-dir data/result_data/new_snapshot_run --output data/aug_data/new_snapshot_run.csv
```

The key is required only for OCM collection; never put it in source code or submitted data. New API results can change coverage, and the stage checks the 50% threshold on every run.

## Database handoff

The teammate's staged loader consumes Task 3's public column names and follows the five-table structure in `ark-yeh` commit `874eb5b`. The complete pipeline rebuilds the database with:

| Table | Rows |
| --- | ---: |
| operator | 45 |
| charger_location | 1,958 |
| charger_characteristic | 1,958 |
| charger_connector | 435 |
| charger | 282 |

Primary-key duplicates, foreign-key orphans and review/unmatched augmentation leakage were all zero. Location geometry uses EPSG:7844; raw longitude/latitude remain WGS84. Run `python main.py --stage load` whenever the augmentation CSV changes, before packaging its database.

Operators are stored in a separate parent table. Locations and characteristics have a 1:1 relationship; normalized connector rows allow several types per location without delimiter-based SQL queries. The `charger` table retains accepted external attributes and their provenance. Opening hours, network, access, nullable free-charging flags, quality-review flags and source-specific JSON are preserved there as well. `external_number_of_plugs` means explicit external DC ports, not parking bays; source plug counts remain separate. `augmentation_match_confidence` stays NULL because no calibrated probability was measured. Accepted status is implicit in `charger`; review/unmatched outcomes remain in the CSV/audit.

Task 2's SA4 codes and names remain in the cleaned and augmented CSV files:
1,957 charger locations have an SA4 assignment and one remains unassigned.
Following the team's selected Task 4 design, SA4 polygons and codes are not
stored in DuckDB. SA4 analysis therefore requires the CSV and ABS boundary
files; the database retains charger point geometry and LGA names. The DDL
removes the earlier region table when rebuilding an existing six-table database.
The DuckDB file is generated at `data/db/.duckdb`.
That directory is Git-ignored, so include the generated database explicitly in
the final submission ZIP; committing the scripts alone does not submit it.

## Outputs and submission

| File or directory | Contents |
| --- | --- |
| `data/src_data/` | Original TfNSW CSV and ABS SA4 ZIP, also obtainable by the cleaning stage |
| `data/clean_src_data/nsw_ev_charging.csv` | Task 2 output: 1,958 rows, 54 columns; 1,957 assigned an SA4, one unassigned |
| `data/reference/` | Raw API snapshots, metadata and historical web notes used by Task 3 |
| `data/aug_data/nsw_ev_charging.csv` | Task 3 output: 1,958 rows, 73 columns, including 282 accepted DC rows |
| `data/result_data/task3_multisource_matches.csv` | Strict source-specific candidate decisions for 433 DC rows |
| `data/result_data/task3_final_multisource_output/` | Final audit, 58 web-rule rows, review queue, quality flags, source/run manifests and checksums |
| `db/schema/nsw_evc_schema.sql` | Task 4 relational/spatial DDL |
| `data/db/.duckdb` | Generated five-table DuckDB database; Git-ignored and explicitly included in the submission ZIP |

The bundled output was regenerated with `python main.py --stage all` after restoring the five-table database design. Loading was checked against both an earlier six-table database and a fresh database, including rollback on an injected loading failure and preservation of the augmentation fields. The current results and file hashes are in `data/result_data/submission_validation.json`. Earlier development verification installed the pinned requirements in a fresh Python 3.12.4 environment and passed 61 regression tests on the previous revision. That test suite is retained separately and is not included in this submission; the earlier result is not a claim that those tests were rerun unchanged against this schema. Source retrieval was previously tested against the official websites in an empty temporary directory using the saved geocoding cache. Successful execution and validation do not establish station identity accuracy.

The code/database ZIP must include source data, saved external snapshots, geocoding cache, code, requirements, DDL and `data/db/.duckdb`. Do not include `.venv`, `.git`, API keys, trial outputs or Python caches. The group report PDF and unified formal AI usage report are separate deliverables. The report should explain the five-table schema and CSV-based SA4 retention, include its diagram and give concrete matching examples. Affected source files retain their required AI citation acknowledgements at the top.

## Code and data attribution

The team implemented the core acquisition and cleaning workflow. Anthropic Claude and Google Gemini assisted with regular expressions, related text standardisation and some pipeline integration. OpenAI Codex later revised specific shared utilities, download safeguards, cache handling and stage interfaces during integration and verification. The affected file headers identify these later changes separately from the team's original implementation. Task 3 and Task 4 headers also disclose AI-generated or revised code; the separate group AI usage report provides the full account.

The source data are from [TfNSW EV charging locations (December 2025 CSV)](https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv) and the [ABS ASGS Edition 4 digital boundaries](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files). Task 3 uses the [Open Charge Map API](https://openchargemap.org/develop/api), the [OSM-derived Opendatasoft dataset](https://public.opendatasoft.com/explore/dataset/osm-australia-charging-station/information/) and the [Charge@Large dataset](https://data.peclet.com.au/explore/dataset/charge-at-large/api/). OSM-derived records and cached Nominatim results contain OpenStreetMap contributor data; retain [OpenStreetMap attribution](https://www.openstreetmap.org/copyright). Exact TfNSW/ABS download URLs are in `config.py`; provider metadata and source links are bundled. The repository's code licence does not replace third-party data licences.
