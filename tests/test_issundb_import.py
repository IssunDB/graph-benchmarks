"""Unit tests for the IssunDB import-report verification.

The check guards against the silent misclassification found in 0.1.0a15,
where an edge file with legacy endpoint keys imported as nodes and the
benchmark ran against an edgeless graph.
"""

import pytest

from graphbench.engines.issundb_engine import _verify_import_counts

EXPECTED = {
    "Person": ("nodes", 3),
    "FOLLOWS": ("relationships", 2),
}


def payload(records):
    return {
        "columns": ["target", "kind", "count"],
        "records": [{"values": list(v)} for v in records],
    }


def test_matching_report_passes():
    _verify_import_counts(
        payload([("Person", "nodes", 3), ("FOLLOWS", "relationships", 2)]),
        EXPECTED,
    )


def test_misclassified_edge_file_raises():
    with pytest.raises(RuntimeError, match="FOLLOWS"):
        _verify_import_counts(
            payload([("Person", "nodes", 3), ("FOLLOWS", "nodes", 2)]),
            EXPECTED,
        )


def test_short_count_raises():
    with pytest.raises(RuntimeError, match="FOLLOWS"):
        _verify_import_counts(
            payload([("Person", "nodes", 3), ("FOLLOWS", "relationships", 0)]),
            EXPECTED,
        )


def test_missing_target_raises():
    with pytest.raises(RuntimeError, match="FOLLOWS"):
        _verify_import_counts(payload([("Person", "nodes", 3)]), EXPECTED)


def test_legacy_result_shape_is_skipped():
    _verify_import_counts(
        {"columns": ["imported"], "records": [{"values": [True]}]},
        EXPECTED,
    )
