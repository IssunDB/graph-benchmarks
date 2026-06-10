"""Render a results JSON into a Markdown report and latency plots.

The report has six parts: an environment header (including hardware), an engine
overview (kind and ingestion method), load times grouped by engine kind with peak
RSS, a correctness matrix against the engine-independent oracle, warm-latency and
cold-run tables, and a notes section spelling out the caveats that make the numbers
interpretable (embedded vs client-server, ingestion-path differences, parameter
rotation, Neo4j server memory settings).

`plot` draws a log-scaled grouped bar chart of median latency with p25-p75 error
bars. `plot_scaling` draws median latency versus dataset scale, one panel per query,
from a list of results at different scales.
"""

from __future__ import annotations

import json
from pathlib import Path

_ENGINE_COLORS = {
    "issundb": "#2ca02c",
    "ladybug": "#d62728",
    "lance-graph": "#7f3fbf",
    "neo4j": "#1f77b4",
}

_KIND_ORDER = {"embedded": 0, "in-memory": 1, "server": 2}


def _available_engines(results: dict) -> list[str]:
    return [name for name, rec in results["engines"].items() if rec.get("available")]


def _query_names(results: dict) -> list[str]:
    names: list[str] = []
    for rec in results["engines"].values():
        for q in rec.get("queries", {}):
            if q not in names:
                names.append(q)
    return names


def _query_stat(results: dict, engine: str, query: str, stat: str) -> float | None:
    q = results["engines"].get(engine, {}).get("queries", {}).get(query)
    if isinstance(q, dict) and stat in q:
        return q[stat]
    return None


def _median(results: dict, engine: str, query: str) -> float | None:
    return _query_stat(results, engine, query, "median_ms")


