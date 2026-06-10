"""Neo4j adapter.

Neo4j is a client-server engine reached over Bolt, so it requires a running server
(see the Docker compose file in `deploy/`). Connection settings come from the
environment: NEO4J_URI (default bolt://localhost:7687), NEO4J_USER (default neo4j),
and NEO4J_PASSWORD (default password).

Ingestion creates a uniqueness constraint per label, then batches `UNWIND` + `MERGE`
for nodes and edges. The dataset id is stored as the `id` property on every node, so
the catalog's Cypher (which filters on `id`) is identical to the other engines and
never touches Neo4j's internal element id.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pyarrow.parquet as pq

from ..queries import Query
from ..schema import Schema
from .base import BuildResult, Engine, EngineInfo, Record

BATCH_SIZE = 50_000


def _chunks(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class Neo4jEngine(Engine):
    name = "neo4j"

    def __init__(self, schema: Schema, workdir: Path):
        super().__init__(schema, workdir)
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._session = self._driver.session(database="neo4j")

    @classmethod
    def probe(cls) -> EngineInfo:
        try:
            import neo4j
        except Exception as exc:  # pragma: no cover - environment dependent
            return EngineInfo(cls.name, "", False, str(exc))
        return EngineInfo(cls.name, getattr(neo4j, "__version__", "unknown"), True)

    def _reset(self) -> None:
        self._session.run("MATCH (n) DETACH DELETE n")
        for label in self.schema.nodes:
            self._session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label.name}) "
                f"REQUIRE n.{self.schema.id_column} IS UNIQUE"
            )

    def build(self, data_dir: Path) -> BuildResult:
        self._reset()
        id_col = self.schema.id_column

        nodes_start = time.perf_counter()
        for label in self.schema.nodes:
            rows = pq.read_table(
                data_dir / "nodes" / f"{label.name}.parquet"
            ).to_pylist()
            query = (
                f"UNWIND $rows AS row MERGE (n:{label.name} {{{id_col}: row.{id_col}}}) "
                "SET n += row"
            )
            for batch in _chunks(rows, BATCH_SIZE):
                self._session.run(query, rows=batch)
        nodes_seconds = time.perf_counter() - nodes_start

        edges_start = time.perf_counter()
        for rel in self.schema.rels:
            rows = pq.read_table(data_dir / "edges" / f"{rel.name}.parquet").to_pylist()
            query = (
                f"UNWIND $rows AS row "
                f"MATCH (a:{rel.src} {{{id_col}: row.{self.schema.src_column}}}) "
                f"MATCH (b:{rel.dst} {{{id_col}: row.{self.schema.dst_column}}}) "
                f"MERGE (a)-[:{rel.name}]->(b)"
            )
            for batch in _chunks(rows, BATCH_SIZE):
                self._session.run(query, rows=batch)
        edges_seconds = time.perf_counter() - edges_start
        return BuildResult(nodes_seconds, edges_seconds)

    def run(self, query: Query) -> list[Record]:
        return self._session.run(query.cypher).data()

    def close(self) -> None:
        self._session.close()
        self._driver.close()
