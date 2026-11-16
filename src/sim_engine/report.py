import html
import json
from pathlib import Path

from .contracts import Outcome
from .evaluation import summarize


def render(outcomes: list[Outcome], destination: Path, gate_result: dict | None = None) -> None:
    summary = summarize(outcomes)
    escape = lambda value: html.escape(str(value), quote=True)
    rows = []
    for row in outcomes:
        failures = ", ".join(c.name for c in row.checks if not c.passed)
        rows.append(f"<tr><td>{escape(row.scenario_id)}</td><td>{escape(row.variant)}</td>"
                    f"<td>{escape(row.cohort)}</td><td>{'PASS' if row.success else 'FAIL'}</td>"
                    f"<td>{escape(failures or row.error or '')}</td><td>{row.latency_ms:.1f}</td></tr>")
    document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent migration laboratory</title>
<style>body{font:16px system-ui;background:#101820;color:#e6edf3;margin:3vw}
h1{color:#9cdb5a}pre{white-space:pre-wrap;background:#1e2c38;padding:1rem}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.7rem;border-bottom:1px solid #415364}
input{padding:.6rem;width:26rem;max-width:90%;margin:1rem 0}</style>
<h1>Agent migration laboratory</h1>
<p>Fictional users and systems. Ratings are deterministic proxies, not human feedback.
This report does not authorize production rollout.</p>
<h2>Comparison</h2><pre>SUMMARY</pre><h2>Release evidence</h2><pre>GATE</pre>
<h2>Episodes</h2><input id="filter" placeholder="Filter by cohort, scenario, or failure">
<table><thead><tr><th>Scenario</th><th>Variant</th><th>Cohort</th><th>Outcome</th><th>Failures</th><th>ms</th></tr></thead>
<tbody>ROWS</tbody></table><script>
document.getElementById('filter').addEventListener('input',e=>{
for(const row of document.querySelectorAll('tbody tr'))row.hidden=!row.textContent.toLowerCase().includes(e.target.value.toLowerCase());
});</script></html>"""
    document = document.replace("SUMMARY", escape(json.dumps(summary, indent=2)))
    document = document.replace("GATE", escape(json.dumps(gate_result or {}, indent=2)))
    document = document.replace("ROWS", "".join(rows))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
