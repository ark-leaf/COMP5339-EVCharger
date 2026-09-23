# Task 3 — external EV charger enrichment

## Modular Task 2 → Task 3 hand-off

Task 3 follows the module split proposed on `ark-yeh` (`6803adc`).
The previously completed matching policy and source snapshots are reused.
Task 3 can run on the cleaned CSV without running Task 2 or requesting live APIs.

| Module | Responsibility |
|---|---|
| `nsw_evc_cleaning_config.py` | Task 2 ColumnCleaner configuration |
| `nsw_evc_data_cleaning.py` | Task 2 cleaning functions, preserving existing postcode/count safeguards |
| `data_augmentation_config.py` | Task 3 paths, thresholds, input contract, reserved augmentation interfaces |
| `task3_pipeline.py` | Read Task 2 output, match, audit, apply cleaners, validate and export |
| `data_utils/multisource_matching.py` | OCM + OSM + Charge@Large candidate selection and acceptance |
| `data_utils/multisource_audit.py` | Accepted attributes, provenance, conflicts and historical web notes |
| `data_utils/multisource_augmentation.py` | Map accepted audit fields to the existing ColumnCleaner interface |
| `data_utils/charging_match_rules.py` | Existing address scoring and metre-based distance functions |
| `data_utils/ocm_reference.py` | Existing OCM normalization and optional OCM-only baseline |
| `data_utils/task3_provenance.py` | Input fingerprints and snapshot retrieval provenance |
| `task3_osm_snapshot.py` | Independent OSM-mirror acquisition; never run implicitly by augmentation |

`main.py` loads the stages in order. `main-cleaning.py` runs Task 2 only;
`main-augmentation.py` runs Task 3 only. Python module names use underscores
(`data_augmentation_config.py`) so the team can import them normally.

`config.py` is a compatibility import layer for older scripts, including the
independent address-enrichment script. New Task 3 code does not import it.
The earlier matcher/audit filenames remain thin compatibility commands.
Future Task 3 changes belong in the augmentation modules, not the Task 2 config.

The initial integration also moved existing Task 2 configuration/functions into
the teammate's module split, retained `config.py` compatibility exports, and
added the shared `DataCleaner` guard for in-memory processing without a writer.
Thus this is not literally a change to `main.py` alone. The final Task 3
hardening changes do not further modify Task 2 or the shared cleaner classes.

The shared `DataCleaner` continues to return a DataFrame for in-memory input and
an iterator for file chunks; it now also supports validation before CSV writing.
The reserved `GET_NSW_EV_COLUMN_AUGMENTATION_CCS` interface delegates to the final
multi-source adapter. `get_ocm_details` remains available for explicit OCM-only
experiments; the final pipeline never silently falls back to that baseline.

## Completion status

Task 3 is implemented for the cleaned TfNSW DC subset. The assignment asks for at
least one new external attribute for at least 50% of DC charger locations. In the
current local run, **239 of 433 DC rows (55.20%)** pass the automatic matching
gate and have a nonempty new external attribute. The assignment threshold is
217 rows, so the final result is 22 rows above the required minimum. This is a
row-level enrichment result, not a measured ground-truth identity-accuracy rate.
As a coordinate-key sensitivity check (latitude/longitude rounded to six
decimals), the 433 rows contain 430 distinct keys and all 239 accepted rows
have distinct keys: 239/430 = 55.58%. Coordinate keys are not a verified
physical-station deduplication.

The pipeline preserves all 1,958 cleaned TfNSW rows in
`aug_data/nsw_ev_charging.csv`; only accepted DC rows receive external attributes.
The cleaned source fields are retained, and `PCODE`/`SA4_CODE26` remain text
identifiers (no `.0` suffix from CSV type inference). The Task 3 adapter is now
compatible with the updated Task 1/2 cleaners: it reuses the existing
`DataCleaner`/`ColumnCleaner` chain and keeps the new Task 1/2 outputs in the
final file.

## Compatibility with the updated Task 1/2 branch

The integration is deliberately additive rather than a replacement of the
team's interfaces:

- `ColumnCleaner` accepts an optional whole-DataFrame processor, so the
  teammate's reserved `df_processor` hook remains the extension point.
- The original `Charger_rating` column is preserved. The cleaner additionally
  writes integer count columns such as `Charger_rating.50kW` and
  `Charger_rating.350kW`; explicit multipliers such as `2x350kW` are used when
  present, otherwise `Number_of_plugs` is used. Missing or non-integer plug
  counts are not fabricated.
