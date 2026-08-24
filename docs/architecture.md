# Architecture

Strategy Reporting is downstream of Strategy Workspace. Runtime and Apex Research publish facts;
Reporting reads them and publishes immutable derived reports. Its single public application seam is
`render_report(subject_kind, subject_id, options) -> ReportPublication`.

Production adapters use only `strategy_workspace.WorkspaceClient`. The formal adapter maps one
terminal Nautilus leg from verified Runtime artifacts. Large normalized output is obtained through
public materialization and streamed into bounded previews; evidence indexes and all artifact content
identities are verified without loading large blobs into memory. The research adapter consumes only
`apex-research.study-report-source.v1`. Renderers consume strict report models; publishers know only
rendered bundles and Workspace publications. HTML can therefore be rebuilt without Runtime or Apex.

Nautilus owns metrics and the native tearsheet. Apex owns protocol, trial, gate, evidence and
decision semantics. Reporting owns contracts, bounded views, templates, safety checks, publication,
verification and the static portal.

Verification re-derives descriptor identity, subject, title, schema, renderer/options, source
identities and semantic lineage from the persisted model. The portal groups each strategy package
into latest/historical research, baseline/challenge/parameter-config formal runs, and Discovery
availability; it remains a derived offline view rather than a second state store.
