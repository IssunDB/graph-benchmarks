"""Render a results JSON into a Markdown report and a latency plot.

The report has three parts: an environment header, a correctness matrix (which engine
agreed with the reference on each query), and a median-latency table with speedup
relative to a chosen baseline. The plot is a log-scaled grouped bar chart of median
latency per query per engine.
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


def _available_engines(results: dict) -> list[str]:
    return [name for name, rec in results["engines"].items() if rec.get("available")]


def _query_names(results: dict) -> list[str]:
    names: list[str] = []
    for rec in results["engines"].values():
        for q in rec.get("queries", {}):
            if q not in names:
                names.append(q)
    return names


def _median(results: dict, engine: str, query: str) -> float | None:
    q = results["engines"].get(engine, {}).get("queries", {}).get(query)
    if isinstance(q, dict) and "median_ms" in q:
        return q["median_ms"]
    return None


def to_markdown(results: dict, baseline: str | None = None) -> str:
    engines = _available_engines(results)
    queries = _query_names(results)
    meta = results["meta"]
    if baseline is None:
        baseline = "neo4j" if "neo4j" in engines else (engines[0] if engines else None)

    lines: list[str] = []
    lines.append("# Graph Benchmark Results")
    lines.append("")
    lines.append(
        f"- Scale: {meta['scale']} persons, seed {meta['seed']}  "
        f"- Host: {meta['platform']}  - Python {meta['python']}"
    )
    lines.append(
        f"- Warmup {meta['warmup']}, measured rounds {meta['rounds']}, generated {meta['timestamp']}"
    )
    counts = ", ".join(f"{k}={v}" for k, v in meta["counts"].items())
    lines.append(f"- Dataset counts: {counts}")
    lines.append("")

    # Build / load times.
    lines.append("## Load Time")
    lines.append("")
    lines.append("| Engine | Version | Nodes (s) | Edges (s) | Total (s) |")
    lines.append("| --- | --- | --- | --- | --- |")
    # Collect build times for determining the minimums
    build_times = {}
    for name in engines:
        b = results["engines"][name].get("build", {})
        build_times[name] = {
            "nodes": b.get("nodes_seconds"),
            "edges": b.get("edges_seconds"),
            "total": b.get("total_seconds"),
        }

    min_nodes = min(
        (
            t["nodes"]
            for t in build_times.values()
            if isinstance(t["nodes"], (int, float))
        ),
        default=None,
    )
    min_edges = min(
        (
            t["edges"]
            for t in build_times.values()
            if isinstance(t["edges"], (int, float))
        ),
        default=None,
    )
    min_total = min(
        (
            t["total"]
            for t in build_times.values()
            if isinstance(t["total"], (int, float))
        ),
        default=None,
    )

    for name in engines:
        b = results["engines"][name].get("build", {})
        nodes_val = b.get("nodes_seconds")
        edges_val = b.get("edges_seconds")
        total_val = b.get("total_seconds")

        nodes_str = f"{nodes_val}" if nodes_val is not None else "n/a"
        if min_nodes is not None and nodes_val == min_nodes:
            nodes_str = f"**{nodes_str}**"

        edges_str = f"{edges_val}" if edges_val is not None else "n/a"
        if min_edges is not None and edges_val == min_edges:
            edges_str = f"**{edges_str}**"

        total_str = f"{total_val}" if total_val is not None else "n/a"
        if min_total is not None and total_val == min_total:
            total_str = f"**{total_str}**"

        lines.append(
            f"| {name} | {results['engines'][name].get('version', '')} | "
            f"{nodes_str} | {edges_str} | {total_str} |"
        )
    lines.append("")

    # Correctness matrix.
    lines.append("## Correctness (vs reference row-set)")
    lines.append("")
    header = "| Query | Reference | " + " | ".join(engines) + " |"
    lines.append(header)
    lines.append("| " + " | ".join("---" for _ in range(len(engines) + 2)) + " |")
    for query in queries:
        corr = results["correctness"].get(query, {})
        ref = corr.get("reference", "")
        cells = []
        for name in engines:
            q = results["engines"][name].get("queries", {}).get(query)
            if not isinstance(q, dict):
                cells.append("-")
            elif "error" in q:
                cells.append("ERR")
            elif name == ref:
                cells.append("ref")
            else:
                cells.append("ok" if q.get("matches_reference") else "MISMATCH")
        lines.append(f"| {query} | {ref} | " + " | ".join(cells) + " |")
    lines.append("")

    # Median latency with speedup vs baseline.
    lines.append(
        f"## Median Latency (ms){f', speedup vs {baseline}' if baseline else ''}"
    )
    lines.append("")
    lines.append("| Query | " + " | ".join(engines) + " |")
    lines.append("| " + " | ".join("---" for _ in range(len(engines) + 1)) + " |")
    for query in queries:
        latencies = {}
        for name in engines:
            val = _median(results, name, query)
            if val is not None and val > 0:
                latencies[name] = val
        min_lat = min(latencies.values()) if latencies else None

        base_val = _median(results, baseline, query) if baseline else None
        cells = []
        for name in engines:
            val = _median(results, name, query)
            if val is None:
                cells.append("n/a")
                continue
            text = f"{val:.2f}"
            if baseline and name != baseline and base_val and val > 0:
                text += f" ({base_val / val:.1f}x)"
            if min_lat is not None and val == min_lat:
                text = f"**{text}**"
            cells.append(text)
        lines.append(f"| {query} | " + " | ".join(cells) + " |")
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
        series = [(_median(results, name, q) or np.nan) for q in queries]
        offsets = x + (idx - (len(engines) - 1) / 2) * width
        ax.bar(offsets, series, width=width, label=name, color=_ENGINE_COLORS.get(name))
    ax.set_xticks(x)
    ax.set_xticklabels(queries, rotation=45, ha="right")
    ax.set_ylabel("Median latency (ms, log scale)")
    ax.set_yscale("log")
    ax.set_title("Graph Benchmark: Median Query Latency (lower is better)")
    ax.legend(loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"Wrote plot to {out_path}")


def load_results(path: Path) -> dict:
    return json.loads(path.read_text())
