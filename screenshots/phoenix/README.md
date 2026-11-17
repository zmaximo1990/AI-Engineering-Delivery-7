# Screenshots

Evidence from the 5-concurrent load test (`python scripts/load_test.py -n 5`).

| File | What it shows |
|------|----------------|
| `phoenix_ui.png` | Phoenix projects list (10 traces after the load run) |
| `traces.png` | Phoenix project `default`: root LangGraph spans |
| `latency_p95.png` | Dashboard header with Latency P50 / P99 for that run |
| `cost_per_run.png` | Dashboard header with Total Cost (token accounting) |
| `load_test_client_metrics.txt` | Client-side wall times for the same run |
