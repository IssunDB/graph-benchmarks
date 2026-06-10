"""Neo4j adapter.

Neo4j is a client-server engine reached over Bolt, so it requires a running server
(see the Docker compose file in `deploy/`). Connection settings come from the
environment: NEO4J_URI (default bolt://localhost:7687), NEO4J_USER (default neo4j),
and NEO4J_PASSWORD (default password).

Ingestion wipes the database, creates a uniqueness constraint per label, then batches
`UNWIND` + `CREATE` for nodes and edges (the dataset is pre-deduplicated and the
database starts empty, so the slower MERGE is unnecessary). The dataset id is stored
as the `id` property on every node, so the catalog's Cypher (which filters on `id`)
is identical to the other engines and never touches Neo4j's internal element id.

`server_info` reports the server's memory settings via SHOW SETTINGS so published
results carry the Neo4j configuration they were measured against.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pyarrow.parquet as pq

from .base import BuildResult, Engine, EngineInfo, Record, package_version
from ..schema import Schema

BATCH_SIZE = 50_000


def _chunks(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class Neo4jEngine(Engine):
    name = "neo4j"
    kind = "server"
    build_method = "batched UNWIND+CREATE over Bolt, uniqueness constraint per label"

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
        return EngineInfo(cls.name, package_version(neo4j, "neo4j"), True)

    def _reset(self) -> None:
        # Batched delete so a wipe at large scales does not exhaust the heap.
        self._session.run(
            "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 50000 ROWS"
        )
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
            query = f"UNWIND $rows AS row CREATE (n:{label.name}) SET n = row"
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
                f"CREATE (a)-[:{rel.name}]->(b)"
            )
            for batch in _chunks(rows, BATCH_SIZE):
                self._session.run(query, rows=batch)
        edges_seconds = time.perf_counter() - edges_start
        return BuildResult(nodes_seconds, edges_seconds)

    def run(self, cypher: str) -> list[Record]:
        return self._session.run(cypher).data()

    def server_info(self) -> dict:
        try:
            rows = self._session.run(
                "SHOW SETTINGS YIELD name, value "
                "WHERE name STARTS WITH 'server.memory' RETURN name, value"
            ).data()
            return {row["name"]: row["value"] for row in rows}
        except Exception:  # pragma: no cover - depends on server edition/version
            return {}

    def close(self) -> None:
        self._session.close()
        self._driver.close()
