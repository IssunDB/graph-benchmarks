"""Single-engine benchmark worker, run in its own process.

The runner spawns this module as `python -m graphbench._worker <config.json>` so
every engine measures in a fresh process: no shared heap state, allocator
fragmentation, or import side effects leak from one engine into the next, and the
process RSS high-water mark is attributable to exactly one engine.

Per query the worker records a cold run (first execution after build), captures
result rows for the first few parameter instantiations (the correctness samples the
runner diffs against the oracle), warms up, then takes timed rounds with the garbage
collector disabled. Timed rounds rotate through the parameter instantiations so no
engine can serve a repeated identical statement from a plan or result cache.

The result is written as JSON to the path given in the config; stdout/stderr are
inherited from the runner so progress is visible live.
"""

from __future__ import annotations

import gc
import json
import math
import resource
import statistics
import sys
import time
from pathlib import Path

from . import engines as eng
from .queries import Query, by_name
from .schema import SOCIAL


def _percentile(ordered: list[float], pct: float) -> float:
    if not ordered:
        return float("nan")
    rank = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[rank]


def _median_ci(ordered: list[float]) -> tuple[float, float]:
    """Distribution-free 95% CI for the *median* via the binomial (order-statistic)
    method, normal-approximated.

    The reported point estimate is the median, so its interval should be a median CI,
    not `1.96*std/sqrt(n)` (a CI for the *mean* that also assumes normality). Latency
    samples are right-skewed, so this nonparametric interval, read straight off the
    order statistics, is the honest choice. Returns absolute (lo, hi) bounds.
    """
    n = len(ordered)
    if n < 2:
        return ordered[0], ordered[0]
    half = 1.96 * math.sqrt(n)
    lo_rank = math.floor((n - half) / 2.0)  # 1-indexed lower order statistic
    hi_rank = math.ceil((n + half) / 2.0) + 1  # 1-indexed upper order statistic
    lo_idx = min(max(lo_rank - 1, 0), n - 1)
    hi_idx = min(max(hi_rank - 1, 0), n - 1)
    return ordered[lo_idx], ordered[hi_idx]


def _stats(samples: list[float]) -> dict:
    ordered = sorted(samples)
    n = len(samples)
    mean = statistics.fmean(samples)
    std = statistics.stdev(samples) if n > 1 else 0.0
    ci_lo, ci_hi = _median_ci(ordered)
    return {
        "rounds": n,
        "min_ms": round(ordered[0], 4),
        "p25_ms": round(_percentile(ordered, 25), 4),
        "median_ms": round(statistics.median(samples), 4),
        "p75_ms": round(_percentile(ordered, 75), 4),
        "p95_ms": round(_percentile(ordered, 95), 4),
        "mean_ms": round(mean, 4),
        "std_ms": round(std, 4),
        # 95% CI for the median (order-statistic method), as absolute bounds.
        "ci_lo_ms": round(ci_lo, 4),
        "ci_hi_ms": round(ci_hi, 4),
    }


def _time_query(engine: eng.Engine, query: Query, qcfg: dict, cfg: dict) -> dict:
    texts = [query.instantiate(ps) for ps in qcfg["param_sets"]]
    out: dict = {}

    # Cold run: first execution of this query after build, before any cache warms.
    start = time.perf_counter()
    rows = engine.run(texts[0])
    out["cold_ms"] = round((time.perf_counter() - start) * 1000.0, 4)
    out["rows"] = len(rows)

    # Correctness samples for the first k parameter instantiations.
    captures = [eng.normalize_rows(rows)]
    for text in texts[1 : qcfg["k_correctness"]]:
        captures.append(eng.normalize_rows(engine.run(text)))
    out["correctness"] = captures

    for i in range(cfg["warmup"]):
        engine.run(texts[i % len(texts)])

    # Timed rounds: at least min_rounds, then keep going until the per-query time
    # budget is spent, hard-capped at max_rounds. GC is off so collection pauses do
    # not land inside individual samples.
    samples: list[float] = []
    elapsed = 0.0
    gc_was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        i = 0
        while len(samples) < cfg["max_rounds"] and (
            len(samples) < cfg["min_rounds"] or elapsed < cfg["time_budget_s"]
        ):
            text = texts[i % len(texts)]
            i += 1
            start = time.perf_counter()
            engine.run(text)
            duration = time.perf_counter() - start
            samples.append(duration * 1000.0)
            elapsed += duration
    finally:
        if gc_was_enabled:
            gc.enable()
    out.update(_stats(samples))
    return out


def _rss_peak_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is kilobytes on Linux, bytes on macOS.
    return round(peak / (1e6 if sys.platform == "darwin" else 1e3), 1)


def run_engine(cfg: dict) -> dict:
    """Build one engine and time every configured query. Importable for in-process use."""
    name = cfg["engine"]
    record: dict = {}
    engine = eng.get_engine_class(name)(SOCIAL, Path(cfg["workdir"]))
    try:
        build = engine.build(Path(cfg["data_dir"]))
        record["build"] = {
            "nodes_seconds": round(build.nodes_seconds, 4),
            "edges_seconds": round(build.edges_seconds, 4),
            "total_seconds": round(build.total_seconds, 4),
        }
        record["server_info"] = engine.server_info()
        print(f"[{name}] built in {build.total_seconds:.2f}s; running queries ...")
        record["queries"] = {}
        for qcfg in cfg["queries"]:
            query = by_name(qcfg["name"])
            try:
                timing = _time_query(engine, query, qcfg, cfg)
                record["queries"][query.name] = timing
                print(
                    f"    {query.name:<26} {timing['median_ms']:8.3f} ms median "
                    f"({timing['rounds']} rounds, {timing['rows']} rows)",
                    flush=True,
                )
            except Exception as exc:
                record["queries"][query.name] = {"error": str(exc)}
                print(f"    {query.name:<26} ERROR: {exc}", flush=True)
    finally:
        engine.close()
    record["rss_peak_mb"] = _rss_peak_mb()
    return record


def main() -> None:
    cfg = json.loads(Path(sys.argv[1]).read_text())
    try:
        record = run_engine(cfg)
    except Exception as exc:
        record = {"error": str(exc), "rss_peak_mb": _rss_peak_mb()}
    Path(cfg["out_path"]).write_text(json.dumps(record))


if __name__ == "__main__":
    main()
