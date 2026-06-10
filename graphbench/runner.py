"""Benchmark orchestration: build, correctness gate, and timing.

For each requested engine the runner builds the graph once, then for each query it
executes once to capture the result (used as the correctness sample), warms up, and
takes timed rounds. Results from every engine are diffed against a reference engine's
row-set; mismatches are recorded and surfaced rather than silently timed away.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import engines as eng
from .dataset import load_manifest
from .queries import CATALOG, Query
from .schema import SOCIAL, Schema


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return float("nan")
    ordered = sorted(samples)
    rank = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[rank]


@dataclass
class QueryTiming:
    rows: int
    min_ms: float
    median_ms: float
    p95_ms: float
    error: str = ""
    normalized: list = field(default_factory=list, repr=False)


def _time_query(
    engine: eng.Engine, query: Query, warmup: int, rounds: int
) -> QueryTiming:
    # First run doubles as a result capture and an initial warmup.
    rows = engine.run(query)
    normalized = eng.normalize_rows(rows)
    for _ in range(max(0, warmup - 1)):
        engine.run(query)
    samples: list[float] = []
    for _ in range(rounds):
        start = time.perf_counter()
        engine.run(query)
        samples.append((time.perf_counter() - start) * 1000.0)
    return QueryTiming(
        rows=len(rows),
        min_ms=min(samples),
        median_ms=statistics.median(samples),
        p95_ms=_percentile(samples, 95),
        normalized=normalized,
    )


def run_benchmark(
    engine_names: list[str],
    data_dir: Path,
    warmup: int = 3,
    rounds: int = 10,
    queries: tuple[Query, ...] = CATALOG,
    schema: Schema = SOCIAL,
) -> dict:
    manifest = load_manifest(data_dir)
    results: dict = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "scale": manifest.scale,
            "seed": manifest.seed,
            "counts": manifest.counts,
            "warmup": warmup,
            "rounds": rounds,
        },
        "engines": {},
        "correctness": {},
    }

    # Per-query normalized results, in engine run order, for the correctness gate.
    per_query: dict[str, list[tuple[str, list]]] = {q.name: [] for q in queries}

    for name in engine_names:
        info = eng.probe(name)
        record: dict = {"version": info.version, "available": info.available}
        if not info.available:
            record["reason"] = info.reason
            results["engines"][name] = record
            print(f"[{name}] unavailable: {info.reason}")
            continue

        print(f"[{name}] building (scale={manifest.scale}) ...")
        try:
            engine = eng.get_engine_class(name)(schema, data_dir.parent / "work" / name)
            try:
                build = engine.build(data_dir)
                record["build"] = {
                    "nodes_seconds": round(build.nodes_seconds, 4),
                    "edges_seconds": round(build.edges_seconds, 4),
                    "total_seconds": round(build.total_seconds, 4),
                }
                print(
                    f"[{name}] built in {build.total_seconds:.2f}s; running queries ..."
                )
                record["queries"] = {}
                for query in queries:
                    try:
                        timing = _time_query(engine, query, warmup, rounds)
                        per_query[query.name].append((name, timing.normalized))
                        record["queries"][query.name] = {
                            "rows": timing.rows,
                            "min_ms": round(timing.min_ms, 4),
                            "median_ms": round(timing.median_ms, 4),
                            "p95_ms": round(timing.p95_ms, 4),
                        }
                        print(
                            f"    {query.name:<26} {timing.median_ms:8.3f} ms  ({timing.rows} rows)"
                        )
                    except Exception as exc:
                        record["queries"][query.name] = {"error": str(exc)}
                        print(f"    {query.name:<26} ERROR: {exc}")
            finally:
                engine.close()
        except Exception as exc:
            record["error"] = str(exc)
            print(f"[{name}] failed to build/run: {exc}")
        results["engines"][name] = record

    # Correctness gate: diff each engine's row-set against the reference (first engine
    # that produced a result for that query).
    for query in queries:
        produced = per_query[query.name]
        if not produced:
            continue
        ref_name, ref_rows = produced[0]
        matches = {ref_name: True}
        for other_name, other_rows in produced[1:]:
            matches[other_name] = other_rows == ref_rows
        results["correctness"][query.name] = {
            "reference": ref_name,
            "reference_rows": len(ref_rows),
            "matches": matches,
        }
        # Annotate per-engine query records with the match verdict.
        for other_name, ok in matches.items():
            q = results["engines"][other_name]["queries"].get(query.name)
            if isinstance(q, dict) and "error" not in q:
                q["matches_reference"] = ok

    return results
