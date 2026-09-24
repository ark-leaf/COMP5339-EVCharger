# Task 3 — reproducible DC charger augmentation

## Current result

The 24 September 2026 API snapshots yield **282 policy-accepted DC rows out of 433 (65.13%)**: 224 strict matches (51.73%) plus 58 accepted by the requested historical-web-evidence rule below. All 282 have normalized connector types, an attribute absent from the original TfNSW data. The 50% target requires 217 rows. There are 37 review-only rows and 114 unmatched rows. AC rows receive no external attributes.

Coverage measures rows meeting the documented matching policy; it is not a measured precision or accuracy score. The 433 DC rows contain 430 distinct coordinate pairs; 282 accepted rows have distinct coordinate pairs (282/430 = 65.58%). A coordinate pair is not a verified count of physical charging sites. The extra 58 are rule-accepted, not manually verified or newly checked online.

Earlier 239/433 and 314/433 figures came from different code and acceptance policies. They are not this release's results.

## Integration with the teammate framework

Base: `ark-yeh` commit `874eb5b`. The teammate's cleaning framework, stage functions and database loading structure are retained. Shared changes support cached geocoding, Python 3.12 annotations, whole-DataFrame reads and safe source downloads. Final submission fixes require the ABS boundary, remove unused cleaning-stage augmentation stubs, preserve SA4 and remaining external fields in DuckDB, and make database rebuilds transactional. See `SUBMISSION_CHECKS.md` for the whole-pipeline checks.

```text
main.py --stage augment
  -> pipeline.data_aug_script.nsw_evc_augmentation()
  -> read current Task 2 CSV
  -> normalize and match saved external records
  -> audit source identity, conflicts and genuinely new attributes
  -> GET_NSW_EV_COLUMN_AUGMENTATION_CCS / MULTISOURCE
  -> original ColumnCleaner + DataCleaner
  -> validate, export CSV and record manifests
```

Business rules remain in `pipeline/data_aug/`. The three API collectors are independent acquisition commands. Normal augmentation never queries APIs or falls back to an older OCM-only implementation.

### Module responsibilities after cleanup

| Existing module | Responsibility |
| --- | --- |
| `nsw_evc_aug_config.py` | Paths, thresholds, Task 2 input contract, shared row-alignment checks, reserved cleaner factories |
| `charging_match_rules.py` | Metre distances, address parsing/scoring, shared missing-value and numeric handling |
| `ocm_reference.py` | OCM normalization and NSW boundary filtering |
| `multisource_matching.py` | Three source adapters, candidate selection and strict matching decisions |
| `multisource_audit.py` | Historical-web rule, attribute conflicts, shared-ID warnings and coverage summaries |
| `multisource_augmentation.py` | Map accepted audit attributes into the teammate's ColumnCleaner objects |
| `nsw_evc_aug_utils.py` | Preflight, stage orchestration, final validation, CSV export and CLI |
| `provenance.py` | Snapshot registry, content hashes and retrieval evidence |

The Task 3 cleanup added no business modules. It unified duplicate matching/audit alignment checks and source definitions, reused scalar parsing, removed an unused wrapper and duplicate final validation, and parsed each external address once per source-matching run. Required columns now fail explicitly at both evidence boundaries. Conflict fields use a fixed order, preventing Python hash randomization from changing warning strings and CSV checksums. Subsequent submission fixes to shared download and database code do not change the Task 3 matching policy.

Both reserved factory names and the stage entry remain unchanged. The separate strict matcher and final audit are intentional: keeping them makes the 224 strict decisions and 58 rule-based additions independently inspectable. Source collectors and historical evidence are retained; they are not duplicate runtime pipelines.

## Sources and acquisition evidence

| Source | Raw snapshot | NSW candidates | DC-indicated candidates |
| --- | ---: | ---: | ---: |
| OCM | 452 unique POIs | 277 | 193 |
| OSM-derived mirror | 509 records | 509 | 229 |
| Charge@Large | 1,958 locations | 1,235 | 75 |

