# NSW EVCharger Data Processor

Integrated with the teammate's `ark-yeh@299b876` pipeline structure.
Task 3 migration details, data semantics, limitations and audit files are in
[TASK3_README.md](TASK3_README.md).

## Run

```bash
python -m pip install -r requirements.txt
python main.py --stage augment    # Task 3 only, consumes the existing Task 2 CSV
python main.py                    # Download/cache + Task 2 + Task 3
python -m unittest discover -s tests -v
```

The checked-in source files and geocoding/charging snapshots permit offline
replay. Task 3 never queries live APIs implicitly. See TASK3_README for explicit
refresh commands, custom input/output paths and API usage constraints.

## Structure and status

- `config.py`: shared paths/endpoints; credentials from environment only.
- `pipeline/data_clean/` + `data_clean_script.py`: teammate's Task 1/2 logic.
- `pipeline/data_aug/` + `data_aug_script.py`: independent Task 3 configuration,
  matching, audit, existing ColumnCleaner adapter, validation and export.
- `pipeline/data_load/`: Task 4 placeholder; no claim of completed DuckDB storage.

The updated Task 2 output contains 1,958 rows and 54 columns. Task 3 preserves
all source fields, appends 49 fields, and enriches **239/433 DC rows (55.20%)**
with at least one genuinely new attribute. Another 83 DC rows are review-only;
111 are unmatched. The 69 accepted-row quality flags are tracked separately.
Coverage is not independently measured matching accuracy.

Legacy root commands remain thin compatibility wrappers. The raw source and
the three charging snapshots are preserved; generated cleaned/augmented/audit
outputs are refreshed for the new pipeline.

The group must still finalize its report, required AI-use acknowledgement and
overall submission. Completing Task 3 does not establish completion of Task 4.
