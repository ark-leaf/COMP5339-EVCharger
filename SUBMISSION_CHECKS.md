# Code and database submission checks — 25 September 2026

This is a technical verification record, not the group's report, a signed AI
declaration, or a guarantee of marks. The base is the team's `874eb5b` layout,
integrated on branch `dengjie`; the final review preserves the stage functions,
configuration locations and ColumnCleaner/DataCleaner interfaces.

## Requirements and evidence

| Requirement | Verified implementation/result |
| --- | --- |
| Programmatic source acquisition | The cleaning stage downloads TfNSW December 2025 CSV and ABS SA4 Edition 4 (2026, GDA2020) ZIP when absent. Both official downloads and cleaning were tested in an empty temporary source directory. |
| Cleaning and integration | 1,958 rows, 54 columns, 433 DC rows; numeric coordinates/plugs, address/postcode/operator normalization and power parsing. There are no exact duplicate source or cleaned rows; coincident coordinates are not blindly deleted. |
| Spatial association | 1,957 rows have an SA4 code/name. One point at Clontarf is outside the matched polygons and remains unassigned; no region is invented. Missing required boundaries now stop the run. |
| External augmentation | Saved OCM, OSM-derived Opendatasoft and Charge@Large API responses. 282/433 DC rows (65.13%) gain connector types absent from the source: 224 strict matches plus 58 historical-web-rule acceptances. |
| Data types and uncertainty | Source 54 columns/values/order retained; 19 additions. kW and explicit DC port semantics preserved. Unknown values remain missing. Conflicting values and identity warnings remain auditable. |
| Relational/spatial database | SQL DDL and generated DuckDB file, six tables with keys and GEOMETRY. 28 referenced SA4 polygons, 1,958 locations and characteristics, 45 operators, 435 connector rows, 282 augmentation rows. |
| Database completeness | Opening hours, access, network, nullable free-charging flags, quality flags and source-specific JSON are retained alongside the existing scalar fields. SQL BOOLEAN preserves false versus unknown. |
| Reproducibility | Fresh Python 3.12.4 environment installed the pinned requirements; `pip check` passed. Spatial installed and loaded successfully in a separate empty extension directory. Full `main.py --stage all` run passed. |
| Tests | `python -m unittest discover -s tests -v`: 61 passed, including strict/default policy replay, offline cleaning, download failure safety, CSV/SQL field round-trip and failed-load rollback. |

The new TfNSW download has CRLF endings while the bundled file uses LF; parsed
values are identical. Normalizing only CRLF reproduces the bundled bytes. The
fresh ABS download has exactly the bundled SHA-256. Cleaning the fresh downloads
using the included geocoding cache reproduces the saved cleaned CSV byte-for-byte.
The fresh-download check does not claim a new reverse-geocoding crawl.

## Changes made for submission

- Keep the team's architecture; add no new business modules. The only new Python
  file in this final review is `tests/test_submission.py`.
- Validate source downloads and replace cached files only after successful
  completion; add bounded HTTP timeouts and reject HTML/corrupt archives.
- Remove the unused `get_ocm_details()`/empty augmentation-factory placeholders
  from the cleaning configuration. The working Task 3 factories remain in the
  augmentation module. Experimental files outside the submitted pipeline remain
  in the local repository and are excluded from the ZIP.
- Preserve SA4 relationships and external attributes in the existing loader.
  Rebuild the database in a transaction and validate before commit.
- Update README/report facts and add file-level AI acknowledgements for known
  assistance. The code, documentation and tests added by Codex are disclosed.

The cleaning and augmentation CSVs retain their previous business values. These
changes do not make the 58 additional associations independently verified.

## Package and run

The code/database ZIP includes Python source, tests, requirements, SQL DDL, the
generated `data/db/.duckdb`, raw TfNSW/ABS files, API snapshots and metadata,
historical web notes, geocoding cache, cleaned/augmented CSVs and audit outputs.
It excludes `.git`, `.venv`, credentials, bytecode, trial scripts and root-level
experimental results. The database directory is Git-ignored, so a Git checkout
alone is not the complete database deliverable.

From the extracted project directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py --stage all
python -m unittest discover -s tests -v
```

On Windows, activate with `.venv\Scripts\activate`. The first Spatial extension
installation needs internet. Subsequent replay uses bundled data/cache and does
not need OCM credentials. To inspect the supplied database without rebuilding:

```python
import duckdb
conn = duckdb.connect("data/db/.duckdb", read_only=True)
conn.execute("LOAD spatial")
print(conn.execute("SHOW TABLES").fetchall())
conn.close()
```

## Remaining group responsibilities

1. Submit the report PDF and formal AI Usage Report through the required Canvas
   channels as well as the code/database ZIP. These Markdown files are not those
   final documents. The assignment report content limit is six pages, excluding
   the title page and optional appendix; team contributions are at most 100 words.
2. Ensure the report's schema diagram and explanation match the six final tables,
   the SA4 link and the additional stored fields. Do not describe the current
   loader as unchanged from the teammate commit.
3. Report 65.13% as policy coverage, not accuracy. Retain the separate 51.73%
   strict baseline, 58 rule-added records, 37 review-only and 114 unmatched rows.
   There are 164 accepted rows with warnings and 35 shared-external-ID groups.
4. Verify the group's AI declarations and affected-file attributions. The
   statement must include Codex's actual implementation/integration/database
   changes and tests, not just proofreading. Confirm any additional
   Claude/Gemini-assisted integration files with the teammate. Include genuine
   representative prompts and retain drafts/AI outputs as required.
5. The extensive AI involvement and student contribution boundary require the
   group's academic judgement and, if uncertain, the coordinator's guidance.
   Passing tests and adding acknowledgements do not by themselves establish
   compliance with that rule.
