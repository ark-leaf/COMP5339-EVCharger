# Task 3 — External EV Charger Data Augmentation

This document describes the reproducible Task 3 workflow for augmenting the
TfNSW EV charger data with external charger attributes. The original TfNSW
values are preserved; external values are stored with source-specific names and
matching evidence.

## Objective and target population

Task 3 targets the 433 TfNSW records whose cleaned `Charger_Type` is `DC`.
An external record is a candidate match when at least one of the following is
satisfied:

```text
local Haversine distance <= 500 metres
OR
structured fuzzy address score >= 0.85
```

The final DC-indicated union uses OCM, OSM records with a DC/fast-charger
indicator, and Charge@Large records with a DC/fast-charger indicator. Distances
are recalculated locally in metres; no API default unit is used by the matcher.
The current implementation is row-level and does not enforce one-to-one
matching, because one external station can legitimately correspond to more
than one TfNSW charger record.

## External sources

### Open Charge Map (OCM)

- Endpoint: `https://api.openchargemap.io/v3/poi/`
- Authentication: `X-API-Key` request header, read from `OCM_API_KEY`.
- Retrieval: overlapping NSW bounding-box queries in
  `task3_ocm_tiled_snapshot.py`.
- Local cache: `result_data/task3_ocm_tiled_snapshot.json` and its metadata
  file.
- Normalised attributes: station ID, name, address, coordinates, operator,
  connector types, plug count, power, operational status, usage cost and
  verification/comments fields.
- OCM records are eligible for the DC match only when CCS/CHAdeMO or a power
  value of at least 40 kW indicates DC/fast charging, and they are not marked
  closed/decommissioned. `NumberOfPoints` falls back to positive connection
  `Quantity` when the station-level value is zero or missing.

The key must never be written to source code, CSV/JSON output or Git. Set it
only in the shell for a fresh OCM snapshot:

```bash
export OCM_API_KEY='your-real-api-key'
python task3_ocm_tiled_snapshot.py
```

### OpenStreetMap (OSM)

The current committed snapshot is an OSM-derived public mirror of NSW charging
stations. It is recorded as `OSM-derived public mirror snapshot`; it should
not be described as a live Overpass response. If the snapshot is absent,
`task3_multisource_supplement_trial.py` can fetch the public mirror pages and
cache them locally.

The OSM fast/DC filter is true when a record has CCS or CHAdeMO connector tags,
or `max_power_kw >= 40`. Positive `charge_points_count` values above 100 are
kept only as raw provenance and withheld from the standardised plug count as
suspicious.

### Charge@Large

- Public endpoint: `https://chargeatlarge.app/locations`
- Script: `task3_chargelarge_snapshot.py`
- Local files: `result_data/task3_chargelarge_raw.json`,
  `result_data/task3_chargelarge_nsw.csv` and the summary JSON.

The Charge@Large fast/DC filter is true when a port has CCS1, CCS2 or CHAdeMO,
or power of at least 40 kW. The flattened data provides address, coordinates,
total/DC-indicated port counts, connector types, power and status counts. The
standardised plug count uses the DC-indicated port count.

## Reproduce the matching workflow

Run these commands from the repository root. The committed snapshots allow the
matching and audit stages to run without credentials. Only the OCM snapshot
refresh needs `OCM_API_KEY`.

```bash
# Optional: refresh the external snapshots.
export OCM_API_KEY='your-real-api-key'
python task3_ocm_tiled_snapshot.py
python task3_chargelarge_snapshot.py

# Build the per-source matches and the DC-indicated union.
python task3_multisource_supplement_trial.py

# Add stable row IDs, provenance, review status and audit fields.
python task3_final_multisource_audit.py

# Run the team's original DataCleaner pipeline with the final audit adapter.
python main.py
```

The matching script uses the cleaned Task 2 file at
`clean_src_data/nsw_ev_charging.csv`. The current repository contains the
cleaned file and the external snapshots used for the reported result.

