"""Command-line entrypoints.

The only module permitted to use ``argparse`` and ``print``
(docs/CODING_STANDARDS.md section 1). Every subcommand is a thin wrapper over a
library function, so the same steps are callable from an Airflow task without
shelling out.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from ecom import logging_setup
from ecom.analysis.profile import build_profile
from ecom.analysis.visualize import render_all
from ecom.bench.harness import DEFAULT_TRIALS
from ecom.bench.report import load_results, render_figures, render_markdown
from ecom.bench.run_bench import RESULTS_SUBDIR, run_all
from ecom.cleaning.run_clean import clean_all
from ecom.config import get_settings
from ecom.ingestion.ingest import ingest_all
from ecom.storage import get_storage
from ecom.synthetic.run_generate import generate_and_store
from ecom.synthetic.validate import run_validation

logger = logging.getLogger("ecom.cli")


def _cmd_ingest(_: argparse.Namespace) -> int:
    """Run source -> raw ingestion."""
    manifest = ingest_all()
    print(f"ingested {manifest['table_count']} tables, {manifest['total_rows']:,} rows")
    return 0


def _cmd_clean(_: argparse.Namespace) -> int:
    """Run raw -> processed cleaning."""
    counts = clean_all()
    for table, rows in counts.items():
        print(f"  processed/{table:<18} {rows:>8,} rows")
    return 0


def _cmd_inventory(_: argparse.Namespace) -> int:
    """Generate the synthetic inventory table."""
    manifest = generate_and_store()
    print(f"generated {manifest['rows']:,} synthetic inventory rows (seed {manifest['seed']})")
    for status, count in sorted(manifest["status_counts"].items()):
        print(f"  {status:<18} {count:>7,}")
    print(f"  sha256 {manifest['sha256']}")
    return 0


def _cmd_validate_inventory(_: argparse.Namespace) -> int:
    """Validate the synthetic inventory table and render its figures."""
    settings = get_settings()
    storage = get_storage(settings)
    reports = settings.resolve(settings.reports_dir)

    results = run_validation(
        storage.get_parquet(storage.processed_key("order_lines")),
        storage.get_parquet(storage.processed_key("orders")),
        storage.get_parquet(storage.processed_key("synthetic_inventory")),
        reports / "figures",
    )
    repro = results["reproducibility"]
    print(f"  reproducible across runs : {repro['identical']}")
    print(f"  differs across seeds     : {repro['differs_across_seeds']}")
    untouched = results["untouched"]
    both_unchanged = untouched["order_lines_unchanged"] and untouched["orders_unchanged"]
    print(f"  real inputs unchanged    : {both_unchanged}")
    print("  status share across seeds:")
    for row in results["spread"].itertuples(index=False):
        print(f"    {row.status:<18} {row.mean_pct:>7.3f}% +/- {row.std_pct:.4f}")
    for path in results["figures"]:
        print(f"  wrote {path}")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    """Run the optimisation study, then render its report and figures."""
    settings = get_settings()
    out = settings.resolve(settings.reports_dir) / RESULTS_SUBDIR

    if args.report_only:
        results = load_results(out / "results.json")
        print(f"re-rendering from {out / 'results.json'}")
    else:
        results = run_all(trials=args.trials)

    figures = render_figures(results, out / "figures")
    report = out / "optimisation_report.md"
    report.write_text(render_markdown(results, figures))

    flag = results["pipeline_flag"]
    sweep = results["selectivity_sweep"]
    print(
        f"  fast reader on clean stage : {flag['speedup']:.2f}x "
        f"({flag['baseline_s']:.2f}s -> {flag['fast_reader_s']:.2f}s)"
    )
    print(f"  processed layer identical  : {flag['all_tables_identical']}")
    print(f"  partition crossover        : {sweep['crossover_selectivity_pct']}% selectivity")
    shards = results["shard_sweep"]
    print(
        f"  shards recommended         : {shards['recommended_shards']}, "
        f"{shards['recommended_speedup']:.1f}x, "
        f"+{shards['recommended_storage_overhead_pct']:.1f}% storage "
        f"(within the {shards['storage_budget_pct']:.0f}% budget)"
    )
    print(
        f"  shards fastest             : {shards['fastest_shards']}, "
        f"{shards['fastest_speedup']:.1f}x, "
        f"+{shards['fastest_storage_overhead_pct']:.1f}% storage - not recommended"
    )
    for workload in results["workloads"]:
        rejected = [s["name"] for s in workload["strategies"] if s["matches_baseline"] is False]
        if rejected:
            print(f"  rejected (wrong answer)    : {', '.join(rejected)}")
    for path in figures:
        print(f"  wrote {path}")
    print(f"  wrote {report}")
    return 0


def _cmd_analyse(args: argparse.Namespace) -> int:
    """Build the profile and optionally render figures."""
    settings = get_settings()
    profile = build_profile()

    reports_dir = settings.resolve(settings.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "profile.json"
    report_path.write_text(json.dumps(profile, indent=2))
    print(f"wrote {report_path}")

    if not args.no_figures:
        for path in render_all(profile, figures_dir=reports_dir / "figures"):
            print(f"wrote {path}")
    return 0


def _cmd_pipeline(args: argparse.Namespace) -> int:
    """Run ingest, clean and analyse in order."""
    for step in (_cmd_ingest, _cmd_clean, _cmd_inventory, _cmd_analyse):
        code = step(args)
        if code != 0:
            return code
    return 0


def _cmd_storage(_: argparse.Namespace) -> int:
    """Show the active backend and what it currently holds."""
    storage = get_storage()
    print(storage.describe())
    keys = storage.list_keys()
    if not keys:
        print("  (empty - run 'ecom ingest' first)")
    for key in keys:
        print(f"  {key}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ecom", description="Olist co-occurrence and inventory analytics pipeline"
    )
    parser.add_argument("--log-level", default=None, help="override ECOM_LOG_LEVEL")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="copy source files into the raw layer").set_defaults(
        func=_cmd_ingest
    )
    sub.add_parser("clean", help="build the processed layer from raw").set_defaults(func=_cmd_clean)
    sub.add_parser("storage", help="show the active storage backend").set_defaults(
        func=_cmd_storage
    )
    sub.add_parser("inventory", help="generate the synthetic inventory table").set_defaults(
        func=_cmd_inventory
    )
    sub.add_parser(
        "validate-inventory", help="validate the synthetic inventory table"
    ).set_defaults(func=_cmd_validate_inventory)

    analyse = sub.add_parser("analyse", help="profile the processed layer and render figures")
    analyse.add_argument("--no-figures", action="store_true", help="skip PNG rendering")
    analyse.set_defaults(func=_cmd_analyse)

    bench = sub.add_parser("bench", help="run the pipeline optimisation study")
    bench.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_TRIALS,
        help=f"measured runs per strategy after one warm-up (default {DEFAULT_TRIALS})",
    )
    bench.add_argument(
        "--report-only",
        action="store_true",
        help="re-render the report and figures from the existing results.json",
    )
    bench.set_defaults(func=_cmd_bench)

    pipeline = sub.add_parser("pipeline", help="ingest + clean + analyse")
    pipeline.add_argument("--no-figures", action="store_true", help="skip PNG rendering")
    pipeline.set_defaults(func=_cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.

    Returns:
        Process exit code: 0 on success, 1 on a handled pipeline failure.
    """
    args = build_parser().parse_args(argv)
    logging_setup.configure(args.log_level or get_settings().log_level)
    try:
        return int(args.func(args))
    except Exception as exc:
        logger.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
