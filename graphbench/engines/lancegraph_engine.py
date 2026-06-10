"""lance-graph adapter.

lance-graph is an embedded, Cypher-capable engine that executes over in-memory Arrow
tables via a `GraphConfig` mapping. There is no persistent database to build: ingestion
just reads the Parquet tables into memory and constructs the config; queries execute
against that table dict.
"""

from __future__ import annotations

import time
from pathlib import Path

import pyarrow.parquet as pq

from ..queries import Query
from ..schema import Schema
from .base import BuildResult, Engine, EngineInfo, Record


class LanceGraphEngine(Engine):
    name = "lance-graph"

    def __init__(self, schema: Schema, workdir: Path):
        super().__init__(schema, workdir)
        from lance_graph import GraphConfig

        builder = GraphConfig.builder()
        for label in schema.nodes:
            builder = builder.with_node_label(label.name, schema.id_column)
        for rel in schema.rels:
            builder = builder.with_relationship(
                rel.name, schema.src_column, schema.dst_column
            )
        self._config = builder.build()
        self._tables: dict[str, object] = {}

    @classmethod
    def probe(cls) -> EngineInfo:
        try:
            import lance_graph
        except Exception as exc:  # pragma: no cover - environment dependent
            return EngineInfo(cls.name, "", False, str(exc))
        return EngineInfo(
            cls.name, getattr(lance_graph, "__version__", "unknown"), True
        )

    def build(self, data_dir: Path) -> BuildResult:
        nodes_start = time.perf_counter()
        for label in self.schema.nodes:
            self._tables[label.name] = pq.read_table(
                data_dir / "nodes" / f"{label.name}.parquet"
            )
        nodes_seconds = time.perf_counter() - nodes_start

        edges_start = time.perf_counter()
        for rel in self.schema.rels:
            self._tables[rel.name] = pq.read_table(
                data_dir / "edges" / f"{rel.name}.parquet"
            )
        edges_seconds = time.perf_counter() - edges_start
        return BuildResult(nodes_seconds, edges_seconds)

    def run(self, query: Query) -> list[Record]:
        from lance_graph import CypherQuery

        result = (
            CypherQuery(query.cypher).with_config(self._config).execute(self._tables)
        )
        # Result is an Arrow Table or RecordBatch; normalize to a list of row dicts.
        if hasattr(result, "to_pylist"):
            return result.to_pylist()
        if hasattr(result, "to_pydict"):
            pydict = result.to_pydict()
            columns = list(pydict)
            length = len(next(iter(pydict.values()))) if pydict else 0
            return [{col: pydict[col][i] for col in columns} for i in range(length)]
        raise TypeError(f"Unsupported lance-graph result type: {type(result)}")
