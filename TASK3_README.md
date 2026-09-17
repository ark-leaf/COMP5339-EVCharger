# Task 3 — external EV charger enrichment

## Completion status

Task 3 is implemented for the cleaned TfNSW DC subset. The assignment asks for at
least one new external attribute for at least 50% of DC charger locations. In the
current local run, **239 of 433 DC rows (55.20%)** pass the automatic matching
gate and have a nonempty new external attribute. This is *row-level provisional
coverage*, not a measured match-accuracy or ground-truth validation rate.
As a coordinate-key sensitivity check (latitude/longitude rounded to six
decimals), the 433 rows contain 430 distinct keys and all 239 accepted rows
have distinct keys: 239/430 = 55.58%. Coordinate keys are not a verified
physical-station deduplication.

The pipeline preserves all 1,958 cleaned TfNSW rows in
`aug_data/nsw_ev_charging.csv`; only accepted DC rows receive external attributes.
The cleaned source fields are retained, and `PCODE`/`SA4_CODE26` remain text
identifiers (no `.0` suffix from CSV type inference). Existing Task 1/2 cleaning
logic was not changed for this work.

| Current DC result | Rows | Share of 433 |
|---|---:|---:|
| Accepted within the automatic gate, with new attributes | 239 | 55.20% |
| Of those, no additional review flag | 170 | 39.26% |
| Of those, review flagged but accepted-source attributes retained | 69 | 15.94% |
| Candidate only; no external attributes exported | 83 | 19.17% |
| No candidate from selected DC-indicated sources | 111 | 25.64% |
| All candidates, including review-only | 322 | 74.36% |

The review queue has 152 rows: the 83 review-only candidates plus the 69
accepted rows with another source requiring review or a numeric disagreement.
There are 31 rows with a numeric conflict between accepted sources. Historical
evidence provisionally supports 83 rows after binding OCM notes to the current
OCM ID; this is **not** an independent identity-verification result.

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
missing or disputed, **not zero**. The 152-row review queue also includes
accepted rows with unresolved source conflicts or a separate review candidate.
Such rows can have accepted-source attributes but should be disclosed as
review-flagged. `augmentation_match_confidence` is a rule score (1.0 or 0.5),
not a calibrated probability of correctness.

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
- `result_data/task3_final_multisource_output/task3_multisource_manual_review_queue.csv` — all 152 rows needing review.
- `result_data/task3_final_multisource_output/task3_duplicate_external_id_report.csv` — repeated external IDs.
- `aug_data/nsw_ev_charging.csv` — final 1,958-row augmented data.

Remaining work before claiming validated accuracy: manually adjudicate the
review queue, sample the automatically accepted matches against authoritative
station identities, resolve source count/power disagreements, and record any
decisions. The current implementation meets the assignment's **provisional
row-level enrichment threshold**, not an independently verified 50% identity
accuracy threshold.
