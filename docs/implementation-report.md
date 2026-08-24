# Strategy Reporting implementation and release audit

Status date: 2026-08-24. This document maps the canonical
`docs/strategy-reporting-development-plan.md` in the QuantResearch root to executable evidence.
`completed`, `not-applicable`, and `non-blocking connected` are intentionally distinct.

## Upstream compatibility baseline

| Owner | Commit | Status and evidence |
|---|---|---|
| Strategy Workspace | `b2250fc92fef07539f8233ddf150f9cb7dc3d6cd` | No Reporting-specific API was added. Public get/list/read/materialize/verify/publish covers the layer. The final public contract preserves per-use publication presentation metadata while URI read/verify/materialize may return a canonical descriptor; Reporting compares immutable content identity and keeps exact publication name/hash/index checks. Workspace evidence: 28 tests plus 5 fresh-wheel alias tests passed in the owning repository. |
| Quant Runtime | `13ab226312f9033a179608cc8842f321d151205c` | `quant-runtime.nautilus-reporting-input.v1`, exact artifact path and schema, public Nautilus extraction before dispose. Targeted Runtime tests: 14 passed. Reporting connected compatibility test consumes the pushed extractor output as an artifact after engine state is absent. |
| Apex Research | `b81651a2abbe7d562b0fbf15f1c0c169863e9174` | Strict `apex-research.study-report-source.v1` with record ID equal to source ID and Markdown compatibility. Targeted Apex tests: 31 passed. Reporting generated a real source publication using this commit and mapped it without private state. |

No Strategy Workspace private module, SQLite database, lock, staging directory, artifact object path,
Runtime package, or Apex package is imported by production Reporting code. `tests/test_boundaries.py`
locks this boundary.

## Canonical plan 21.x

### 21.1 Strategy Workspace

- completed: public read, artifact verification/read/materialization, immutable publication, list and
  idempotency behavior were exercised through the real `WorkspaceClient` round-trip.
- completed: model/HTML/native tearsheet are sent in one `publish_record(..., artifacts=...)` call;
  returned top-level artifact refs are used as truth.
- completed: Reporting neither needs nor introduces `publish_artifact`.
- not-applicable: no Reporting-specific Workspace schema/API commit was needed.
- completed upstream at `b2250fc92fef07539f8233ddf150f9cb7dc3d6cd`: same-content
  aliases retain their per-use name/media/schema/role in publications while URI operations return
  a canonical descriptor. Reporting's real Workspace round-trip locks this public behavior.

### 21.2 Quant Runtime

- completed upstream at `13ab226`: core `nautilus_trader==1.231.0` stays unchanged; Runtime does not
  add visualization dependencies.
- completed upstream: strict reporting-input schema includes native PnL/return/general stats,
  ordered finite portfolio returns, run/account info, extraction interfaces, availability and
  unavailable reasons; both equity and futures paths publish it before dispose.
- completed evidence: 14 targeted tests passed, including public API signature, empty returns,
  non-finite values, duplicate timestamps, equity native output and futures native output.
- completed in Reporting: the exact artifact name, ArtifactRef record schema, exact root fields,
  evidence-index sizes/hashes and engine version are fail-closed.

### 21.3 Apex Research

- completed upstream at `b81651a`: strict source identity, ordered trials, gates, evidence, decision,
  availability, record refs and Workspace run refs; Markdown continues unchanged.
- completed evidence: 31 targeted source/study/boundary tests passed.
- completed in Reporting: local strict mirror verifies operator enums, package schema, gate uniqueness,
  canonical protocol/gate/decision/source identities, trial/source order, evidence and run references.
- completed: no Markdown parsing, private state, Runtime bytes or Reporting dependency exists.

### 21.4 Strategy Reporting

All listed implementation items are completed: independent Python 3.12 repository; exact Nautilus
visualization pin; direct compatible pandas and streaming-JSON dependencies; canonical JSON/hash; strict envelope/formal/
research/options contracts; public Workspace seam; formal and Apex adapters; renderer registry;
Chinese formal/research HTML; official offline tearsheet; model JSON as sole rebuild input; deterministic
descriptor/ID; single-call publish; first publication time mapping; idempotency/race reload; inspect,
verify and rebuild; strict JSON CLI and exit codes; static portal; safe materialization; escaping/CSP/
remote-resource validation; row/byte caps; frozen/malicious fixtures; packaged templates/assets; real
Workspace round-trip; upstream connected contract tests; wheel and fresh-install gates. Large Runtime
output is streamed with bounded previews, while rebuild re-derives descriptor cross-fields and
lineage from the persisted model without re-entering Runtime or Apex.

### 21.5 ApexTrade read-only migration audit

Read-only references:

- `docs/14_output_file_contract.md`: HTML is a derived view of structured results.
- `docs/designs/offline_structured_analysis_risk_gate_design.md`: offline rebuild and risk presentation.
- `apps/backtest-tool/src/cli/report/regeneration_support.rs`: rebuild workflow idea only.
- `apps/backtest-tool/src/cli/report/html.rs` and `html/cards.rs`: Chinese information hierarchy and
  bounded cards only.
- `apps/backtest-tool/src/cli/report/html/tests.rs` and structured-output tests: escaping, malicious
  payload and invalid-input test ideas only.

