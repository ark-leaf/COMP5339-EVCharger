# NSW EV Charging Station Data Processing Pipeline

The team pipeline cleans and integrates TfNSW/ABS data (Tasks 1–2), augments DC locations (Task 3), and loads the results into DuckDB (Task 4).

This version integrates `ark-yeh` commit `874eb5b` and the student's revised Task 3 implementation. Task 3 accepts **282/433 DC rows (65.13%)** under the documented policy: 224 strict matches plus 58 added by a 500 m / historical high-or-medium web-evidence rule. This is policy coverage, not independently measured identity accuracy. The API snapshots are from 24 September 2026. See [TASK3_README.md](TASK3_README.md) for rules, warnings and the separate strict-baseline command.

## Install and run

Python 3.12.4 was tested with the pinned dependencies in `requirements.txt`, including the team's pandas 3.0.5 and NumPy 2.5.3.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py --stage all
python -m unittest discover -s tests -v
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

The final review keeps this layout and adds no business modules. Input alignment, source definitions and scalar parsing are shared rather than repeated. Tests cover both matching policies, offline cleaning replay, source downloads, the staged loader and transaction rollback. The DuckDB spatial extension must already be installed for database tests.

Unused augmentation placeholders were removed from the cleaning configuration. Experimental root-level scripts are not part of the submission ZIP; local copies were preserved. Use the stage commands above or `python -m pipeline.data_aug_script --help`.

## Task 2 replay and Task 3 handoff

The latest teammate cleaning stage was rerun against the bundled TfNSW data and the saved reverse-geocoding responses. It produces 1,958 rows and 54 columns, including 433 DC rows. Under the original validation environment its CSV is byte-identical to the previous Task 2 snapshot. Task 3 preserves all source columns, values and row order and appends 19 columns.

Task 2 uses the saved `data/result_data/task2_nominatim_cache.json` by default. If new inputs need reverse geocoding, explicitly set `ADDRESS_ENRICHER_ALLOW_NETWORK=1`; successful requests are rate-limited and cached. Task 3 does not rerun or modify Task 2.

## Database handoff

The teammate's staged loader consumes Task 3's public column names and retains Task 2's SA4 linkage. The complete pipeline rebuilds the database with:

| Table | Rows |
| --- | ---: |
| operator | 45 |
| sa4_region | 28 |
| charger_location | 1,958 |
| charger_characteristic | 1,958 |
| charger_connector | 435 |
| charger | 282 |

Primary-key duplicates, foreign-key orphans and review/unmatched augmentation leakage were all zero. Location and region geometry use EPSG:7844; raw longitude/latitude remain WGS84. Run `python main.py --stage load` whenever the augmentation CSV changes, before packaging its database.

Operators and regions are separate parent tables. Locations and characteristics have a 1:1 relationship; normalized connector rows allow several types per location without delimiter-based SQL queries. The `charger` table retains accepted external attributes and their provenance. Opening hours, network, access, nullable free-charging flags, quality-review flags and source-specific JSON are now preserved there as well. `external_number_of_plugs` means explicit external DC ports, not parking bays; source plug counts remain separate. `augmentation_match_confidence` stays NULL because no calibrated probability was measured. Accepted status is implicit in `charger`; review/unmatched outcomes remain in the CSV/audit.

Task 4 stores the 28 referenced ABS SA4 regions with their polygon geometry and
links 1,957 charger locations to them via `sa4_code`; the one unassigned Task 2
row remains NULL. The loader reads the same archived ABS boundaries as Task 2,
preserves the teammate's staged loading interface, and checks that linked points
fall inside their regions. The DuckDB file is generated at `data/db/.duckdb`.
That directory is Git-ignored, so include the generated database explicitly in
the final submission ZIP; committing the scripts alone does not submit it.

## Submission evidence

- [Whole-pipeline submission checks and remaining group deliverables](SUBMISSION_CHECKS.md)
- [Task 3 methodology, outputs and limitations](TASK3_README.md)
- [Facts to use when updating the student's report](TASK3_REPORT_NOTES.md)
- [Task 3 AI assistance and contribution record](TASK3_AI_USAGE.md)
- `data/result_data/task3_final_multisource_output/task3_run_manifest.json`
- `data/result_data/task3_final_multisource_output/task3_source_manifest.json`

The code/database ZIP must include source data, saved external snapshots, geocoding cache, code, requirements, DDL and `data/db/.duckdb`. Do not include `.venv`, `.git`, API keys, trial outputs or Python caches. The group report PDF and formal AI usage report are separate deliverables, not replaced by these README files. The formal AI usage report must reflect the complete group contribution and be checked by the students.

## Data attribution

The source data are from [TfNSW EV charging locations (December 2025 CSV)](https://opendata.transport.nsw.gov.au/data/dataset/be1c4de4-4517-4bd0-8a09-2965ddfc7179/resource/7bbb6461-e52d-4fe7-ace4-a15c30198de0/download/ev_20251216.csv) and the [ABS ASGS Edition 4 digital boundaries](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-4-july-2026-june-2031/access-and-downloads/digital-boundary-files). Exact download URLs are in `config.py`. External sources and their API/dataset links are listed in [TASK3_README.md](TASK3_README.md). OSM-derived records and cached Nominatim results contain OpenStreetMap contributor data; retain [OpenStreetMap attribution](https://www.openstreetmap.org/copyright). Provider metadata and source links are bundled; the repository's code licence does not replace third-party data licences.