- **OCM:** `https://api.openchargemap.io/v3/poi/`, 16 overlapping bounding-box queries, `countrycode=AU`, expanded connection details, ID deduplication, followed by NSW boundary filtering. The key is sent only in the `X-API-Key` header. A query reaching its configured result cap raises an error.
- **OSM-derived data:** the Opendatasoft `osm-australia-charging-station` API, six pages with a NSW filter and stable ID ordering. The collector checks totals, duplicate records and coordinates. This is an OSM mirror, **not a direct Overpass query**. OSM node/way IDs use their typed URL when available.
- **Charge@Large:** `https://chargeatlarge.app/locations`; raw locations and nested ports are saved. The recorded query covers power 0–350 kW and does not restrict results to currently available or accessible locations. It therefore does not establish complete NSW coverage. NSW clipping and DC connector selection occur locally.

The default snapshots are in `data/reference/task3_live_20260924/`. All three collectors were actually executed on 24 September; the associated metadata contains UTC retrieval times and SHA-256 values. A retrieval date is not the last update date of each station.

Historical API records are retained in `data/reference/task3_historical/`. The historical OSM snapshot has a verified 23 September checksum and the same record contents. The old OCM query log records 16 requests and a retrieval date but lacks an original checksum. The old Charge@Large query summary records its parameters and record count but lacks a retrieval timestamp. Those missing historical facts are left unknown.

## Strict matching baseline

1. Process only Task 2 DC rows. External candidates must have CCS or CHAdeMO evidence; OCM records explicitly marked non-operational are excluded.
2. Calculate geographic distance locally in **metres** from latitude/longitude. No OCM default miles setting is involved in matching.
3. Search within **500 m**, and retain strong fuzzy-address candidates outside that radius for review.
4. Automatically accept a candidate within **100 m**, or within **500 m with a corroborating numbered address**. Address parsing normalizes street abbreviations, house numbers and postcodes; the overall address threshold is 0.85 with additional component checks.
5. Explicit postcode or house-number conflicts require review. Repaired source postcodes retain their raw provenance. A second similarly close candidate (gap below 20 m), near-tied evidence or selection of a materially more distant candidate also requires review.
6. When an external record serves several TfNSW rows, accept shared use only if each pair represents the same numbered address or source points within 50 m. Otherwise send the assignments to review. Do not sum site-level port counts across these rows.
7. Address-only candidates outside 500 m remain review-only. This stage does not use historical web notes. Its candidate file and matching summary retain the 224-row baseline.

## Historical web evidence acceptance rule

The audit applies an additional rule requested by the student; it does not change the strict matcher or target a fixed number of rows:

1. Consider only DC rows whose strict combined status is `review`. Leave strict accepted and unmatched rows unchanged.
2. Require a historical note attached to the current normalized source address. OCM notes additionally require the same current OCM ID. Require a nonempty evidence URL and a `high` or `medium` evidence label; a negative conclusion cannot supply support. An opened page is not required.
3. Require a current review candidate with an external ID, DC evidence, distance **0–500 m inclusive**, and at least one genuinely new attribute. Explicitly non-operational candidates are excluded.
4. Select **one nearest eligible candidate per source row**. Break exact distance ties in OCM, OSM, Charge@Large order. The web note is row-level support and may refer to a different provider than the selected candidate; it is not external-ID identity verification.
5. Export that candidate's attributes through the existing cleaners. Set `acceptance_basis` and its match method to `coordinate_500m_historical_web_rule`. Preserve strict statuses, methods and rejection reasons in the audit; flag every newly accepted row for quality review.

Under this policy, house/postcode disagreements, ambiguous neighbours and shared IDs remain warnings rather than vetoes. This can accept an incorrect identity, including a row with inconsistent source coordinates and address. High/medium labels describe the old web evidence, not the probability that the chosen external station is correct. No fresh manual verification is claimed.

