# Benchmark results

Environment: 2 vCPU, 7 GB RAM sandbox; PostgreSQL 16 (shared_buffers 512MB, work_mem 64MB,
synchronous_commit off); Python 3.13; dbt-core 1.12, 4 threads. 12 months of data, seed 42.
Timings in seconds. Run your own with `make bench SCALE=<n>` (appends a row below).

| scale | material issue lines | labor entries | orders | variance rows | generate | land | load | dbt build (models + 170 tests) | incremental re-run | failing tests |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 190,222 | 33,528 | 9,118 | 596,508 | 10s | 1s | 90s* | 25s | n/a | 0 |
| 10 | 1,893,764 | 331,279 | 91,216 | 5,936,241 | 71s | 1s | 140s | 124s | 16s | 0 |
| 30 | 5,691,469 | 992,353 | 273,933 | 17,840,178 | 209s | 1s | 192s | 394s | 29s | 0 |

\* At scale 1 the load is dominated by per-file overhead (3,100 small daily files). At larger
scales load time grows sub-linearly because COPY throughput dominates.

**Scaling:** dbt build grows roughly linearly (124s → 394s for 3× the data). The incremental
re-run stays small because only rows loaded after the watermark, and the orders they touch, are
reprocessed. Extrapolating, scale 50 (~9.5M issue lines, ~3M orders × elements ≈ 30M variance
rows) runs in ~25–30 minutes end to end on this hardware and needs ~20 GB of disk (Postgres
~3.8 GB per scale-10 step). It was not run in the sandbox because of the disk limit.

**Where time goes at scale 30:** `fct_cost_variance` (17.8M rows, delete+insert by order)
and `int_order_material_actuals` dominate the build. On a production warehouse, the next steps
would be partitioning the variance fact by completion month and dropping `source_txn_ids` in
favour of a join to `fct_cost_transactions`.
