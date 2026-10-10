# Load test and the Performance tab (H3, H4)

Run `locustfile.py` against a NON-production cluster with `PERF_ENABLED=true`, then again with `PERF_ENABLED=false`. During the run read the Performance tab and Atlas's real-time operations view. Record: peak ops/s in the tab, Atlas's figure (differences above about 10% mean adjusting `_weight` in `perf_metrics.py` or explaining other clients), p95 request latency with and without metrics, pool in use/waiting, loop lag, unattributed share. Put the results in `docs/PERFORMANCE_AUDIT.md`, section "Measured in production".
