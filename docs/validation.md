# Validation runbook

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pytest -m "not connected"
uv run pytest -m connected
uv run mypy src
uv build
git diff --check
```

Then create a fresh Python 3.12 virtual environment outside the checkout, install the Strategy
Workspace, Quant Runtime, Apex Research and Reporting wheels, import from a non-source directory,
inspect packaged templates/assets, and run `render-run`, `render-study`, `inspect`, `verify`,
`rebuild`, and `portal build` against a real public Workspace fixture publication. Each CLI command
must produce one JSON line. Connected validation is separate and must never be represented by
fixtures.
