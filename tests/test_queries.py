"""Catalog templates and parameter-set construction."""

import pytest

from graphbench.queries import CATALOG, by_name
from graphbench.runner import build_param_sets

SAMPLE_VALUES = {"person_id": 42, "country": "Country_00", "interest": "Interest_00"}


def test_every_template_instantiates_cleanly():
    for query in CATALOG:
        text = query.instantiate(SAMPLE_VALUES)
        assert "{" not in text and "}" not in text, query.name


def test_parameterless_queries_ignore_values():
    query = by_name("two_hop_paths")
    assert query.instantiate({}) == query.cypher


def test_missing_param_raises():
    with pytest.raises(KeyError):
        by_name("point_lookup").instantiate({})


def test_param_sets_rotate_over_pools():
    pools = {"person_id": [1, 2, 3], "country": ["X"], "interest": ["A", "B"]}
    sets = build_param_sets(by_name("point_lookup"), pools)
    assert sets == [{"person_id": 1}, {"person_id": 2}, {"person_id": 3}]
    assert build_param_sets(by_name("two_hop_paths"), pools) == [{}]


def test_param_sets_are_capped():
    pools = {"person_id": list(range(100))}
    sets = build_param_sets(by_name("point_lookup"), pools)
    assert len(sets) == 8
