"""Benchmark orchestration: oracle ground truth, per-engine workers, correctness gate.

The runner first computes the expected rows for every query instantiation with the
engine-independent oracle (polars over the raw Parquet — see `oracle.py`). Each
requested engine is then benchmarked in its own worker subprocess (`_worker.py`) so
engines cannot perturb each other's measurements and peak RSS is per-engine. Finally,
every engine's captured result rows are diffed against the oracle's; mismatches are
recorded and surfaced rather than silently timed away.

Query placeholders are instantiated from the manifest's probe pools into a fixed,
deterministic sequence of parameter sets, identical for every engine, so timings stay
comparable while repeated rounds never execute an identical statement.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import engines as eng
from . import oracle
from .dataset import load_manifest
from .queries import CATALOG, Query

# Number of parameter instantiations per parameterized query (timing rotates over
# all of them; correctness checks the first K_CORRECTNESS).
N_PARAM_SETS = 8
K_CORRECTNESS = 3


def build_param_sets(query: Query, pools: dict[str, list]) -> list[dict]:
    """Deterministic parameter sets for `query`, drawn round-robin from the pools."""
    if not query.params:
        return [{}]
    size = min(N_PARAM_SETS, max(len(pools[p]) for p in query.params))
    return [{p: pools[p][i % len(pools[p])] for p in query.params} for i in range(size)]


def _hardware() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory_gb = None
    try:
        memory_gb = round(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1
        )
    except (ValueError, OSError, AttributeError):
        pass
    return {"cpu": cpu, "cores": os.cpu_count(), "memory_gb": memory_gb}


def _run_worker(cfg: dict, isolate: bool) -> dict:
    workdir = Path(cfg["workdir"])
    workdir.mkdir(parents=True, exist_ok=True)
    if not isolate:
        from . import _worker

        return _worker.run_engine(cfg)
    cfg_path = workdir / "worker_config.json"
    out_path = Path(cfg["out_path"])
    out_path.unlink(missing_ok=True)
    cfg_path.write_text(json.dumps(cfg))
    proc = subprocess.run(
        [sys.executable, "-m", "graphbench._worker", str(cfg_path)], check=False
    )
    if not out_path.exists():
        raise RuntimeError(f"worker exited with code {proc.returncode} and no result")
    return json.loads(out_path.read_text())


def _measure_cold_open(
    name: str,
    klass: type,
    workdir: Path,
    queries: tuple[Query, ...],
    param_sets: dict[str, list[dict]],
    record: dict,
) -> None:
    """Time each query once in a fresh process attached to the built database.

    One process per query, because the point is that nothing else has run in it: two
    queries sharing a process would leave the second one warm again, which is the defect
    this measurement exists to avoid. The cost is one process start plus one open per
    query, which is why this is a single run rather than a timed distribution.

    Anything that goes wrong is recorded against the query and does not fail the run:
    this is a supplementary measurement, and the in-process figure is still there.
    """
    if not klass.supports_cold_open:
        reason = "engine cannot reopen a built database"
        record["cold_open"] = {"skipped": reason}
        print(f"[{name}] cold-open runs skipped: {reason}")
        return

    print(f"[{name}] cold-open runs (one process per query) ...")
    out: dict = {}
    for query in queries:
        text = query.instantiate(param_sets[query.name][0])
        cfg_path = workdir / f"cold_{query.name}.json"
        out_path = workdir / f"cold_{query.name}_result.json"
        out_path.unlink(missing_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "engine": name,
                    "workdir": str(workdir),
                    "text": text,
                    "out_path": str(out_path),
                }
            )
        )
        proc = subprocess.run(
            [sys.executable, "-m", "graphbench._cold_worker", str(cfg_path)],
            check=False,
        )
        if not out_path.exists():
            out[query.name] = {"error": f"cold worker exited with {proc.returncode}"}
        else:
            out[query.name] = json.loads(out_path.read_text())
        cfg_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

        result = out[query.name]
        if "cold_open_ms" in result:
            # Fold into the per-query record so consumers find it next to the warm
            # numbers, and keep the in-process figure under a name that says what it is.
            q = record.get("queries", {}).get(query.name)
            if isinstance(q, dict):
                q["cold_open_ms"] = result["cold_open_ms"]
                q["cold_open_ms_open"] = result["open_ms"]
                if "cold_ms" in q:
                    q["first_run_in_warm_process_ms"] = q.pop("cold_ms")
            print(
                f"    {query.name:<26} {result['cold_open_ms']:8.3f} ms cold "
                f"(+{result['open_ms']:.3f} ms open, {result['rows']} rows)",
                flush=True,
            )
        else:
            print(f"    {query.name:<26} cold run unavailable: {result}", flush=True)
    record["cold_open"] = out


def run_benchmark(
    engine_names: list[str],
    data_dir: Path,
    warmup: int = 3,
    min_rounds: int = 20,
    time_budget_s: float = 2.0,
    max_rounds: int = 1000,
    queries: tuple[Query, ...] = CATALOG,
    isolate: bool = True,
) -> dict:
    manifest = load_manifest(data_dir)
    param_sets = {q.name: build_param_sets(q, manifest.pools) for q in queries}
    k_correctness = {
        q.name: min(K_CORRECTNESS, len(param_sets[q.name])) for q in queries
    }

    print("[oracle] computing ground truth from Parquet ...")
    tables = oracle.load_tables(data_dir)
    expected = {
        q.name: [
            eng.normalize_rows(oracle.evaluate(tables, q, ps))
            for ps in param_sets[q.name][: k_correctness[q.name]]
        ]
        for q in queries
    }

    results: dict = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": platform.node(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "hardware": _hardware(),
            "scale": manifest.scale,
            "seed": manifest.seed,
            "counts": manifest.counts,
            "timing": {
                "warmup": warmup,
                "min_rounds": min_rounds,
                "time_budget_s": time_budget_s,
                "max_rounds": max_rounds,
                "param_sets": N_PARAM_SETS,
                "isolated_processes": isolate,
            },
        },
        "engines": {},
        "correctness": {},
    }

    for name in engine_names:
        info = eng.probe(name)
        record: dict = {"version": info.version, "available": info.available}
        if not info.available:
            record["reason"] = info.reason
            results["engines"][name] = record
            print(f"[{name}] unavailable: {info.reason}")
            continue
        klass = eng.get_engine_class(name)
        record["kind"] = klass.kind
        record["build_method"] = klass.build_method

        workdir = data_dir.parent / "work" / name
        cfg = {
            "engine": name,
            "data_dir": str(data_dir),
            "workdir": str(workdir),
            "out_path": str(workdir / "worker_result.json"),
            "warmup": warmup,
            "min_rounds": min_rounds,
            "time_budget_s": time_budget_s,
            "max_rounds": max_rounds,
            "queries": [
                {
                    "name": q.name,
                    "param_sets": param_sets[q.name],
                    "k_correctness": k_correctness[q.name],
                }
                for q in queries
            ],
        }
        mode = "isolated worker" if isolate else "in-process"
        print(f"[{name}] building (scale={manifest.scale}, {mode}) ...")
        try:
            record.update(_run_worker(cfg, isolate))
        except Exception as exc:
            record["error"] = str(exc)
            print(f"[{name}] failed to build/run: {exc}")
        if "error" not in record:
            _measure_cold_open(name, klass, workdir, queries, param_sets, record)
        results["engines"][name] = record

    # Correctness gate: diff each engine's captured row-sets against the oracle's,
    # per parameter instantiation. An engine matches only if every instantiation does.
    for query in queries:
        matches: dict[str, bool] = {}
        for name in engine_names:
            q = results["engines"][name].get("queries", {}).get(query.name)
            if not isinstance(q, dict) or "correctness" not in q:
                continue
            ok = q.pop("correctness") == expected[query.name]
            matches[name] = ok
            q["matches_oracle"] = ok
        results["correctness"][query.name] = {
            "reference": "oracle",
            "param_sets_checked": k_correctness[query.name],
            "expected_rows": [len(rows) for rows in expected[query.name]],
            "matches": matches,
        }

    return results
