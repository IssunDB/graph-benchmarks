"""Common engine adapter interface.

Every engine is driven through the same three operations: `build` (ingest a dataset
and report load timings), `run` (execute one Cypher statement and return rows for
correctness comparison), and `close`. Result normalization lives here so all engines
are compared on equal footing regardless of their native return type.

Adapters also declare two pieces of reporting metadata: `kind` classifies the
deployment model ("embedded" persistent engine, "in-memory" engine with no
persistent build, or client-"server" engine reached over a network protocol), and
`build_method` describes in one line how ingestion is performed. Both are surfaced
in the report so load times and latencies are never compared across architectures
without that context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

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


def package_version(module: object, dist_name: str) -> str:
    """Best-effort version of an engine's client: `__version__`, then dist metadata."""
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    try:
        from importlib import metadata

        return metadata.version(dist_name)
    except Exception:
        return "unknown"


def normalize_value(value: object) -> object:
    """Coerce a single cell to a comparable, engine-independent value.

    All numbers become rounded floats so an engine returning ints where another
    returns floats (e.g. for counts) still compares equal — including after a JSON
    round-trip through the worker process boundary.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), FLOAT_DECIMALS)
    if value is None:
        return None
    return str(value)


def normalize_rows(rows: list[Record]) -> list:
    """Normalize each row to a column-sorted list of [column, value] pairs, then sort rows.

    Keying by column name makes comparison independent of column order, and sorting
    rows makes it independent of row order. Ordered (top-k) queries are thus compared
    as a multiset: this catches value and cardinality mismatches without making the
    gate brittle to tie-break order, which legitimately differs across engines.

    The result is JSON-native (lists, not tuples), so a round-trip through the worker
    process boundary preserves equality.
    """
    normalized = [
        sorted([str(col), normalize_value(val)] for col, val in row.items())
        for row in rows
    ]
    return sorted(normalized, key=repr)


class Engine(ABC):
    """Base class for an engine adapter. Subclasses set the class metadata fields."""

    name: str = "engine"
    # One of "embedded" (persistent, in-process), "in-memory", or "server".
    kind: str = "embedded"
    # One-line description of the ingestion path, surfaced in the report.
    build_method: str = ""

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
    def run(self, cypher: str) -> list[Record]:
        """Execute one Cypher statement and return rows as {column: value} dicts."""

    def server_info(self) -> dict:
        """Server-side configuration relevant to performance (empty for embedded)."""
        return {}

    def close(self) -> None:  # noqa: B027 - optional override
        """Release resources. Default is a no-op."""
