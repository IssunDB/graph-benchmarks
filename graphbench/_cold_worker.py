"""Time one query in a process that did no ingestion.

The build worker measures every query inside one long-lived process, so by the time a
query runs first, the engine has already been warmed twice over: by whatever its
ingestion path built eagerly, and by every query before it. For IssunDB, `IMPORT
DATABASE` ends with a full CSR-snapshot rebuild, so the structure a first aggregation
would otherwise have to build is charged to load time, and no query ever pays it. The
"cold run" recorded there is therefore cold only with respect to that one query's own
caches, which is not what a user meets on a freshly opened database.

This module answers the other question. The runner spawns it once per query, as
`python -m graphbench._cold_worker <config.json>`; it attaches to the database the
build worker left behind (`Engine.open_built`, which must not rebuild or delete
anything), runs the statement exactly once, and exits.

Two limits are deliberate and worth stating wherever these numbers are shown. The
database file is still in the operating system's page cache from the build, so this
measures a cold *process*, not cold storage; dropping caches needs privileges a
benchmark should not want. And an engine with nothing persistent to reopen, such as an
in-memory one, cannot be measured this way at all: re-reading its input is a build. Such
engines report no cold-open figure rather than a misleading one.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import engines as eng
from .schema import SOCIAL


def run_cold(cfg: dict) -> dict:
    name = cfg["engine"]
    klass = eng.get_engine_class(name)
    if not klass.supports_cold_open:
        return {"skipped": f"{name} cannot reopen a built database"}

    # The open is timed separately: for a lazily-opening engine it is microseconds, and
    # for one that loads eagerly it is most of the answer, so folding it into the query
    # would hide which of the two is being measured.
    open_start = time.perf_counter()
    engine = klass.open_built(SOCIAL, Path(cfg["workdir"]))
    open_ms = (time.perf_counter() - open_start) * 1000.0
    try:
        start = time.perf_counter()
        rows = engine.run(cfg["text"])
        elapsed_ms = (time.perf_counter() - start) * 1000.0
    finally:
        engine.close()
    return {
        "open_ms": round(open_ms, 4),
        "cold_open_ms": round(elapsed_ms, 4),
        "rows": len(rows),
    }


def main() -> None:
    cfg = json.loads(Path(sys.argv[1]).read_text())
    try:
        result = run_cold(cfg)
    except Exception as exc:
        result = {"error": str(exc)}
    Path(cfg["out_path"]).write_text(json.dumps(result))


if __name__ == "__main__":
    main()
