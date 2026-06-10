"""Common engine adapter interface.

Every engine is driven through the same three operations: `build` (ingest a dataset
and report load timings), `run` (execute one query and return normalized rows for
correctness comparison), and `close`. Result normalization lives here so all engines
are compared on equal footing regardless of their native return type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..queries import Query
from ..schema import Schema

# An engine returns each result row as a {column_name: value} dict, so comparison is
# independent of the column order an engine chooses to emit.
Record = dict
FLOAT_DECIMALS = 4


@dataclass
class BuildResult:
    nodes_seconds: float
    edges_seconds: float

    @property
    def total_seconds(self) -> float:
        return self.nodes_seconds + self.edges_seconds


@dataclass
class EngineInfo:
    name: str
    version: str
    available: bool
    reason: str = ""


def normalize_value(value: object) -> object:
    """Coerce a single cell to a comparable, engine-independent value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, FLOAT_DECIMALS)
    if isinstance(value, int):
        return value
    if value is None:
        return None
    return str(value)


def normalize_rows(rows: list[Record]) -> list[tuple]:
    """Normalize each row to a sorted tuple of (column, value) pairs, then sort rows.

    Keying by column name makes comparison independent of column order, and sorting
    rows makes it independent of row order. Ordered (top-k) queries are thus compared
    as a multiset: this catches value and cardinality mismatches without making the
    gate brittle to tie-break order, which legitimately differs across engines.
    """
    normalized = [
        tuple(sorted((str(col), normalize_value(val)) for col, val in row.items()))
        for row in rows
    ]
    return sorted(normalized, key=repr)


class Engine(ABC):
    """Base class for an engine adapter. Subclasses set `name`."""

    name: str = "engine"

    def __init__(self, schema: Schema, workdir: Path):
        self.schema = schema
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)

    @classmethod
    @abstractmethod
    def probe(cls) -> EngineInfo:
        """Report whether the engine's client library is importable, and its version."""

    @abstractmethod
    def build(self, data_dir: Path) -> BuildResult:
        """Ingest the Parquet dataset under `data_dir`."""

    @abstractmethod
    def run(self, query: Query) -> list[Record]:
        """Execute `query` and return rows as {column: value} dicts (caller normalizes)."""

    def close(self) -> None:  # noqa: B027 - optional override
        """Release resources. Default is a no-op."""