## Matching and review policy

For every source, the matcher stores the best candidate and retains:

- source-specific match status and method;
- external ID and address;
- local distance in metres;
- fuzzy address score where an address is available;
- source-specific external attributes;
- whether the result is coordinate-supported or address-only.

Coordinate-supported matches are automatic candidates, not ground-truth
identity labels. Address-only matches are placed in the manual-review queue.
Address conflicts should be checked using street number, street name, suburb,
postcode, station name, operator and map position. A web page is evidence for
review, not by itself proof that two records are the same physical station.

The final audit also reports external IDs assigned to multiple TfNSW rows. This
is a diagnostic for station-level versus charger-level duplication; it is not
silently resolved by dropping rows.

## Final results

The final results use 433 unique TfNSW DC rows:

| Result | Rows | Coverage |
|---|---:|---:|
| OCM-only accepted candidates | 211 | 48.73% |
| OCM + OSM fast/DC + Charge@Large fast/DC candidates | 322 | 74.36% |
| Coordinate-supported candidates | 315 | 72.75% |
| Address-only/manual-review candidates | 7 | 1.62% |
| Unmatched by the selected DC-indicated sources | 111 | 25.64% |
| Provisionally supported after saved evidence screening | 289 | 66.74% |

The 322 figure is a row-level candidate coverage, not a count of unique
external stations and not a completed manual validation result. All 322
candidate rows contain at least one external attribute in
`has_new_attributes`.

Source-level diagnostics from the same run are:

| Source | Accepted rows | Unique external IDs |
|---|---:|---:|
| OCM | 211 | 169 |
| OSM fast/DC | 219 | 179 |
| Charge@Large fast/DC | 56 | 38 |

The difference between accepted rows and unique IDs is expected under the
row-level, non-one-to-one policy and is listed in the duplicate-ID report.

## Output files

Primary matching outputs:

- `result_data/task3_multisource_matches.csv` — per-source matches and the
  322-row DC-indicated union.
- `result_data/task3_multisource_summary.json` — source counts and matching
  rules.
- `result_data/task3_final_multisource_output/task3_multisource_final_audit.csv`
  — one row per TfNSW DC record with stable IDs, provenance and audit fields.
- `result_data/task3_final_multisource_output/task3_multisource_final_audit_summary.json`
  — final coverage and diagnostics.
- `result_data/task3_final_multisource_output/task3_multisource_manual_review_queue.csv`
  — the seven address-only candidates requiring review.
- `result_data/task3_final_multisource_output/task3_duplicate_external_id_report.csv`
  — external IDs assigned to more than one TfNSW row.

Saved evidence files include the existing OCM and non-OCM web-review reports.
They are retained separately from the automatic matching result so that
evidence quality is not confused with identity confirmation.

## Known limitations

1. OSM coverage is based on a public mirror snapshot, not a live Overpass
   query.
2. External sources have different schemas. Missing attributes are kept blank;
   they are not inferred as zero or copied from another source.
3. OCM, OSM and Charge@Large do not necessarily identify the same station at
   the same granularity as TfNSW. Duplicate external IDs therefore require
   interpretation rather than automatic deletion.
4. Seven address-only candidates remain pending manual review. The
   `provisionally_supported` count includes saved local/web evidence and should
   be reported as provisional until the team records final review decisions.
5. External snapshots are point-in-time data. The retrieval timestamp in each
   metadata/summary file should be included in the assignment report.

## Files and code

| File | Role |
|---|---|
| `task3_ocm_tiled_snapshot.py` | OCM NSW snapshot retrieval |
| `task3_chargelarge_snapshot.py` | Charge@Large retrieval and flattening |
| `task3_multisource_supplement_trial.py` | OCM/OSM/Charge@Large matching |
| `task3_final_multisource_audit.py` | final audit, provenance and review outputs |
| `config.py` | existing OCM adapter plus the compatible multi-source
  `DataCleaner`/`ColumnCleaner` augmentation interface |