def to_markdown(results: dict, baseline: str | None = None) -> str:
    engines = _available_engines(results)
    queries = _query_names(results)
    meta = results["meta"]
    timing = meta.get("timing", {})
    hardware = meta.get("hardware", {})
    if baseline is None:
        baseline = "neo4j" if "neo4j" in engines else (engines[0] if engines else None)

    lines: list[str] = []
    lines.append("# Graph Benchmark Results")
    lines.append("")
    lines.append(f"- Scale: {meta['scale']} persons, seed {meta['seed']}")
    hw_bits = []
    if hardware.get("cpu"):
        hw_bits.append(hardware["cpu"])
    if hardware.get("cores"):
        hw_bits.append(f"{hardware['cores']} cores")
    if hardware.get("memory_gb"):
        hw_bits.append(f"{hardware['memory_gb']} GB RAM")
    lines.append(
        f"- Host: {meta['platform']}"
        + (f" ({', '.join(hw_bits)})" if hw_bits else "")
        + f" - Python {meta['python']}"
    )
    lines.append(
        f"- Timing: warmup {timing.get('warmup')}, >= {timing.get('min_rounds')} rounds "
        f"per query within a {timing.get('time_budget_s')}s budget "
        f"(max {timing.get('max_rounds')}); query parameters rotate over up to "
        f"{timing.get('param_sets')} instantiations; "
        f"{'one isolated worker process per engine' if timing.get('isolated_processes') else 'engines share one process'}; "
        f"generated {meta['timestamp']}"
    )
    counts = ", ".join(f"{k}={v}" for k, v in meta["counts"].items())
    lines.append(f"- Dataset counts: {counts}")
    lines.append("")

    # Engine overview.
    lines.append("## Engines")
    lines.append("")
    lines.append("| Engine | Version | Kind | Ingestion method |")
    lines.append("| --- | --- | --- | --- |")
    for name in engines:
        rec = results["engines"][name]
        lines.append(
            f"| {name} | {rec.get('version', '')} | {rec.get('kind', '')} | "
            f"{rec.get('build_method', '')} |"
        )
    lines.append("")

    # Build / load times, grouped by kind: an in-memory table read, a persistent
    # embedded build, and a network ingest are not the same work, so they are never
    # ranked against each other.
    lines.append("## Load Time (grouped by engine kind - not comparable across kinds)")
    lines.append("")
    lines.append(
        "| Engine | Kind | Nodes (s) | Edges (s) | Total (s) | Peak RSS (MB) |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- |")
    ordered = sorted(
        engines, key=lambda n: _KIND_ORDER.get(results["engines"][n].get("kind", ""), 9)
    )
    for name in ordered:
        rec = results["engines"][name]
        build = rec.get("build", {})
        kind = rec.get("kind", "")
        rss = rec.get("rss_peak_mb")
        if kind == "server":
            rss_str = "n/a (client process only)"
        else:
            rss_str = f"{rss}" if rss is not None else "n/a"
        cells = [
            f"{build.get(key)}" if build.get(key) is not None else "n/a"
            for key in ("nodes_seconds", "edges_seconds", "total_seconds")
        ]
        lines.append(f"| {name} | {kind} | {' | '.join(cells)} | {rss_str} |")
    lines.append("")

    # Correctness matrix against the oracle.
    lines.append("## Correctness (vs engine-independent oracle)")
    lines.append("")
    lines.append(
        "Each engine's rows are diffed against ground truth computed directly from "
        "the Parquet dataset with polars, over the first few parameter "
        "instantiations of every query. No engine is its own reference."
    )
    lines.append("")
    lines.append("| Query | " + " | ".join(engines) + " |")
    lines.append("| " + " | ".join("---" for _ in range(len(engines) + 1)) + " |")
    for query in queries:
        cells = []
        for name in engines:
            q = results["engines"][name].get("queries", {}).get(query)
            if not isinstance(q, dict):
                cells.append("-")
            elif "error" in q:
                cells.append("ERR")
            else:
                cells.append("ok" if q.get("matches_oracle") else "MISMATCH")
        lines.append(f"| {query} | " + " | ".join(cells) + " |")
    lines.append("")

    # Warm latency: median with 95% CI, speedup vs baseline.
    lines.append(
        "## Warm Latency, median ms +/- 95% CI"
        + (f", speedup vs {baseline}" if baseline else "")
    )
    lines.append("")
    lines.append("| Query | " + " | ".join(engines) + " |")
    lines.append("| " + " | ".join("---" for _ in range(len(engines) + 1)) + " |")
    for query in queries:
        latencies = {
            name: val
            for name in engines
            if (val := _median(results, name, query)) is not None and val > 0
        }
        min_lat = min(latencies.values()) if latencies else None
        base_val = _median(results, baseline, query) if baseline else None
        cells = []
        for name in engines:
            val = _median(results, name, query)
            if val is None:
                q = results["engines"][name].get("queries", {}).get(query)
                cells.append("ERR" if isinstance(q, dict) and "error" in q else "n/a")
                continue
            ci = _query_stat(results, name, query, "ci95_ms")
            text = f"{val:.2f}"
            if ci is not None:
                text += f" +/-{ci:.2f}"
            if baseline and name != baseline and base_val and val > 0:
                text += f" ({base_val / val:.1f}x)"
            if min_lat is not None and val == min_lat:
                text = f"**{text}**"
            cells.append(text)
        lines.append(f"| {query} | " + " | ".join(cells) + " |")
    lines.append("")

    # Cold runs: first execution after build, before any cache warms.
    lines.append("## Cold Run (first execution after build, ms)")
    lines.append("")
    lines.append("| Query | " + " | ".join(engines) + " |")
    lines.append("| " + " | ".join("---" for _ in range(len(engines) + 1)) + " |")
    for query in queries:
        cells = []
        for name in engines:
            val = _query_stat(results, name, query, "cold_ms")
            cells.append(f"{val:.2f}" if val is not None else "n/a")
        lines.append(f"| {query} | " + " | ".join(cells) + " |")
    lines.append("")

    # Caveats that make the numbers interpretable.
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Engine kinds are not directly comparable: a client-server engine "
        "(neo4j) pays a network round-trip per query that embedded and in-memory "
        "engines do not, which dominates at sub-millisecond latencies; in-memory "
        "engines trade RSS for speed and perform no persistent build."
    )
    lines.append(
        "- Ingestion paths differ per engine (see the Engines table); load times "
        "measure each engine's available ingestion API, not a common code path."
    )
    lines.append(
        "- Parameterized queries rotate their literal values across rounds to "
        "defeat plan/result caches. Whole-graph aggregations (top_followed, "
        "two_hop_paths, ...) have no parameters, so their statement is necessarily "
        "identical every round."
    )
    for name in engines:
        server_info = results["engines"][name].get("server_info") or {}
        if server_info:
            settings = ", ".join(f"{k}={v}" for k, v in sorted(server_info.items()))
            lines.append(f"- {name} server settings: {settings}")
    lines.append("")
    return "\n".join(lines)