- `PCODE` is repaired from a postcode printed in `Station_address` when they
  disagree, while `PCODE_ORIGINAL` and `PCODE_REPAIRED_FROM_ADDRESS` preserve
  the provenance of that repair. Task 3 uses the repaired postcode for normal
  address matching but still checks the original postcode for source-data
  contradictions.
- The final audit carries the repair fields, and the Task 3 adapter maps only accepted
  Task 3 attributes into the full 1,958-row augmented table. It does not
  overwrite the source plug count, source rating, coordinates, or address.
- For external values, plug count and scalar power are populated only when
  the accepted sources provide a single consistent positive numeric value.
  Disputed or unavailable values remain blank; source-specific values and
  conflict flags remain in the audit JSON.

| Current DC result | Rows | Share of 433 |
|---|---:|---:|
| Accepted within the automatic gate, with new attributes | 239 | 55.20% |
| Accepted identities with a separate quality flag | 69 | 15.94% |
| Accepted identities with no quality flag | 170 | 39.26% |
| Candidate only; no external attributes exported | 83 | 19.17% |
| No candidate from selected DC-indicated sources | 111 | 25.64% |
| All candidates, including review-only | 322 | 74.36% |

The identity-review queue now contains only the **83 unaccepted candidates**.
The 69 accepted rows are kept in a separate quality-flags file: 38 have an
alternative candidate from another source and 31 have a numeric disagreement
between accepted sources. These warnings do not reverse a match that already
passes the automatic identity gate. Disputed scalar plug-count or power values
remain blank in the final CSV.

As a source-sensitivity check, OCM and OSM alone cover **218/433 = 50.35%**.
Charge@Large improves the final union to 239 rows but is not required for the
assignment's 50% threshold.

## Data sources and local copies

| Source | Local file / retrieval | DC-indicated accepted rows |
|---|---|---:|
| Open Charge Map (OCM) | `task3_ocm_tiled_snapshot.py`; `result_data/task3_ocm_tiled_snapshot.json` | 135 |
| OpenStreetMap-derived public mirror | `task3_osm_snapshot.py`; `result_data/task3_osm_nsw_snapshot_for_multisource.json` | 162 |
| Charge@Large | `task3_chargelarge_snapshot.py`; `result_data/task3_chargelarge_raw.json` and `result_data/task3_chargelarge_nsw.csv` | 32 |

OCM is fetched from `https://api.openchargemap.io/v3/poi/` in overlapping NSW
tiles, using `X-API-Key: $OCM_API_KEY`. Keep the key in the shell, never in
code, CSV, JSON, or Git. The checked-in OCM snapshot metadata records retrieval
at `2026-09-16T14:32:46Z`; other source summaries/snapshots are local
point-in-time copies. The OSM file is from an OSM-derived **public mirror**, not
a live Overpass response (mirror dataset endpoint:
`https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/osm-australia-charging-station/records`).
Charge@Large is fetched from
`https://chargeatlarge.app/locations`.

