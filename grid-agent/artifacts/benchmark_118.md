# Benchmark - one-shot rescue per scenario

Blind brute force: 72107 actions x ~32 ms = ~38 min (quoted, not run)

| scenario | do_nothing | scoped_brute_force | agent |
|---|---|---|---|
| crisis-at-open | FAILED | rescued (3.4s) | rescued (15.0s) |
| outage-line-111 | FAILED | FAILED (5.6s) | FAILED (33.6s) |
| outage-line-113 | FAILED | FAILED (5.6s) | FAILED (14.0s) |
| outage-line-101 | FAILED | FAILED (13.4s) | FAILED (13.7s) |
| outage-line-183 | FAILED | rescued (3.4s) | FAILED (8.3s) |
