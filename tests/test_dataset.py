"""Generator invariants: determinism, probe-pool validity, shuffled edge order."""

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from graphbench.dataset import generate, load_manifest

SCALE = 400
SEED = 7


def _all_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def test_generation_is_byte_for_byte_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, scale=SCALE, seed=SEED)
    generate(b, scale=SCALE, seed=SEED)
    files_a, files_b = _all_files(a), _all_files(b)
    assert [p.relative_to(a) for p in files_a] == [p.relative_to(b) for p in files_b]
    for fa, fb in zip(files_a, files_b):
        assert fa.read_bytes() == fb.read_bytes(), fa.name


def test_manifest_pools_reference_existing_values(tmp_path):
    generate(tmp_path, scale=SCALE, seed=SEED)
    manifest = load_manifest(tmp_path)

    follows = pq.read_table(tmp_path / "edges" / "FOLLOWS.parquet")
    sources = set(follows.column("src").to_pylist())
    assert manifest.pools["person_id"], "person pool must not be empty"
    for pid in manifest.pools["person_id"]:
        assert pid in sources, "pool persons must have at least one outgoing FOLLOWS"

    countries = set(
        pq.read_table(tmp_path / "nodes" / "Country.parquet").column("name").to_pylist()
    )
    assert set(manifest.pools["country"]) == countries

    interests = set(
        pq.read_table(tmp_path / "nodes" / "Interest.parquet")
        .column("name")
        .to_pylist()
    )
    assert set(manifest.pools["interest"]) <= interests


def test_edges_are_not_written_in_sorted_order(tmp_path):
    generate(tmp_path, scale=SCALE, seed=SEED)
    follows = pq.read_table(tmp_path / "edges" / "FOLLOWS.parquet")
    src = np.asarray(follows.column("src").to_pylist())
    assert not np.all(src[:-1] <= src[1:]), (
        "FOLLOWS must be shuffled so sorted insertion order gives no engine "
        "a locality advantage"
    )
