# Task 3 report facts — historical web evidence acceptance policy

Use these checked facts when revising the student-authored Task 3 report. The current rule accepts 282/433 rows (65.13%): 224 strict matches plus 58 historical-web-rule matches. The latter are not manually verified. These facts supersede the older 239/433 and 314/433 figures; 224/433 remains the reproducible strict baseline. This is not a completed or signed group report.

## Aim and inputs

- Task 3 consumes the latest teammate Task 2 CSV: 1,958 rows, 54 columns, 433 DC rows.
- The original TfNSW data includes operator, charger rating and plug count. These fields alone cannot establish a genuinely new attribute.
- Three public API sources were queried programmatically: OCM, an OSM-derived Opendatasoft mirror, and Charge@Large. The OSM source was not queried through Overpass.
- Actual API collection was repeated on 24 September 2026; raw responses, retrieval times and SHA-256 checksums are bundled. Historical API logs and snapshots are retained separately.

## Method to explain in the student's own words

Explain both stages. The strict matcher accepts within 100 m without blocking conflicts/ambiguity, or within 500 m with a corroborating numbered address. The audit then accepts an additional class of strict-review rows: an attached high/medium historical web note with a URL and no negative decision, plus a current DC candidate within 500 m with a genuinely new attribute. Select one nearest eligible candidate per row, using OCM/OSM/Charge@Large order for exact ties. Do not hardcode the 58 records or claim a 65.13% accuracy rate.

The historical notes are bound to the current source address; OCM notes also require an unchanged OCM ID. Supplemental notes may not identify the selected external record. Under the student-requested rule, strict house/postcode, ambiguity and shared-ID conflicts remain warnings rather than vetoes. Explain that this increases coverage with greater identity uncertainty. Counts are not summed across rows sharing an external site. Address-only candidates outside 500 m and low-evidence rows are not promoted.

Describe how the student's Task 3 functions connect to the teammate's stage entry and ColumnCleaner/DataCleaner interfaces. Task 3 preserves the Task 2 input and adds 19 columns; both reserved augmentation factory names point to the same implementation.

## Results to report

| Measure | Current result |
| --- | ---: |
| Accepted with at least one new attribute | 282/433 = 65.13% |
| Strict baseline | 224/433 = 51.73% |
| Additional historical-web-rule rows | 58 |
| Required row count for the 50% target | 217 |
| Review-only candidates | 37 |
| Unmatched DC rows | 114 |
| Accepted rows with connector types | 282 |
| Accepted rows with maximum kW | 177 |
| Accepted rows with minimum kW | 176 |
| Accepted rows with explicit DC port counts | 34 |
| Accepted rows with cost text | 121 |
| Accepted rows with opening hours | 32 |
| Accepted rows retaining quality warnings | 164 |
| Historical search context attached | 205 |
| Distinct accepted coordinate pairs | 282 |
| Distinct DC coordinate pairs | 430 |

OCM/OSM/Charge@Large source contributions are 148/176/34 accepted row links, with overlap. OCM+OSM covers 255 rows; Charge@Large adds 27 more. The 58 additional rows select OCM 22 times, OSM 29 times and Charge@Large 7 times. Report the union, not the sum of source counts.

The regression suite includes a strict-only replay returning 224 rows and the team's staged loader. Final submission verification reruns the entire cleaning, augmentation and database pipeline, not only Task 3. DuckDB contains 282 augmentation rows, 435 atomic connector records and 28 referenced SA4 polygons. Primary-key duplicates, foreign-key orphans, and review/unmatched leakage were zero. Remaining external fields and source-specific JSON are preserved in the database. See `SUBMISSION_CHECKS.md` for final test results and packaging evidence; tests do not independently verify station identity.

The architecture cleanup did not change the acceptance criteria, selected candidates or enhanced business attributes. It removed duplicated validation, centralized evidence alignment and source definitions, reused parsed candidate addresses, and fixed nondeterministic conflict-warning ordering. No additional business modules were created.

## Limitations to retain

Coverage is not accuracy. The 164 warning-bearing accepted rows include all 58 newly accepted rows. There are 35 shared-external-ID groups and a separate 37-row review queue. These are not measured error counts. The high/medium web labels are old evidence-quality labels, not calibrated identity confidence. Some accepted rows retain substantial address or coordinate conflicts; describe this limitation rather than calling all matches high confidence.

The APIs and mirrors differ in coverage and update frequency. Charge@Large's saved query is bounded to 0–350 kW. An API retrieval time does not show when each station was last updated. Availability is a snapshot, not a prediction or a current guarantee.

Power is normalized to kW with its scope retained. OCM and Charge@Large use DC connection/port ratings; OSM supplies a station maximum only. Conflicting numeric claims stay in the audit and are not exported as one certain scalar. OCM/OSM point counts are not automatically converted into physical plug or bay counts.

Historical search snippets and confidence labels now contribute to the documented acceptance heuristic, not independent identity verification. Do not describe the output as 282 manually or web-verified stations. No new web search or manual adjudication was performed for the 58-row promotion.

## Evidence and acknowledgements

Use the current run/source manifests, final audit and `task3_web_rule_accepted.csv` under `data/result_data/task3_final_multisource_output/`. The matching CSV/summary retain the strict 224-row stage. The earlier `task3_integration_verification.json` is historical baseline evidence; its code hashes and 43-test result do not certify this later policy. Cite the API/dataset links in `TASK3_README.md` and retain source-provider attribution.

Suggested English methodology wording to adapt: After strict matching, the pipeline accepts an additional class of records with a current DC candidate within 500 m and historical web evidence labelled high or medium. It selects one nearest eligible candidate per source row and preserves the original conflict reasons as quality warnings. This rule adds 58 rows to the strict baseline of 224, yielding 282/433 (65.13%) policy coverage. These additional associations have not been independently verified as the same physical station.

中文说明：严格匹配后，程序将“存在 500m 内直流候选，并有历史高／中等级网页证据”的部分待审核记录按规则接受。每行仅选择一个最近的合格候选，保留原冲突警告。新增 58 行，与基线 224 行合计 282/433＝65.13%。这是规则接受覆盖率，不是 58 条都经人工确认，也不是匹配准确率。

Complete the formal Generative AI and Automated Writing Tools Usage Report using `TASK3_AI_USAGE.md`, the actual conversation history, and the group's contribution records. The student's final report should explain decisions they understand and endorse; this file is a factual aid.
