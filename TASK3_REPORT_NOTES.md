# Task 3 report facts — 24 September 2026

Use these checked facts when revising the student-authored Task 3 report. They supersede the older report draft's 239/433 and exploratory 314/433 figures. They are not a completed or signed group report.

## Aim and inputs

- Task 3 consumes the latest teammate Task 2 CSV: 1,958 rows, 54 columns, 433 DC rows.
- The original TfNSW data includes operator, charger rating and plug count. These fields alone cannot establish a genuinely new attribute.
- Three public API sources were queried programmatically: OCM, an OSM-derived Opendatasoft mirror, and Charge@Large. The OSM source was not queried through Overpass.
- Actual API collection was repeated on 24 September 2026; raw responses, retrieval times and SHA-256 checksums are bundled. Historical API logs and snapshots are retained separately.

## Method to explain in the student's own words

Discuss why the sources complement each other, how their records are normalized, why DC connector evidence is required, and how source identity is checked before exporting attributes. Explain the distinction between a 500 m candidate search and the stricter automatic gate: within 100 m without explicit conflicts/ambiguity, or within 500 m with a corroborating numbered address. Address-only and unresolved cases remain review-only.

Explain the shared-ID safeguard: several TfNSW records can legitimately refer to one site, but one external object cannot automatically enrich unrelated nearby sites. Record-level attributes retain their source and are not summed into counts of physical stations.

Describe how the student's Task 3 functions connect to the teammate's stage entry and ColumnCleaner/DataCleaner interfaces. Task 3 preserves the Task 2 input and adds 19 columns; both reserved augmentation factory names point to the same implementation.

## Results to report

| Measure | Current result |
| --- | ---: |
| Accepted with at least one new attribute | 224/433 = 51.73% |
| Required row count for the 50% target | 217 |
| Review-only candidates | 95 |
| Unmatched DC rows | 114 |
| Accepted rows with connector types | 224 |
| Accepted rows with maximum kW | 148 |
| Accepted rows with minimum kW | 147 |
| Accepted rows with explicit DC port counts | 27 |
| Accepted rows with cost text | 103 |
| Accepted rows with opening hours | 29 |
| Accepted rows retaining quality warnings | 96 |
| Historical search context attached | 205 |
| Distinct accepted coordinate pairs | 224 |
| Distinct DC coordinate pairs | 430 |

OCM/OSM/Charge@Large source contributions are 126/147/27 accepted row links, with overlap. OCM+OSM covers 204 rows; Charge@Large adds 20 more. Report the union, not the sum of source counts.

The full pipeline loads 224 augmentation rows and 345 atomic connector records into the teammate's schema. Primary-key duplicates, foreign-key orphans, and review/unmatched leakage are zero. This demonstrates the handoff; it is not an independent certification of Task 4's entire rubric.

## Limitations to retain

Coverage is not accuracy. Automatic matches still rely on spatial/address assumptions, and no ground-truth precision estimate has been established. Describe the remaining 96 warning-bearing accepted rows and the separate 95-row review queue without calling either count an error count.

The APIs and mirrors differ in coverage and update frequency. Charge@Large's saved query is bounded to 0–350 kW. An API retrieval time does not show when each station was last updated. Availability is a snapshot, not a prediction or a current guarantee.

Power is normalized to kW with its scope retained. OCM and Charge@Large use DC connection/port ratings; OSM supplies a station maximum only. Conflicting numeric claims stay in the audit and are not exported as one certain scalar. OCM/OSM point counts are not automatically converted into physical plug or bay counts.

Historical search snippets and confidence labels provide context, not independent verification of all accepted identities. Do not describe the output as 224 manually or web-verified stations.

## Evidence and acknowledgements

Use the run/source manifests and final audit under `data/result_data/task3_final_multisource_output/` as the numerical source. Cite the API/dataset links in `TASK3_README.md` and retain source-provider attribution.

Complete the formal Generative AI and Automated Writing Tools Usage Report using `TASK3_AI_USAGE.md`, the actual conversation history, and the group's contribution records. The student's final report should explain decisions they understand and endorse; this file is a factual aid.
