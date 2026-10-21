"""Pipeline optimisation study: measurement, alternative strategies, sweeps.

The package answers one question for each expensive operation in the pipeline:
of the ways it could be implemented or laid out on disk, which is fastest, is
the fast one still correct, and at what volume does the choice start to matter.

Layers, matching the convention used elsewhere in ``src/ecom``:

``harness``
    Timing, memory and correctness checking. Knows nothing about the pipeline.
``workloads``
    Pure alternative implementations of the pipeline's hot operations.
``fragmentation``
    Physical storage layouts and the queries that discriminate between them.
``studies``
    Sweeps: selectivity, shard count, volume scaling, materialisation.
``run_bench``
    The only module that performs I/O; writes ``reports/benchmarks/results.json``.
``report``
    Renders that JSON as Markdown and figures.
"""

from ecom.bench.harness import Measurement, WorkloadResult, run_workload

__all__ = ["Measurement", "WorkloadResult", "run_workload"]