The rule adds 58 distinct rows: 22 use OCM, 29 OSM and 7 Charge@Large. Total accepted source links are OCM 148, OSM 176 and Charge@Large 34, with overlap, giving a union of 282. OCM+OSM covers 255 rows; Charge@Large adds 27 otherwise uncovered rows.

The final audit has 35 shared-external-ID groups and 164 warning-bearing accepted rows. These include all 58 web-rule rows and baseline rows affected by the enlarged shared-ID groups. Shared records are not summed into counts of physical stations or bays. Neither warning counts nor web labels are measured error rates.

## Attribute meanings and missing values

| Exported field | Nonempty accepted rows | Meaning |
| --- | ---: | --- |
| normalized connectors | 282 | Sorted, deduplicated union of reported connector types |
| external maximum power | 177 | Agreed source maximum, in kW |
| external minimum power | 176 | DC connection/port minimum where explicitly available |
| external DC port count | 34 | Explicit Charge@Large DC ports |
| usage cost | 121 | Original text; no invented tariff/currency conversion |
| free-charging flag | 176 | Mirror-reported true/false; missing stays unknown |
| access condition | 176 | Source access description |
| external operator | 148 | Additional source value; never replaces TfNSW operator |
| network | 63 | Source network label |
| opening hours | 32 | Source text; absent information remains empty |

OCM DC powers come only from DC-indicated connections, excluding AC ratings at mixed sites. OSM supplies a station maximum and no minimum. Charge@Large powers refer to DC-indicated ports. Per-source `power_scope` is retained in `external_attributes_json` so these meanings remain visible.

OCM `NumberOfPoints` and OSM `charge_points_count` are not assumed to be physical plugs or bays. Charge@Large port IDs are deduplicated within devices; a port with several connector labels is still one port. The loader-compatible `external_number_of_plugs` column is an alias of the explicit DC port count, not a replacement for the original TfNSW plug count.

Conflicting numeric attributes are removed from the confirmed export and kept as observations in the audit. Missing values remain empty/nullable, not zero. Explicit source booleans remain booleans in JSON. Postcodes, SA4 codes and external IDs retain their text form.

Power, counts, operator and provenance fields alone do not count toward the assignment's “new attribute” target. All 282 accepted rows satisfy that target through connector types. The nullable `augmentation_match_confidence` column exists for the teammate loader and is left empty because no calibrated probability has been measured.

## Historical web notes

The 125-row OCM and 104-row supplemental search files are preserved in `data/reference/web_review/`. Notes are attached only when the source address still agrees; OCM notes also require the same external ID. Supplemental notes do not prove candidate identity.

The final audit attaches historical context to 205 rows. The additional rule uses these notes as described above, but does not relabel them as independent identity verification. Of the original 95 strict review rows, 74 have attached notes, 71 have a candidate within 500 m, and 58 meet the high/medium evidence rule. The three out-of-radius cases (Swansea, Lake George and Lake Haven) are not promoted. Some old notes cannot be reused because candidate IDs or source addresses changed.

## Run and refresh

Offline, from the project root:

```bash
python main.py --stage augment
python -m unittest discover -s tests -v
```

Reproduce the strict baseline in separate files without changing the default result:

```bash
python -m pipeline.data_aug_script --strict-only --results-dir data/result_data/strict_baseline --output data/aug_data/strict_baseline.csv
```

For custom Task 2 output and separate result files:

```bash
python -m pipeline.data_aug_script --input data/clean_src_data/nsw_ev_charging.csv --output data/aug_data/nsw_ev_charging.csv --results-dir data/result_data
```

To collect a separate snapshot set, set a real ASCII key in the shell and choose a new directory:

