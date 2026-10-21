"""Measurement primitives for the optimisation study.

Nothing in this module knows what is being measured. It supplies the three
things every credible benchmark needs and the project previously did by hand:

1. **Repeated trials with a discarded warm-up.** A single timing on a laptop is
   dominated by page-cache state and CPU frequency scaling. We report the median
   of several trials because the median is unaffected by one slow outlier,
   and we keep min and max so the spread is visible rather than hidden.
2. **Peak memory measured separately from time.** ``tracemalloc`` roughly
   doubles the cost of allocation-heavy code, so timing it would report the
   cost of the instrument. Timing trials run clean; one extra traced run
   supplies the memory number.
3. **A correctness check against the baseline.** An optimisation that returns a
   different answer is not an optimisation. Every strategy is compared to the
   first one registered, and a mismatch is recorded in the result rather than
   raised, so the report can show *that* a fast-but-wrong strategy exists.

All timings are therefore warm-cache, single-machine, single-process numbers.
They are honest about relative cost between strategies, which is the question
the study asks; they are not predictions of cluster behaviour.
"""

from __future__ import annotations

import gc
import logging
import time
import tracemalloc
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from statistics import median
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_TRIALS = 5
"""Odd number so the median is an observed value, not an average of two."""

WARMUP_RUNS = 1
"""One discarded run per strategy: it pays the import, page-cache and JIT costs
that would otherwise all land on the first measured trial."""


@dataclass
class Measurement:
    """Timing and memory for one strategy on one workload.

    Attributes:
        name: Strategy name as it appears in the report.
        seconds_median: Median wall time across trials, the headline figure.
        seconds_min: Fastest trial, the best case the machine achieved.
        seconds_max: Slowest trial; a wide gap to min means a noisy result.
        peak_mib: Peak Python heap during one separately traced run.
        rows_out: Rows the strategy produced, for the correctness column.
        matches_baseline: None for the baseline itself, else whether the output
            equalled the baseline's.
        note: Free-text caveat shown in the report, e.g. why a result is wrong.
        failed: Error text if the strategy raised; it is reported, not fatal,
            because a missing optional dependency should not void the study.
    """

    name: str
    seconds_median: float = 0.0
    seconds_min: float = 0.0
    seconds_max: float = 0.0
    peak_mib: float = 0.0
    rows_out: int = 0
    matches_baseline: bool | None = None
    note: str = ""
    failed: str = ""

    @property
    def ok(self) -> bool:
        """True if the strategy ran and agreed with the baseline."""
        return not self.failed and self.matches_baseline is not False


@dataclass
class WorkloadResult:
    """Every strategy's measurement for one workload, plus its context.

    Attributes:
        workload: Human-readable name of the operation under test.
        concept: The lecture concept this workload exercises, carried into the
            report so each number is traceable to the syllabus.
        unit: What one row of input means, used to compute throughput.
        input_rows: Size of the input, the throughput denominator.
        measurements: One entry per strategy, in registration order.
    """

    workload: str
    concept: str
    unit: str = "rows"
    input_rows: int = 0
    measurements: list[Measurement] = field(default_factory=list)

    @property
    def baseline(self) -> Measurement | None:
        """The first registered strategy, against which speedups are quoted."""
        return self.measurements[0] if self.measurements else None

    def speedup(self, m: Measurement) -> float:
        """Baseline time divided by this strategy's time.

        Returns:
            Factor greater than 1 when faster than baseline, 0.0 if either
            timing is unusable.
        """
        base = self.baseline
        if base is None or m.failed or not m.seconds_median:
            return 0.0
        return base.seconds_median / m.seconds_median

    def best(self) -> Measurement | None:
        """The fastest strategy that also agreed with the baseline."""
        usable = [m for m in self.measurements if m.ok and m.seconds_median]
        return min(usable, key=lambda m: m.seconds_median) if usable else None

    def to_dict(self) -> dict[str, Any]:
        """Render as JSON-safe nested dicts for the results file."""
        return {
            "workload": self.workload,
            "concept": self.concept,
            "unit": self.unit,
            "input_rows": self.input_rows,
            "strategies": [
                {
                    "name": m.name,
                    "seconds_median": round(m.seconds_median, 6),
                    "seconds_min": round(m.seconds_min, 6),
                    "seconds_max": round(m.seconds_max, 6),
                    "peak_mib": round(m.peak_mib, 2),
                    "rows_out": m.rows_out,
                    "throughput_rows_per_s": (
                        round(self.input_rows / m.seconds_median) if m.seconds_median else 0
                    ),
                    "speedup_vs_baseline": round(self.speedup(m), 3),
                    "matches_baseline": m.matches_baseline,
                    "note": m.note,
                    "failed": m.failed,
                }
                for m in self.measurements
            ],
        }


