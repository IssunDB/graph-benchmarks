"""The oracle's answers verified against independent numpy computations over the
raw Parquet, on a small generated dataset."""

import numpy as np
import pyarrow.parquet as pq
import pytest

from graphbench import oracle
from graphbench.dataset import generate, load_manifest
from graphbench.queries import CATALOG, by_name

SCALE = 400
SEED = 11


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    generate(out, scale=SCALE, seed=SEED)
    return out


@pytest.fixture(scope="module")
def tables(data):
    return oracle.load_tables(data)


@pytest.fixture(scope="module")
def manifest(data):
    return load_manifest(data)


def test_every_catalog_query_has_an_evaluator(tables, manifest):
    params = {
        "person_id": manifest.pools["person_id"][0],
        "country": manifest.pools["country"][0],
        "interest": manifest.pools["interest"][0],
    }
    for query in CATALOG:
        rows = oracle.evaluate(tables, query, params)
        assert isinstance(rows, list)


def test_point_lookup_matches_parquet(data, tables, manifest):
    pid = manifest.pools["person_id"][0]
    persons = pq.read_table(data / "nodes" / "Person.parquet").to_pylist()
    expected = [{"name": r["name"], "age": r["age"]} for r in persons if r["id"] == pid]
    assert (
        oracle.evaluate(tables, by_name("point_lookup"), {"person_id": pid}) == expected
    )


def test_one_hop_matches_parquet(data, tables, manifest):
    pid = manifest.pools["person_id"][0]
    follows = pq.read_table(data / "edges" / "FOLLOWS.parquet")
    src = np.asarray(follows.column("src").to_pylist())
    dst = np.asarray(follows.column("dst").to_pylist())
    expected = sorted(int(d) for d in dst[src == pid])
    rows = oracle.evaluate(tables, by_name("one_hop_neighbors"), {"person_id": pid})
    assert [r["id"] for r in rows] == expected
    assert expected, "pool person must have at least one outgoing edge"


def test_two_hop_path_count_matches_numpy(data, tables):
    follows = pq.read_table(data / "edges" / "FOLLOWS.parquet")
    src = np.asarray(follows.column("src").to_pylist())
    dst = np.asarray(follows.column("dst").to_pylist())
    out_degree = np.bincount(src, minlength=SCALE)
    expected = int(out_degree[dst].sum())
    rows = oracle.evaluate(tables, by_name("two_hop_paths"), {})
    assert rows == [{"num": expected}]


def test_top_followed_matches_max_indegree(data, tables):
    follows = pq.read_table(data / "edges" / "FOLLOWS.parquet")
    dst = np.asarray(follows.column("dst").to_pylist())
    in_degree = np.bincount(dst, minlength=SCALE)
    rows = oracle.evaluate(tables, by_name("top_followed"), {})
    assert len(rows) == 3
    assert rows[0]["num"] == int(in_degree.max())
    assert rows[0]["id"] == int(np.argmax(in_degree))  # ties broken by lowest id


def test_age_band_counts_sum_to_population_in_band(data, tables):
    persons = pq.read_table(data / "nodes" / "Person.parquet")
    ages = np.asarray(persons.column("age").to_pylist())
    in_band = int(((ages >= 30) & (ages <= 40)).sum())
    # Every person lives in exactly one city in one of <= 5 countries, and the
    # query's LIMIT 5 therefore covers all of them.
    rows = oracle.evaluate(tables, by_name("age_band_by_country"), {})
    assert sum(r["num"] for r in rows) == in_band


def test_follows_reach_matches_set_arithmetic(data, tables, manifest):
    pid = manifest.pools["person_id"][0]
    follows = pq.read_table(data / "edges" / "FOLLOWS.parquet")
    src = np.asarray(follows.column("src").to_pylist())
    dst = np.asarray(follows.column("dst").to_pylist())
    one = set(dst[src == pid].tolist())
    two = set(dst[np.isin(src, list(one))].tolist())
    rows = oracle.evaluate(tables, by_name("follows_reach"), {"person_id": pid})
    assert rows == [{"num": len(one | two)}]
