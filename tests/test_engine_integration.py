"""End-to-end: each locally available embedded engine must agree with the oracle.

Skipped per engine when its client library is not installed. The var-length
`follows_reach` query is excluded here because not every engine supports the
syntax; the benchmark runner records such failures as ERR rather than hiding them.
"""

import pytest

from graphbench import oracle
from graphbench.dataset import generate, load_manifest
from graphbench.engines import get_engine_class, normalize_rows, probe
from graphbench.queries import CATALOG
from graphbench.runner import build_param_sets
from graphbench.schema import SOCIAL

SCALE = 250
SEED = 5

QUERIES = tuple(q for q in CATALOG if q.name != "follows_reach")


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    generate(out, scale=SCALE, seed=SEED)
    return out


@pytest.mark.parametrize("engine_name", ["issundb", "ladybug", "lance-graph"])
def test_engine_matches_oracle(engine_name, data, tmp_path):
    info = probe(engine_name)
    if not info.available:
        pytest.skip(f"{engine_name} not installed: {info.reason}")

    manifest = load_manifest(data)
    tables = oracle.load_tables(data)
    engine = get_engine_class(engine_name)(SOCIAL, tmp_path / engine_name)
    try:
        engine.build(data)
        for query in QUERIES:
            params = build_param_sets(query, manifest.pools)[0]
            expected = normalize_rows(oracle.evaluate(tables, query, params))
            actual = normalize_rows(engine.run(query.instantiate(params)))
            assert actual == expected, query.name
    finally:
        engine.close()