The generated `task3_source_manifest.json` records endpoints, local copies,
SHA-256 fingerprints, retrieval provenance, attribution and licence notes.
Historical OSM/Charge@Large retrieval times were not captured and remain
unknown; file modification dates are not substituted for API retrieval dates.
New OSM collections save UTC retrieval time in hash-bound metadata.
OSM-derived data must retain OpenStreetMap
attribution and is licensed under [ODbL](https://www.openstreetmap.org/copyright).
[OCM contributor data is CC BY 4.0](https://openchargemap.org/about), but an
OCM POI can carry a provider-specific licence. Its original provider metadata
remains in the raw snapshot; the standardized `external_data_provider` field
identifies the source family, not a replacement for that POI-level licence.
The Charge@Large endpoint did not expose an explicit
redistribution licence captured by this pipeline; verify its terms before
publishing the raw snapshot outside the assignment submission.

The selected DC subset requires an explicit CCS/CHAdeMO connector indication
or reported power of at least 40 kW. OCM closed/decommissioned records are
excluded. This is a *DC/fast indication*, not a verified electrical
classification; a high-power AC record is possible. OSM's `charge_points_count`
may count all points rather than DC connectors. Charge@Large's DC-indicated
port count is used for its standardized plug count. OCM uses `NumberOfPoints`
or a positive connection `Quantity` fallback. These quantities are not always
semantically identical, so source-specific values and quality notes remain in
the audit.

Power values are standardized to kW. Minimum/maximum power describe the
reported connections at the matched site, which may include AC connectors at
a mixed AC/DC site; do not label these as exclusively DC power. Plug counts
are connector/port counts as reported by each provider, not necessarily the
number of physical charging cabinets, parking bays, or simultaneously usable
DC outputs. Live-status values describe the saved snapshot, not current
availability when the offline pipeline runs.

## Matching policy

`data_utils/multisource_matching.py` searches candidates when either the
locally recalculated Haversine distance is **≤500 m** or structured fuzzy
address score is **≥0.85**. The 500 m value is a *candidate search radius*,
not an automatic acceptance radius; it is in metres and does not depend on an
OCM API default unit. The address scorer retains house numbers and weighs
street, full address, postcode, and house number.

A source match is automatically accepted only if its selected candidate is
within **100 m**, the postcode printed in the TfNSW address does not contradict
`PCODE`, an explicit external postcode does not contradict `PCODE`, and the
nearest two coordinate candidates are not within **20 m** of each other, and
a selected address-favoured candidate is not materially farther than the
nearest coordinate candidate. A
500 m/strong-address candidate failing one of these safeguards is marked
`review`, not discarded or used for enrichment. A source row with contradictory
address and `PCODE` is never automatically accepted, even at very small
coordinate distance. Some genuine 100–500 m matches may therefore await human
confirmation.

Per-source IDs, distance, method, score, review reason, and raw attributes are
retained. An external station may map to multiple TfNSW charger rows; one-to-one
matching is **not** enforced. The duplicate-ID report exposes this for review.
The automatic rule is not proof of physical identity, particularly in dense
charging sites. Operator/name/address and maps should be manually spot-checked.

## Attribute merging and review

`data_utils/multisource_audit.py` puts only **accepted-source** attributes in
`augmentation_attributes_by_source` / `augmented_attributes`; review-only
candidate attributes stay in the per-source diagnostic columns. The existing
`DataCleaner` / `ColumnCleaner` interface in `data_augmentation_config.py` maps the accepted
attributes into the final CSV, without overwriting TfNSW fields. Examples of
genuinely new fields include connector types, power, access/opening hours,
operational status, usage cost, and DC-indicated port count. All 239 accepted
rows have at least one such field; a provenance label or empty list alone does
not count as enrichment.

`external_number_of_plugs`, `external_power_kw_min`, and
`external_power_kw_max` are filled only when available accepted sources agree
on the positive numeric value. Otherwise the scalar stays blank; source-level
values remain in `external_attributes_json` and
`external_numeric_conflict_flags` names the disagreement. A blank means
missing or disputed, **not zero**. Identity review and accepted-row quality
review are separate fields and files. `augmentation_match_confidence` is a
rule score (1.0 accepted, 0.5 review-only, 0.0 unmatched), not a calibrated
probability of correctness.

Final augmented-column availability across the 239 accepted rows is:

| Final field | Accepted rows with a value |
|---|---:|
| Normalized connector type | 239 / 239 |
| Operator | 217 / 239 |
| Agreed external plug count | 190 / 239 |
| Charger capacity description | 164 / 239 |
| Minimum power | 135 / 239 |
| Agreed maximum power | 162 / 239 |
| Usage cost | 113 / 239 |
| Access condition | 162 / 239 |
| Network | 60 / 239 |
| Card-payment flag | 162 / 239 |
| Opening hours | 32 / 239 |
| Charge@Large live-status counts | 32 / 239 |

At least one source reports a plug count for 219 rows and a maximum power for
164 rows. The lower final scalar counts above are deliberate: a scalar is
written only when all accepted positive values agree. Raw source-specific
values remain JSON, so no information is silently discarded. Boolean payment,
free-use and reservation fields are kept as text (`True`/`False`) so missing is
not silently converted to `False`.

Saved web-review notes are reused only when they can be bound to the current
OCM ID. Non-OCM notes without an external ID may be retained as context but do
not independently screen a match. Explicit negative decisions never count as
provisionally supported. Review and screening fields must not be described as
completed manual validation.

## Reproduce from the checked-in snapshots

### Environment

Python **3.12** is the tested runtime. From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

On Windows use `.venv\Scripts\activate` instead. `requirements.txt` pins the
direct runtime dependencies for the current Task 1/2/3 pipeline; the tests use
the standard-library `unittest` runner. No API key or network access is needed
for the snapshot-based Task 3 run after installation. The cleaned TfNSW CSV,
ABS boundary ZIP, and three external snapshots must be available locally.

### Execution

Task 3 alone, using the existing Task 2 output:

```bash
python main-augmentation.py
# Equivalent: python main.py --stage augment
```

Both stages in sequence:

```bash
python main-cleaning.py
python main-augmentation.py
# Equivalent: python main.py
```

To consume a teammate's cleaned CSV and keep a separate set of output files:

```bash
python main-augmentation.py \
  --input /path/to/task2_cleaned.csv \
  --output /path/to/task3_augmented.csv \
  --results-dir /path/to/task3_results
```

The default input is `clean_src_data/nsw_ev_charging.csv`; the default final
output is `aug_data/nsw_ev_charging.csv`. Paths resolve against the repository,
so the entry points also work from another working directory. A missing local
snapshot produces an explicit error before matching starts.

Required Task 2 columns are `Station_name`, `Station_address`, `Operator`,
`Number_of_plugs`, `Charger_Type`, `Charger_rating`, `Latitude`, `Longitude`,
`LGANAME`, `PCODE`, and `Source`. All additional Task 2 columns pass through
unchanged, including SA4 fields and count-by-power columns. Percentages use the
actual DC population in that input.

If an older teammate output omits `PCODE_ORIGINAL`, the matcher can recover the
postcode audit from the local raw CSV only after checking equal row count,
coordinates and charger types. Those diagnostic fields are used internally;
they do not overwrite Task 2 fields. Without a verifiably aligned raw CSV,
original-postcode provenance is unavailable. Raw CSV is optional when the
Task 2 output already includes that provenance.

`task3_run_manifest.json` records the input path/SHA-256, all consumed snapshot
and evidence fingerprints, output path, counts, validation checks, Python
version and package versions. Input content is checked again before final
export. The final CSV is validated before it is written, and source identifiers
are checked again after CSV round-trip. Outputs cannot overwrite any configured
source, raw snapshot, retrieval metadata or historical web-review file.

### Optional live source collection

The OSM collector uses the public mirror's
[Explore API v2.1](https://help.opendatasoft.com/apis/ods-explore-v2/), filters
`meta_name_state='New South Wales'`, orders by `meta_osm_id` and retrieves up
to 100 records per page. It checks the advertised total, unique IDs, NSW scope,
coordinates and page completeness, retries transient failures, and publishes
only a fully collected JSON snapshot. Failed HTTP requests or validation do
not replace the existing snapshot. No OSM API key is needed.

```bash
# Validate the existing cache without an API call or file change.
python task3_osm_snapshot.py

# Fetch into a NEW folder, preserving the assignment benchmark.
python task3_osm_snapshot.py --refresh --output-dir /path/to/new_snapshots
```

To evaluate a new OSM snapshot, also place copies of the OCM and Charge@Large
snapshots (and available metadata) in that new folder, then run:

```bash
python main-augmentation.py \
  --snapshot-dir /path/to/new_snapshots \
  --output /path/to/new_augmented.csv \
  --results-dir /path/to/new_results
```

A live test on **23 September 2026** retrieved **509 unique NSW records in six
pages**. Compared by OSM ID and all record fields, there were zero additions,
deletions or field changes versus the frozen OSM snapshot. It was collected
in a separate validation folder; the benchmark snapshot was not replaced and
its unknown historical retrieval time was not rewritten.

The retained OCM/Charge@Large collection scripts write to `result_data`.
Use a separate repository copy or back up snapshots before running them if
the original benchmark must remain unchanged. OCM always queries the API and
requires the secret key. Charge@Large normally reuses its raw cache; its
environment flag explicitly requests a live refresh:

```bash
export OCM_API_KEY='your-real-api-key'
python task3_ocm_tiled_snapshot.py
TASK3_REFRESH_CHARGELARGE=1 python task3_chargelarge_snapshot.py
```

Live results may change. The 239/433 regression benchmark applies to the
provided snapshots; refreshed sources must be evaluated separately, not forced
to reproduce the old count by loosening the matching rules.

The pipeline regenerates matching and audit for the input supplied on each run.
The adapter also checks DC row indices, source address/postcode, original
postcode (when available), and coordinates. A stale audit is rejected when an
adapter is called separately. Source CSV values and row order must remain
unchanged, non-DC/review-only rows must not receive external attributes, and at
least half of the DC rows must receive a genuinely new attribute.

Main outputs:

- `result_data/task3_multisource_matches.csv` — selected candidate and status per source.
- `result_data/task3_multisource_summary.json` — candidate/accepted counts and rules.
- `result_data/task3_final_multisource_output/task3_multisource_final_audit.csv` — 433 DC rows with provenance, review state, and accepted attributes.
- `result_data/task3_final_multisource_output/task3_multisource_final_audit_summary.json` — coverage summary.
- `result_data/task3_final_multisource_output/task3_multisource_manual_review_queue.csv` — 83 unaccepted identity-review candidates.
- `result_data/task3_final_multisource_output/task3_multisource_accepted_quality_flags.csv` — 69 accepted rows with attribute conflicts or alternative-source warnings.
- `result_data/task3_final_multisource_output/task3_duplicate_external_id_report.csv` — repeated external IDs.
- `result_data/task3_final_multisource_output/task3_source_manifest.json` — source endpoints, local copies, attribution, and licence notes.
- `result_data/task3_final_multisource_output/task3_run_manifest.json` — input/snapshot/evidence hashes, runtime versions, output paths and run validation.
- `aug_data/nsw_ev_charging.csv` — final 1,958-row augmented data.

Task 3 is complete against the stated assignment requirement and is
reproducible from the checked-in snapshots. Manual adjudication of the 83
candidate-only rows, resolution of the 69 accepted-row quality flags, and an
independent accuracy sample would improve validation, but none of those rows is
needed to reach the reported 239 accepted enrichments. Do not describe 55.20%
as a measured identity-accuracy rate.

## Regression checks

Run `python -m unittest discover -s tests -v`. The **23 tests** cover the frozen 239/433
identities and attributes, all Task 2 fields and row order, power/plug-count
conflict handling, old teammate CSV schema, optional raw provenance, stale-audit
rejection, missing snapshots, output-path protection, shared DataCleaner modes,
and stage imports. They also cover OSM pagination/retries/failed refreshes,
snapshot fingerprints, missing boolean values, valid JSON/positive kW/integer
plug-count formats, and rejecting provenance-only JSON as enrichment. The
integration run blocks network access and Task 2 reruns.
Installation from `requirements.txt` in a fresh Python 3.12 virtual environment,
`pip check`, and all 23 tests passed on 23 September 2026.

An additional integration check generated the cleaned input using the actual
`nsw_evc_cleaning_config.py` and `nsw_evc_data_cleaning.py` from `ark-yeh` at
`6803adc`. That CSV lacks the two postcode-provenance columns. With verified
raw-row alignment, the modular Task 3 still produced 239/433 accepted rows,
83 review-only rows and 69 accepted quality flags; accepted external IDs and
attribute JSON matched the previous final result exactly. The complete
`python main.py` cleaning-to-augmentation path also reproduced those counts.

## Task 3 requirement checklist and team hand-off

| Assignment requirement | Implementation/evidence |
|---|---|
| Python query of external API(s) | Separate OCM, OSM and Charge@Large snapshot scripts |
| At least one genuinely new attribute for at least 50% of DC locations | 239/433; all 239 have normalized connector types; metadata-only matches are rejected |
| Keep local source copies for reproducibility | Frozen source JSON/CSV, source manifest and SHA-256 fingerprints |
| Document sources, linkage and processing | This README, explicit thresholds, row-level audit, separate identity and attribute review queues |
| Reusable code and execution instructions | Independent Task 3 config/entry point, pinned dependencies and regression tests |

Task 2 owns its cleaned CSV and cleaning modules. Task 3 consumes that CSV;
additional Task 2 columns pass through unchanged. Task 4 should consume
`aug_data/nsw_ev_charging.csv`, using `augmentation_match_status='accepted'`
for external facts and retaining the source IDs/provenance. Historical trial
scripts and candidate-only rows are not alternative final datasets.

This completes the implemented Task 3 pipeline and its technical hand-off.
The group's final report must still describe the methods, limitations and
individual contributions in its own words; Task 4 and overall submission
packaging are outside this Task 3 completion statement. Matching coverage is
not independently measured identity accuracy or a guarantee of a grade.
