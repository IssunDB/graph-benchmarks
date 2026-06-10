"""Command-line entry point: `graphbench gen | run | report | engines`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import engines as eng
from .dataset import generate
from .queries import CATALOG, by_name
from .report import load_results, plot, to_markdown
from .runner import run_benchmark


def _cmd_gen(args: argparse.Namespace) -> None:
    out = Path(args.out)
    manifest = generate(out, scale=args.scale, seed=args.seed)
    print(f"Generated scale={manifest.scale} seed={manifest.seed} into {out}")
    for label, count in manifest.counts.items():
        print(f"  {label:<14} {count}")


def _cmd_engines(args: argparse.Namespace) -> None:
    for name in eng.ALL_ENGINES:
        info = eng.probe(name)
        status = (
            f"available ({info.version})"
            if info.available
            else f"unavailable: {info.reason}"
        )
        print(f"{name:<12} {status}")


def _cmd_run(args: argparse.Namespace) -> None:
    names = args.engines.split(",") if args.engines else list(eng.ALL_ENGINES)
    queries = (
        tuple(by_name(n) for n in args.queries.split(",")) if args.queries else CATALOG
    )
    results = run_benchmark(
        engine_names=names,
        data_dir=Path(args.data),
        warmup=args.warmup,
        rounds=args.rounds,
        queries=queries,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote results to {out}")
    if not args.no_report:
        _render(results, Path(args.report_md), Path(args.report_plot), args.baseline)


def _cmd_report(args: argparse.Namespace) -> None:
    results = load_results(Path(args.results))
    _render(results, Path(args.out_md), Path(args.out_plot), args.baseline)


def _render(
    results: dict, md_path: Path, plot_path: Path, baseline: str | None
) -> None:
    md = to_markdown(results, baseline=baseline)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md)
    print(f"Wrote report to {md_path}")
    print("\n" + md)
    try:
        plot(results, plot_path)
    except SystemExit as exc:
        print(f"(plot skipped: {exc})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graphbench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gen", help="Generate a synthetic dataset")
    g.add_argument("--scale", type=int, default=10_000, help="Number of Person nodes")
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--out", default="data")
    g.set_defaults(func=_cmd_gen)

    e = sub.add_parser("engines", help="List engine availability")
    e.set_defaults(func=_cmd_engines)

    r = sub.add_parser("run", help="Build, validate, and time engines")
    r.add_argument("--engines", default="", help="Comma list; default all registered")
    r.add_argument(
        "--queries", default="", help="Comma list of query names; default all"
    )
    r.add_argument("--data", default="data")
    r.add_argument("--warmup", type=int, default=3)
    r.add_argument("--rounds", type=int, default=10)
    r.add_argument("--out", default="results/results.json")
    r.add_argument(
        "--baseline", default=None, help="Engine to compute speedups against"
    )
    r.add_argument("--report-md", default="results/report.md")
    r.add_argument("--report-plot", default="results/latency.png")
    r.add_argument("--no-report", action="store_true")
    r.set_defaults(func=_cmd_run)

    p = sub.add_parser("report", help="Render a report from a results JSON")
    p.add_argument("--results", default="results/results.json")
    p.add_argument("--out-md", default="results/report.md")
    p.add_argument("--out-plot", default="results/latency.png")
    p.add_argument("--baseline", default=None)
    p.set_defaults(func=_cmd_report)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