The boundary scan confirms none of these forbidden implementation families entered production:
`AnalysisBundle`, `PerformanceMetrics`, `calculate_performance_metrics`, legacy/output-directory/log
parsers, `apex_backtest` engine types, margin-log parsing, result-directory analysis or legacy markers.
No ApexTrade file was modified. Reuse is limited to presentation, security and test ideas.

## Acceptance matrix (plan section 22)

| IDs | Status | Evidence |
|---|---|---|
| A01-A06 | completed | Strict Pydantic contracts, canonical/non-finite/path tests, deterministic ID, renderer-version and wall-clock exclusion tests. |
| A07-A11 | completed | Single/multi-leg tests, exact Runtime v1 mapping, official pinned API signature, artifact-only connected acceptance and native tearsheet rebuild. |
| A12-A18 | completed | Empty execution, no positions, empty/short returns, missing/duplicate/tampered artifacts, unordered/duplicate/non-finite rejection. |
| A19-A24 | completed | Real Apex v1 mapping, no Discovery, no Apex, no Markdown fallback, formal-link state and upstream Markdown tests. |
| A25-A27 | completed | Malicious fixtures, no payload-driven `innerHTML`, CSP/remote-resource scan and real headless Edge load with zero HTTP(S) requests. |
| A28-A33 | completed | Real Workspace single publication, immutable/idempotent/race-winner behavior, descriptor/model and semantic-lineage recomputation, poison-spy no-rerun rebuild, one-line CLI JSON and exit contract. |
| A34-A35 | completed | Static latest/history research, baseline/challenge/parameter-config formal and Discovery availability grouping, filters, empty state, safe paths and 10,000-record fail-closed cap. |
| A36-A39 | completed | Wheel resources, wheel-only validation, boundary scan and ApexTrade audit. |
| A40 | non-blocking connected | Real local Workspace fixture publications and pushed upstream contract integrations pass. A historical MarketHub-backed production sample is not run by this offline implementation task and must not be represented by fixture evidence. |

## Plan section 28 deliverables

All Reporting deliverables, Runtime reporting inputs, Apex structured source and Markdown compatibility
are completed. Strategy Workspace remains a public dependency rather than a modified Reporting-owned
component. PDF/Excel/server/cloud output remain intentional non-goals.

Example deterministic fixture publications from a real `WorkspaceClient` round-trip:

- Formal report: `report_3329a89f9afe62e8179882d6f9366c6d2f74de9081bc1c881ee4e541213a774d`
  - model: `workspace-artifact://sha256/cfc40752e07952685a8e31f408f17e029a7efbe916c6ae9dc5fb3b4c126d2e46`
  - HTML: `workspace-artifact://sha256/0b5c72b05167a1464fb9ccaff2061b44ec5df664583ce178e392396696f8d414`
  - native tearsheet: `workspace-artifact://sha256/b957b4ee0eec0b101a91e2d316a3f2e3a13a14c010ecd5d42e02c88dfd8a0dd2`
- Research report: `report_f367bd75625f06f971c706994cfc41fd3ba04cf20f713678c208fc5fa8ebe205`
  - model: `workspace-artifact://sha256/600d0f0597893159f6b363def8e060a59a0c8b7460982d38ad33890844a083c0`
  - HTML: `workspace-artifact://sha256/4fec954144224858a9ebf79148a407d153031b1c2af0059fd87d4d8e1d506a72`

These are explicitly fixture identities, not MarketHub-connected performance evidence.

## Reporting verification

- Ruff format/check: passed.
- mypy strict over `src/strategy_reporting`: passed.
- pytest offline: 91 passed, including real headless Edge zero-network validation and the final
  Workspace same-content alias/materialization semantics.
- pytest upstream compatibility: 2 passed against pushed Runtime/Apex source checkouts.
- real public Workspace publication round-trip: passed.
- wheel build and packaged template/static-resource inspection: passed.
- fresh four-wheel install from a non-source directory: passed. Installed only the Workspace,
  Runtime, Apex and Reporting distributions as project inputs, then used their resolved public
  dependencies.
- wheel-only CLI acceptance: `render-run`, `render-study`, `inspect`, `verify`, `rebuild`, and
  `portal build` each returned exactly one successful JSON line; portal contained both reports.

## Release evidence

Fresh validation root:
`C:\Users\will\AppData\Local\Temp\strategy-reporting-postcommit-2cbde0d567844212b9648d2075ebe28a`.
Its Workspace and portal are retained for audit during this release session.

Wheel SHA-256 values used by that isolated Python 3.12 environment:

- Strategy Workspace: `07fa57564f8e555c753dfc880d9104cc4d2ca101ef38e64934594a3ed75e3b5f`
- Quant Runtime: `31a20467b582d81f7e35fc6d00e28dcafcb80403be2384ca2d4cfdc94a590560`
- Apex Research: `e090f641e2407d52fdb75e6484a58b4f94901c3db0672cb623d8654ab3a81c87`
- Strategy Reporting: `f78bb60d955dddcc017f04a485bc5ad0a73b0a6d083f858ae747a106a450374b`

The three upstream repository HEADs above were also checked against their live `origin/main` refs.
Strategy Reporting was reviewed and committed in three coherent changes (`8f005e4`, `164275a`,
`2b59828`) before this release-evidence update, then rebuilt and installed from the resulting wheel.
Final repository synchronization is recorded in the handoff because a commit cannot truthfully cite
its own final SHA. No fixture result in this document is represented as MarketHub-connected
performance evidence.
