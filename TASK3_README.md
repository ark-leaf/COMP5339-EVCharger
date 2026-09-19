# Task 3 — external EV charger enrichment

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
- The final audit carries the repair fields, and `main.py` maps only accepted
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
| OpenStreetMap-derived public mirror | `result_data/task3_osm_nsw_snapshot_for_multisource.json` | 162 |
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
attribution and licence notes. OSM-derived data must retain OpenStreetMap
attribution and is licensed under [ODbL](https://www.openstreetmap.org/copyright).
[OCM contributor data is CC BY 4.0](https://openchargemap.org/about), but an
OCM POI can carry a provider-specific licence, so the provider field remains
in the output. The Charge@Large endpoint did not expose an explicit
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

## Matching policy

`task3_multisource_supplement_trial.py` searches candidates when either the
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

`task3_final_multisource_audit.py` puts only **accepted-source** attributes in
`augmentation_attributes_by_source` / `augmented_attributes`; review-only
candidate attributes stay in the per-source diagnostic columns. The existing
`DataCleaner` / `ColumnCleaner` interface in `config.py` maps the accepted
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

Run from the repository root, with the committed cleaned TfNSW file and source
snapshots present:

```bash
python task3_multisource_supplement_trial.py
python task3_final_multisource_audit.py
python main.py
```

Only when refreshing external data, run the snapshot scripts first (network
access required). OCM requires the secret key:

```bash
export OCM_API_KEY='your-real-api-key'
python task3_ocm_tiled_snapshot.py
python task3_chargelarge_snapshot.py
```

The audit adapter checks row indices, source address/postcode, and coordinates
against the cleaned input. If the cleaned input changes, rerun the matching and
audit before `main.py`; stale enrichment will fail instead of silently joining
to a different TfNSW row. `main.py` retains the older OCM-only adapter as a
fallback if the multi-source audit file is absent; that fallback is **not** the
result reported here.

Main outputs:

- `result_data/task3_multisource_matches.csv` — selected candidate and status per source.
- `result_data/task3_multisource_summary.json` — candidate/accepted counts and rules.
- `result_data/task3_final_multisource_output/task3_multisource_final_audit.csv` — 433 DC rows with provenance, review state, and accepted attributes.
- `result_data/task3_final_multisource_output/task3_multisource_final_audit_summary.json` — coverage summary.
- `result_data/task3_final_multisource_output/task3_multisource_manual_review_queue.csv` — 83 unaccepted identity-review candidates.
- `result_data/task3_final_multisource_output/task3_multisource_accepted_quality_flags.csv` — 69 accepted rows with attribute conflicts or alternative-source warnings.
- `result_data/task3_final_multisource_output/task3_duplicate_external_id_report.csv` — repeated external IDs.
- `result_data/task3_final_multisource_output/task3_source_manifest.json` — source endpoints, local copies, attribution, and licence notes.
- `aug_data/nsw_ev_charging.csv` — final 1,958-row augmented data.

Task 3 is complete against the stated assignment requirement and is
reproducible from the checked-in snapshots. Manual adjudication of the 83
candidate-only rows, resolution of the 69 accepted-row quality flags, and an
independent accuracy sample would improve validation, but none of those rows is
needed to reach the reported 239 accepted enrichments. Do not describe 55.20%
as a measured identity-accuracy rate.
