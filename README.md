# NSW EV Charging Station Data Processing Pipeline

The team pipeline cleans and integrates TfNSW/ABS data (Tasks 1–2), augments DC locations (Task 3), and loads the results into DuckDB (Task 4).

This version integrates `ark-yeh` commit `874eb5b` and the student's revised Task 3 implementation. The latest Task 3 benchmark is **224/433 DC rows (51.73%)**, using the API snapshots collected on 24 September 2026. See [TASK3_README.md](TASK3_README.md) for matching rules, data quality and reproducibility.

## Install and run

Python 3.12.4 was tested with the pinned dependencies in `requirements.txt`, including the team's pandas 3.0.5 and NumPy 2.5.3.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py --stage augment
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

The default is `all`. The load stage rebuilds the project's DuckDB tables. The DuckDB spatial extension must be available; its first installation requires internet access. Augmentation uses saved snapshots and requires no API key or network connection.

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

The old root-level compatibility scripts and experimental matching scripts have been retired. Use the stage commands above or `python -m pipeline.data_aug_script --help`.

## Task 2 replay and Task 3 handoff

The latest teammate cleaning stage was rerun against the bundled TfNSW data and the saved reverse-geocoding responses. It produces 1,958 rows and 54 columns, including 433 DC rows. Under the original validation environment its CSV is byte-identical to the previous Task 2 snapshot. Task 3 preserves all source columns, values and row order and appends 19 columns.

Task 2 uses the saved `data/result_data/task2_nominatim_cache.json` by default. If new inputs need reverse geocoding, explicitly set `ADDRESS_ENRICHER_ALLOW_NETWORK=1`; successful requests are rate-limited and cached. Task 3 does not rerun or modify Task 2.

## Database handoff

The existing teammate loader consumes Task 3's public column names. Its end-to-end validation passed with:

| Table | Rows |
| --- | ---: |
| operator | 45 |
| charger_location | 1,958 |
| charger_characteristic | 1,958 |
| charger_connector | 345 |
| charger | 224 |

Primary-key duplicates, foreign-key orphans and review/unmatched augmentation leakage were all zero. Location geometry follows the teammate loader's EPSG:7844 setting. These checks validate the integration; they do not constitute an independent review of every Task 4 rubric item.

## Submission evidence

- [Task 3 methodology, outputs and limitations](TASK3_README.md)
- [Facts to use when updating the student's report](TASK3_REPORT_NOTES.md)
- [Task 3 AI assistance and contribution record](TASK3_AI_USAGE.md)
- `data/result_data/task3_final_multisource_output/task3_run_manifest.json`
- `data/result_data/task3_final_multisource_output/task3_source_manifest.json`

Include source data, saved external snapshots, code, requirements and the group report in the submission package. The formal AI usage report must reflect the complete group contribution and be checked by the students.