def time_callable(fn: Callable[[], Any], trials: int = DEFAULT_TRIALS) -> tuple[list[float], Any]:
    """Run ``fn`` repeatedly and return every timing plus the last result.

    Garbage collection is forced before each trial so that a collection debt
    built up by the previous strategy is not charged to this one.

    Args:
        fn: Zero-argument callable to measure.
        trials: Number of measured runs, after the warm-up.

    Returns:
        ``(timings, result)`` where timings has one float per trial.
    """
    for _ in range(WARMUP_RUNS):
        fn()

    timings: list[float] = []
    result: Any = None
    for _ in range(trials):
        gc.collect()
        start = time.perf_counter()
        result = fn()
        timings.append(time.perf_counter() - start)
    return timings, result


def trace_peak_mib(fn: Callable[[], Any]) -> float:
    """Return the peak Python heap in MiB during one run of ``fn``.

    This counts only allocations Python made, so it excludes memory held inside
    native libraries. It is the reproducible half of memory measurement; RSS
    would also capture allocator and page-cache noise.
    """
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak / (1024 * 1024)


def _canonical_nulls(frame: pd.DataFrame) -> pd.DataFrame:
    """Render every missing value as ``None`` regardless of the dtype it came in.

    Strategies legitimately produce different null sentinels for the same
    absence: a pandas nullable string column holds ``pd.NA`` where an Arrow
    kernel's output holds ``None``, and numpy float columns hold ``NaN``. Those
    are the same answer, so the comparison normalises them rather than
    reporting a disagreement that does not exist.
    """
    return frame.astype(object).where(frame.notna(), None)


def _comparable(value: Any) -> Any:
    """Reduce a strategy's output to something order-insensitively comparable.

    DataFrames are sorted by all columns and index-reset, because two correct
    join strategies may legitimately emit the same rows in different orders;
    a hash join returns probe order, a sort-merge join returns sorted order.

    Series are *not* reordered: a parsed column must line up with the rows it
    came from, so position carries meaning there and a sort would hide a
    genuine misalignment.
    """
    if isinstance(value, pd.DataFrame):
        ordered = value.sort_values(list(value.columns), ignore_index=True)
        return _canonical_nulls(ordered)
    if isinstance(value, pd.Series):
        return _canonical_nulls(value.reset_index(drop=True).to_frame(name="value"))
    return value


def outputs_match(left: Any, right: Any) -> bool:
    """Compare two strategy outputs ignoring row order, dtype and null flavour.

    ``check_dtype=False`` is deliberate: DuckDB returns an int32 count where
    pandas returns int64, and that difference is not a correctness problem.
    Series are compared element-wise in their original order via
    :func:`_comparable`, which wraps them in a one-column frame.
    """
    left, right = _comparable(left), _comparable(right)
    if isinstance(left, pd.DataFrame) and isinstance(right, pd.DataFrame):
        if left.shape != right.shape:
            return False
        try:
            pd.testing.assert_frame_equal(left, right, check_dtype=False, check_like=True)
        except AssertionError:
            return False
        return True
    return bool(left == right)


def run_workload(
    *,
    workload: str,
    concept: str,
    strategies: Iterable[tuple[str, Callable[[], Any]]],
    input_rows: int,
    unit: str = "rows",
    trials: int = DEFAULT_TRIALS,
    notes: dict[str, str] | None = None,
    measure_memory: bool = True,
) -> WorkloadResult:
    """Measure every strategy for one workload and check they agree.

    The first strategy is the baseline: speedups are quoted against it and every
    other strategy's output is compared to its output.

    Args:
        workload: Name of the operation under test.
        concept: Lecture concept being exercised, for the report.
        strategies: ``(name, callable)`` pairs, baseline first.
        input_rows: Input size, used for throughput.
        unit: What an input row is.
        trials: Measured runs per strategy.
        notes: Optional per-strategy caveat shown in the report.
        measure_memory: Set False for I/O-bound workloads where the Python heap
            figure is meaningless.

    Returns:
        A :class:`WorkloadResult` holding one measurement per strategy.
    """
    notes = notes or {}
    result = WorkloadResult(workload=workload, concept=concept, unit=unit, input_rows=input_rows)
    baseline_output: Any = None

    for index, (name, fn) in enumerate(strategies):
        measurement = Measurement(name=name, note=notes.get(name, ""))
        try:
            timings, output = time_callable(fn, trials=trials)
            measurement.seconds_median = median(timings)
            measurement.seconds_min = min(timings)
            measurement.seconds_max = max(timings)
            measurement.rows_out = len(output) if hasattr(output, "__len__") else 0
            if measure_memory:
                measurement.peak_mib = trace_peak_mib(fn)
            if index == 0:
                baseline_output = output
            else:
                measurement.matches_baseline = outputs_match(baseline_output, output)
                if not measurement.matches_baseline:
                    logger.warning("%s / %s disagrees with the baseline", workload, name)
        except Exception as exc:  # a broken strategy is a result, not a crash
            measurement.failed = f"{type(exc).__name__}: {exc}"
            logger.warning("%s / %s failed: %s", workload, name, measurement.failed)
        result.measurements.append(measurement)
        logger.info(
            "%-28s %-26s %8.4f s  x%.2f",
            workload,
            name,
            measurement.seconds_median,
            result.speedup(measurement),
        )
    return result
