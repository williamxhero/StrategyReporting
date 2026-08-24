# Contracts

- Models reject unknown top-level fields and non-finite numbers.
- `FormalRunReport` is `strategy-reporting.formal-run-report.v1`.
- `ResearchStudyReport` is `strategy-reporting.research-study-report.v1`.
- Persisted publication payload is `strategy-reporting.report-descriptor.v1`.
- Returned envelope is `strategy-reporting.report-envelope.v1`; artifacts and lineage are assembled
  from the publication top level and are never duplicated in the descriptor.
- `report_id` hashes canonical subject/source identities, model SHA-256, renderer version and
  normalized options. Wall-clock values and local paths are excluded.
- The report-model JSON artifact is the sole rebuild input. HTML and native tearsheet are derived.
- Verify/rebuild bind every descriptor cross-field and lineage edge back to that persisted model;
  a self-consistent forged report ID is insufficient.
- Formal artifact names are selected exactly under `formal/<formal_id>/`; missing and duplicate names
  fail closed. The evidence index, normalized schema/framework/version, native-statistics mirror,
  attempt and Runtime identity/hash mirrors are exact.
- Large normalized order/fill/position/event arrays must remain arrays and are streamed into capped
  previews with exact totals and omitted counts. Research never parses Markdown.
- Apex source identity, embedded source ordering, gate/decision identities, evidence closure and
  list hard caps mirror `apex-research.study-report-source.v1` exactly.
