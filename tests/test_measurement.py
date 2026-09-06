"""The two measurements that were reporting something other than what they claimed:
process memory, and a query's cold run."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from graphbench import _worker
from graphbench.engines import get_engine_class
from graphbench.schema import SOCIAL

pytestmark = pytest.mark.skipif(
    not Path("/proc/self/status").exists(),
    reason="peak RSS is read from /proc, which this platform lacks",
)


def test_peak_rss_is_not_inherited_from_the_parent():
    """A worker's peak must describe the worker.

    `getrusage(RUSAGE_SELF).ru_maxrss` is inherited through fork *and* exec, so a child
    spawned by a parent that had already allocated reported the parent's high-water mark
    as its own. That is what made three different engines, one of them a bare network
    client, report byte-identical peaks. The child below allocates nothing, so anything
    close to the parent's peak means the reading is inherited again.
    """
    hog = bytearray(600 * 1024 * 1024)
    parent_peak = _worker._rss_peak_mb()
    assert parent_peak > 500, "the parent needs a high-water mark to be inherited"

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from graphbench import _worker; print(_worker._rss_peak_mb())",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    del hog
    child_peak = float(child.stdout.strip())
    assert child_peak < parent_peak / 4, (
        f"child reported {child_peak} MB against the parent's {parent_peak} MB, "
        "so the peak is being inherited rather than measured"
    )


def test_resetting_the_peak_separates_the_phases():
    """Without a reset, an ingestion peak hides every later phase, since it is the
    larger on every engine measured so far."""
    hog = bytearray(400 * 1024 * 1024)
    before = _worker._rss_peak_mb()
    del hog
    if not _worker._reset_rss_peak():
        pytest.skip("this kernel does not support resetting the peak via clear_refs")
    after = _worker._rss_peak_mb()
    assert after < before / 2, (
        f"peak still {after} MB after releasing the allocation that took it to {before}"
    )


def _run_cold_worker(tmp_path: Path, text: str, tag: str) -> dict:
    cfg_path = tmp_path / f"cold_{tag}.json"
    out_path = tmp_path / f"cold_{tag}_result.json"
    cfg_path.write_text(
        json.dumps(
            {
                "engine": "issundb",
                "workdir": str(tmp_path),
                "text": text,
                "out_path": str(out_path),
            }
        )
    )
    subprocess.run(
        [sys.executable, "-m", "graphbench._cold_worker", str(cfg_path)], check=True
    )
    return json.loads(out_path.read_text())


def test_a_cold_open_does_not_destroy_the_built_database(tmp_path):
    """`open_built` must attach to what the build left behind, repeatedly.

    The normal constructor deletes the database so a build starts empty, which is the one
    thing a cold-open path must not do: it runs after the build, on the same directory,
    once per query. Two runs in a row is what pins that, since a path that wiped the
    database would still let the first one pass.

    Both runs go through the subprocess for a second reason: LMDB refuses to open one
    environment twice in a single process, so an in-process reopen is not merely
    undesirable here, it is impossible.
    """
    klass = get_engine_class("issundb")
    if not klass.probe().available:
        pytest.skip("issundb is not installed")

    engine = klass(SOCIAL, tmp_path)
    engine.run("CREATE (n:Marker {id: 7})")
    engine.close()
    del engine

    query = "MATCH (n:Marker) RETURN n.id AS id"
    first = _run_cold_worker(tmp_path, query, "first")
    second = _run_cold_worker(tmp_path, query, "second")
    assert first["rows"] == 1, "the cold open must see the data, not an empty database"
    assert second["rows"] == 1, "the first cold open must have left the database intact"


def test_the_cold_worker_reports_a_timing_and_a_row_count(tmp_path):
    """End to end through the subprocess the runner actually spawns."""
    klass = get_engine_class("issundb")
    if not klass.probe().available:
        pytest.skip("issundb is not installed")

    engine = klass(SOCIAL, tmp_path)
    engine.run("CREATE (n:Marker {id: 7})")
    engine.close()

    cfg_path = tmp_path / "cold.json"
    out_path = tmp_path / "cold_result.json"
    cfg_path.write_text(
        json.dumps(
            {
                "engine": "issundb",
                "workdir": str(tmp_path),
                "text": "MATCH (n:Marker) RETURN n.id AS id",
                "out_path": str(out_path),
            }
        )
    )
    subprocess.run(
        [sys.executable, "-m", "graphbench._cold_worker", str(cfg_path)], check=True
    )
    result = json.loads(out_path.read_text())
    assert result["rows"] == 1
    assert result["cold_open_ms"] > 0
    # Timed apart from the query, since an engine that loads eagerly on open would
    # otherwise look fast in the query column and slow nowhere.
    assert "open_ms" in result


def test_an_engine_without_persistent_state_is_skipped_rather_than_guessed(tmp_path):
    """An in-memory engine re-reading its input is doing a build, not an open, so it has
    no cold-open figure; the runner must say so instead of reporting the build."""
    klass = get_engine_class("lance-graph")
    assert klass.supports_cold_open is False
    with pytest.raises(NotImplementedError):
        klass.open_built(SOCIAL, tmp_path)
