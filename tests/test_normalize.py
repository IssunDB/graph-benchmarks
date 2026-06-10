"""Normalization must make row/column order, numeric type, and the worker's JSON
round-trip irrelevant to the correctness gate."""

import json

from graphbench.engines import normalize_rows


def test_column_order_is_irrelevant():
    assert normalize_rows([{"a": 1, "b": 2}]) == normalize_rows([{"b": 2, "a": 1}])


def test_row_order_is_irrelevant():
    assert normalize_rows([{"a": 1}, {"a": 2}]) == normalize_rows([{"a": 2}, {"a": 1}])


def test_int_and_float_counts_compare_equal():
    assert normalize_rows([{"num": 4}]) == normalize_rows([{"num": 4.0}])


def test_floats_are_rounded():
    assert normalize_rows([{"avg": 31.00001}]) == normalize_rows([{"avg": 31.000011}])
    assert normalize_rows([{"avg": 31.1}]) != normalize_rows([{"avg": 31.2}])


def test_json_round_trip_preserves_equality():
    rows = normalize_rows(
        [{"id": 1, "name": "x", "ok": True, "avg": 2.5, "none": None}]
    )
    assert json.loads(json.dumps(rows)) == rows


def test_cardinality_mismatch_is_caught():
    assert normalize_rows([{"a": 1}]) != normalize_rows([{"a": 1}, {"a": 1}])
