# Strategy Reporting

Strategy Reporting is the immutable presentation/read-model layer for QuantResearch. It reads
verified facts through the public Strategy Workspace client, builds strict report models, renders
self-contained Chinese HTML, and publishes model and HTML artifacts in one immutable publication.
It does not run Quant Runtime, call Apex Research, parse Markdown, or calculate engine metrics.

Python API:

```python
from pathlib import Path
from strategy_reporting import ReportOptions, render_report

publication = render_report(
    "formal-run",
    "run_123",
    ReportOptions(workspace_root=Path(r"D:\WILL\STOCK\QuantResearch\runtime\workspace")),
)
```

CLI commands always emit exactly one JSON object on stdout:

```powershell
strategy-reporting --workspace D:\path\to\workspace render-run --run-id run_123
strategy-reporting --workspace D:\path\to\workspace render-study --study-id study_123
strategy-reporting --workspace D:\path\to\workspace inspect --report-id report_<sha256>
strategy-reporting --workspace D:\path\to\workspace verify --report-id report_<sha256>
strategy-reporting --workspace D:\path\to\workspace rebuild --report-id report_<sha256>
strategy-reporting --workspace D:\path\to\workspace portal build --output D:\reports
```

`--workspace` takes priority over `STRATEGY_WORKSPACE_ROOT`, then the public Workspace default.
`rebuild` compares deterministic bytes and never republishes by default. Portal output is a static,
offline derived view and never becomes state.

See [architecture](docs/architecture.md), [contracts](docs/contracts.md),
[security](docs/security.md), and [validation](docs/validation.md).
