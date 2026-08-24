# Strategy Reporting contributor contract

- This repository owns presentation/read models only. It never runs strategies or research.
- Production data access goes exclusively through the public `strategy_workspace.WorkspaceClient`.
- Never import Runtime, Apex Research, Workspace storage, SQLite, locks, or private modules.
- HTML must be deterministic, self-contained, escaped, bounded, and rebuilt only from report-model JSON.
- Missing or inconsistent evidence fails closed; never infer missing metrics or parse Markdown.
- `nautilus_trader[visualization]` stays pinned to `1.231.0`.
- Use exact-path staging; never use `git add .`, `git add -A`, or `git commit -a`.
- Before finishing run Ruff format/check, non-connected pytest, strict mypy, build, diff check, and a wheel-only smoke test.
