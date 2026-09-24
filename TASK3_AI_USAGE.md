# Task 3 contribution and AI assistance record

This is a factual working record for the group's formal AI usage report, not a declaration that the work complies with every assessment rule. Students must verify it against their drafts and the complete conversation before submission.

## Existing team work

The teammate supplied the Task 1/2 cleaning pipeline, shared ColumnCleaner/DataCleaner structure, reserved Task 3 interfaces, and the later database stage. This release integrates the latest `ark-yeh` commit `874eb5b`. Earlier integrated versions also involved AI assistance, so it would be inaccurate to describe every inherited line as independently student-authored.

## Student implementation with AI references

The student reported implementing or adapting core functions in:

- `nsw_evc_aug_config.py`: Task 2 input checks and raw-postcode alignment.
- `ocm_reference.py`: OCM normalization and NSW record loading.
- `charging_match_rules.py`: distance and address parsing/scoring.
- `multisource_matching.py`: source normalization and candidate matching.
- `multisource_audit.py`: attribute selection, review handling and coverage summaries.
- `multisource_augmentation.py`: source-index alignment and use of the reserved cleaner interface.
- `nsw_evc_aug_utils.py`: validation and pipeline flow.
- The OCM and Charge@Large collectors, and parts of the OSM request/CLI flow.

These implementations were informed by AI-provided explanations and reference code, followed by AI review, repairs and testing. Manual typing does not establish independent authorship. In particular, the P7 validation implementation closely followed an AI reference. The descriptions above reflect the student's reported process, not an independently verified line-by-line attribution.

## Substantial AI work

Earlier assistance included the scaffold, reference implementations, matching and audit design discussions, debugging, tests, data searches and report drafts. The OSM pagination core, record checks, atomic writing and provenance checks were written or substantially modified by AI.

During the 24 September integration, AI:

- Merged the latest teammate architecture and migrated the student implementation to its paths and public functions.
- Changed the broad coordinate acceptance rule to the documented 100 m / corroborated 500 m gate, added shared-ID safeguards, and retained historical web notes without promoting them to identity proof.
- Corrected mixed AC/DC power interpretation, preserved OSM object namespaces, and completed the fields required by the teammate loader.
- Added snapshot checks, quantity validation, source-preservation checks and regression tests; fixed a shared file-reader case and Python annotation compatibility.
- Ran the three real API collectors, replayed Task 2, ran the full pipeline and database validations, and checked the pinned dependency environment.
- Simplified legacy entry points and updated README files and factual report notes.

These changes are AI-authored or AI-modified work and should be disclosed as such. They should not be labelled solely as proofreading or testing. The student has not yet independently confirmed or signed off every decision introduced during this integration.

## Subsequent student-requested acceptance policy

The student explicitly chose to accept the 58 historical high/medium web-evidence candidates under a 500 m rule rather than require individual manual confirmation. AI implemented that policy in the existing audit module, added configuration and tests, reran both policy modes, and updated documentation. The result is 282 policy-accepted rows (224 strict plus 58 additional); it is not 282 manually or independently verified identities. Existing house/postcode, ambiguity and shared-ID conflicts remain visible. This policy implementation and its accompanying report wording are AI-authored assistance, not merely proofreading.

The policy implementation was initially tested with 47 tests and a temporary database using the unchanged teammate loader. No additional web verification was performed for this change.

## Subsequent architecture cleanup

At the student's request, AI consolidated duplicate evidence-alignment validation, shared scalar/source definitions, removed duplicate final validation, cached candidate address parsing and fixed unstable conflict-warning ordering. These are AI-authored refactoring changes; the earlier student/AI contribution descriptions do not imply sole student authorship of the resulting functions. AI added three regression tests and incorporated the unchanged teammate loader into the existing end-to-end test. The resulting suite has 50 passing tests. The matching policy and business attributes remain unchanged, and no new web or API evidence was collected for this cleanup.

## Preparing the formal declaration

### Final whole-pipeline submission review

At the student's request, Codex also reviewed the complete code submission, not only augmentation. It restored the SA4 table/linkage and checks in the team's loader, added the remaining external fields and source-specific JSON to DuckDB, made rebuilds transactional, hardened source downloads, removed unused cleaning-stage augmentation placeholders and added submission regression tests. It verified official downloads in temporary files and ran clean-environment and packaged-project checks. These code changes, tests and accompanying documentation are additional AI assistance and must be reflected in the group's final declaration if retained. The database changes are not solely student-authored work.

The teammate reported using Claude and Gemini for address/text regular expressions and some pipeline integration without distinguishing the two tools' individual contributions. The cleaning helper's acknowledgement reflects the reported joint regex assistance; the group must confirm any additional affected integration files. No individual model/version or invented prompt is attributed to either tool.

### Group confirmation

Identify the tools used, their purposes, the affected parts of the final submission, which suggestions/code were adopted, and how the students checked them. Retain prompts, outputs, source material and drafts for the period required by the assignment. Do not invent model/session details or claim the core is entirely original because it was retyped.

The assignment requires the essence of the submitted code/content to be the students' contribution. Accurate disclosure is necessary but does not by itself establish that a permitted-use boundary has been met. If the adopted reference code or substantial AI changes exceed the unit's allowance, the group needs the coordinator's direction; code tests cannot resolve that academic decision.
