# Task 3 — reproducible DC charger augmentation

## Current result

The 24 September 2026 API snapshots yield **224 accepted DC rows out of 433 (51.73%)**. All 224 have normalized connector types, an attribute absent from the original TfNSW data. The 50% target requires 217 rows. There are 95 review-only rows and 114 unmatched rows. AC rows receive no external attributes.

Coverage measures rows meeting the documented matching policy; it is not a measured precision or accuracy score. The 433 DC rows contain 430 distinct coordinate pairs; 224 accepted rows have distinct coordinate pairs (224/430 = 52.09%). A coordinate pair is not a verified count of physical charging sites.

Earlier 239/433 and 314/433 figures came from different code and acceptance policies. They are not this release's results.

## Integration with the teammate framework

Base: `ark-yeh` commit `874eb5b`. The Task 1/2 processing modules and all Task 4 modules use the teammate versions. Shared helper changes are limited to preserved geocoding cache support, a Python 3.12 forward-annotation fix, and handling a whole DataFrame in the shared file reader.

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

## Matching policy

1. Process only Task 2 DC rows. External candidates must have CCS or CHAdeMO evidence; OCM records explicitly marked non-operational are excluded.
2. Calculate geographic distance locally in **metres** from latitude/longitude. No OCM default miles setting is involved in matching.
3. Search within **500 m**, and retain strong fuzzy-address candidates outside that radius for review.
4. Automatically accept a candidate within **100 m**, or within **500 m with a corroborating numbered address**. Address parsing normalizes street abbreviations, house numbers and postcodes; the overall address threshold is 0.85 with additional component checks.
5. Explicit postcode or house-number conflicts require review. Repaired source postcodes retain their raw provenance. A second similarly close candidate (gap below 20 m), near-tied evidence or selection of a materially more distant candidate also requires review.
6. When an external record serves several TfNSW rows, accept shared use only if each pair represents the same numbered address or source points within 50 m. Otherwise send the assignments to review. Do not sum site-level port counts across these rows.
7. Address-only candidates outside 500 m remain review-only. Historical web searches cannot override the gate automatically.

The final accepted source counts are OCM 126, OSM 147 and Charge@Large 27; these overlap, giving a union of 224. OCM+OSM alone yields 204, so Charge@Large contributes 20 additional accepted rows in this release.

There are 16 retained shared-external-ID groups consistent with the co-location rule. The audit retains 96 accepted rows with residual warnings, including weak address text, shared station IDs or attribute disagreements. These warnings are visible rather than silently represented as high-confidence identity proof. The policy reduces obvious ambiguity but does not prove that every accepted link is correct.

## Attribute meanings and missing values

| Exported field | Nonempty accepted rows | Meaning |
| --- | ---: | --- |
| normalized connectors | 224 | Sorted, deduplicated union of reported connector types |
| external maximum power | 148 | Agreed source maximum, in kW |
| external minimum power | 147 | DC connection/port minimum where explicitly available |
| external DC port count | 27 | Explicit Charge@Large DC ports |
| usage cost | 103 | Original text; no invented tariff/currency conversion |
| free-charging flag | 147 | Mirror-reported true/false; missing stays unknown |
| access condition | 147 | Source access description |
| external operator | 126 | Additional source value; never replaces TfNSW operator |
| network | 57 | Source network label |
| opening hours | 29 | Source text; absent information remains empty |

OCM DC powers come only from DC-indicated connections, excluding AC ratings at mixed sites. OSM supplies a station maximum and no minimum. Charge@Large powers refer to DC-indicated ports. Per-source `power_scope` is retained in `external_attributes_json` so these meanings remain visible.

OCM `NumberOfPoints` and OSM `charge_points_count` are not assumed to be physical plugs or bays. Charge@Large port IDs are deduplicated within devices; a port with several connector labels is still one port. The loader-compatible `external_number_of_plugs` column is an alias of the explicit DC port count, not a replacement for the original TfNSW plug count.

Conflicting numeric attributes are removed from the confirmed export and kept as observations in the audit. Missing values remain empty/nullable, not zero. Explicit source booleans remain booleans in JSON. Postcodes, SA4 codes and external IDs retain their text form.

Power, counts, operator and provenance fields alone do not count toward the assignment's “new attribute” target. All 224 accepted rows satisfy that target through connector types. The nullable `augmentation_match_confidence` column exists for the teammate loader and is left empty because no calibrated probability has been measured.

## Historical web notes

The 125-row OCM and 104-row supplemental search files are preserved in `data/reference/web_review/`. Notes are attached only when the source address still agrees; OCM notes also require the same external ID. Supplemental notes do not prove candidate identity.

The final audit attaches historical context to 205 rows. Search result snippets, “high/medium” labels and opened web pages are not promoted into a verified match or counted as extra augmentation. No claim of 224 independently web-verified station identities is made.

## Run and refresh

Offline, from the project root:

```bash
python main.py --stage augment
python -m unittest discover -s tests -v
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
- `data/result_data/task3_multisource_matches.csv`: source-specific candidate decisions for all 433 DC rows.
- `data/result_data/task3_final_multisource_output/`: final audit, 95-row review queue, 96-row residual-warning table, shared-ID report, source manifest and run manifest.
- The run manifest records input/output hashes, runtime package versions, row counts and the assignment-target check.
- The tests cover source contracts, address/distance rules, reused IDs, units/counts, API pagination/failures, saved metadata, source preservation and complete replay.
- `python main.py --stage all` passed through the teammate loader: 224 augmentation rows and 345 atomic connector rows; no primary-key duplicates, foreign-key orphans or review/unmatched leakage.

## Sources and disclosure

Source attribution and raw provider metadata are retained. Reference the [OCM API](https://openchargemap.org/develop/api), [OSM-derived dataset](https://public.opendatasoft.com/explore/dataset/osm-australia-charging-station/information/), [OpenStreetMap attribution](https://www.openstreetmap.org/copyright), and [Charge@Large dataset](https://data.peclet.com.au/explore/dataset/charge-at-large/api/) in the group report.

See [TASK3_AI_USAGE.md](TASK3_AI_USAGE.md) for the actual contribution record and [TASK3_REPORT_NOTES.md](TASK3_REPORT_NOTES.md) for the current report facts. Tests establish software behavior; neither testing nor disclosure alone determines compliance with the unit's AI rules.