```bash
export OCM_API_KEY='YOUR_API_KEY'
export TASK3_NEW_SNAPSHOT_DIR='data/reference/task3_new_snapshot'
python task3_ocm_tiled_snapshot.py
python task3_osm_snapshot.py --output-dir "$TASK3_NEW_SNAPSHOT_DIR" --refresh
python task3_chargelarge_snapshot.py
python -m pipeline.data_aug_script --snapshot-dir "$TASK3_NEW_SNAPSHOT_DIR" --results-dir data/result_data/new_snapshot_run --output data/aug_data/new_snapshot_run.csv
```

Never commit the key. Collectors reject destinations containing their previous snapshots. New API results can differ; the runtime validates the 50% target for each run rather than assuming the frozen benchmark.

## Outputs and validation

- `data/aug_data/nsw_ev_charging.csv`: 1,958 rows, 73 columns; 54 unchanged source columns plus 19 additions.
- `data/result_data/task3_multisource_matches.csv`: strict source-specific candidate decisions for all 433 DC rows; its summary reports the 224-row baseline, not the final policy result.
- `data/result_data/task3_final_multisource_output/`: final audit, 37-row review queue, 164-row residual-warning table, shared-ID report, source manifest and run manifest.
- `task3_web_rule_accepted.csv` in that audit directory: the 58 additional records, their selected candidate, historical evidence, strict decisions and remaining warnings.
- The run manifest records input/output hashes, runtime package versions, row counts and the assignment-target check.
- The tests include shared evidence alignment, missing columns, invalid/duplicate indices, cached address parsing, policy radius/quality boundaries, negative or stale evidence, and replay of both 282-row and 224-row policies. Final test results are recorded in `SUBMISSION_CHECKS.md`.
- The full cleaning/augmentation/loading run regenerates the packaged database: 282 augmentation rows, 435 atomic connector rows and 28 SA4 polygons; no primary-key duplicates, foreign-key orphans or review/unmatched leakage. Source-specific attribute JSON and the remaining external fields are preserved in DuckDB. Cleaned and augmented CSV business values remain unchanged.

The loader handoff is now part of the end-to-end regression test, using an in-memory database and the installed DuckDB spatial extension. The test does not install extensions or call external APIs. Install the extension once before running the full suite on a new machine, for example `python -c "import duckdb; duckdb.connect().execute('INSTALL spatial')"` with network access.

## Task 3 requirement check

| Requirement | Current evidence |
| --- | --- |
| Acquire external data programmatically | Three collectors; saved raw API responses and hash-bound query metadata |
| At least one new attribute for at least 50% of DC rows | All 282 accepted rows have connector types; 282/433 exceeds the 217-row threshold |
| Explain association and enhancement methods | Strict and web-evidence rules above; per-source IDs, distances and decisions in the audit |
| Handle inconsistent formats and missing values | kW normalization, connector names, explicit port-count semantics, nullable unknowns and conflict suppression |
| Preserve the integrated dataset and support the next stage | 1,958 rows; 54 original columns unchanged; 19 added columns; regression-tested teammate loader |
| Reproducible execution and source attribution | Offline snapshots, manifests, stage command, tests and source links |

These checks establish the implemented Task 3 behavior, not independently verified station identity or guaranteed marks. The group must still finalize its report, AI-use declaration and submission package. The stricter 224/433 baseline also exceeds 50%; the extra 58 improve documented policy coverage, not measured accuracy.

## Sources and disclosure

Source attribution and raw provider metadata are retained. Reference the [OCM API](https://openchargemap.org/develop/api), [OSM-derived dataset](https://public.opendatasoft.com/explore/dataset/osm-australia-charging-station/information/), [OpenStreetMap attribution](https://www.openstreetmap.org/copyright), and [Charge@Large dataset](https://data.peclet.com.au/explore/dataset/charge-at-large/api/) in the group report.

See [TASK3_AI_USAGE.md](TASK3_AI_USAGE.md) for the actual contribution record and [TASK3_REPORT_NOTES.md](TASK3_REPORT_NOTES.md) for the current report facts. Tests establish software behavior; neither testing nor disclosure alone determines compliance with the unit's AI rules.