def plot(results: dict, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    engines = _available_engines(results)
    queries = _query_names(results)
    if not engines or not queries:
        raise SystemExit("Nothing to plot: no available engines or queries.")

    x = np.arange(len(queries))
    width = 0.8 / max(len(engines), 1)
    fig, ax = plt.subplots(figsize=(max(8, len(queries) * 1.1), 5))
    for idx, name in enumerate(engines):
        medians = np.array(
            [(_median(results, name, q) or np.nan) for q in queries], dtype=float
        )
        p25 = np.array(
            [(_query_stat(results, name, q, "p25_ms") or np.nan) for q in queries],
            dtype=float,
        )
        p75 = np.array(
            [(_query_stat(results, name, q, "p75_ms") or np.nan) for q in queries],
            dtype=float,
        )
        err = np.vstack(
            [np.clip(medians - p25, 0, None), np.clip(p75 - medians, 0, None)]
        )
        offsets = x + (idx - (len(engines) - 1) / 2) * width
        ax.bar(
            offsets,
            medians,
            width=width,
            label=name,
            color=_ENGINE_COLORS.get(name),
            yerr=np.nan_to_num(err),
            capsize=2,
            error_kw={"linewidth": 0.8},
        )
    ax.set_xticks(x)
    ax.set_xticklabels(queries, rotation=45, ha="right")
    ax.set_ylabel("Median latency (ms, log scale; whiskers p25-p75)")
    ax.set_yscale("log")
    ax.set_title("Graph Benchmark: Median Query Latency (lower is better)")
    ax.legend(loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"Wrote plot to {out_path}")


def plot_scaling(results_list: list[dict], out_path: Path) -> None:
    """Median latency vs dataset scale, one panel per query, one line per engine."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    results_list = sorted(results_list, key=lambda r: r["meta"]["scale"])
    scales = [r["meta"]["scale"] for r in results_list]
    engines: list[str] = []
    queries: list[str] = []
    for results in results_list:
        engines += [e for e in _available_engines(results) if e not in engines]
        queries += [q for q in _query_names(results) if q not in queries]
    if not engines or not queries:
        raise SystemExit("Nothing to plot: no available engines or queries.")

    ncols = 3
    nrows = -(-len(queries) // ncols)
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4.2 * ncols, 3.2 * nrows), squeeze=False
    )
    for qi, query in enumerate(queries):
        ax = axes[qi // ncols][qi % ncols]
        for name in engines:
            ys = [_median(results, name, query) for results in results_list]
            pts = [(s, y) for s, y in zip(scales, ys) if y is not None]
            if not pts:
                continue
            ax.plot(
                [p[0] for p in pts],
                [p[1] for p in pts],
                marker="o",
                label=name,
                color=_ENGINE_COLORS.get(name),
            )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(query, fontsize=9)
        ax.tick_params(labelsize=8)
    for qi in range(len(queries), nrows * ncols):
        axes[qi // ncols][qi % ncols].axis("off")
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower right", fontsize=9)
    fig.suptitle("Median latency (ms) vs scale (persons)", fontsize=11)
    fig.supxlabel("scale (persons)", fontsize=9)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"Wrote scaling plot to {out_path}")


def load_results(path: Path) -> dict:
    return json.loads(path.read_text())
