"""Ladybug adapter.

Ladybug is an embedded engine (the maintained Kuzu successor) with a bulk `COPY`
path, so ingestion is DDL plus one `COPY ... FROM <parquet>` per table. DDL and COPY
go through the async connection; queries go through the sync connection.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .base import BuildResult, Engine, EngineInfo, Record, package_version
from ..schema import Schema

# Map property name -> Ladybug/Cypher column type.
_TYPE_BY_PROP = {
    "id": "INT64",
    "name": "STRING",
    "gender": "STRING",
    "age": "INT64",
    "is_married": "BOOLEAN",
    "state": "STRING",
    "country": "STRING",
    "population": "INT64",
}


class LadybugEngine(Engine):
    name = "ladybug"
    kind = "embedded"
    build_method = "DDL + bulk COPY ... FROM Parquet"

    def __init__(self, schema: Schema, workdir: Path):
        super().__init__(schema, workdir)
        import ladybug as lb

        self._lb = lb
        self._db_path = workdir / "social.lbdb"
        if self._db_path.exists():
            self._db_path.unlink()
        self._db = lb.Database(str(self._db_path))

    @classmethod
    def probe(cls) -> EngineInfo:
        try:
            import ladybug as lb
        except Exception as exc:  # pragma: no cover - environment dependent
            return EngineInfo(cls.name, "", False, str(exc))
        return EngineInfo(cls.name, package_version(lb, "ladybug"), True)

    def _node_ddl(self, label) -> str:
        cols = ", ".join(f"{p} {_TYPE_BY_PROP[p]}" for p in label.properties)
        return f"CREATE NODE TABLE {label.name}({cols}, PRIMARY KEY ({self.schema.id_column}))"

    async def _build_async(self, data_dir: Path) -> tuple[float, float]:
        conn = self._lb.AsyncConnection(self._db)
        nodes_start = time.perf_counter()
        for label in self.schema.nodes:
            await conn.execute(self._node_ddl(label))
        for label in self.schema.nodes:
            path = data_dir / "nodes" / f"{label.name}.parquet"
            await conn.execute(f"COPY {label.name} FROM '{path}'")
        nodes_seconds = time.perf_counter() - nodes_start

        edges_start = time.perf_counter()
        for rel in self.schema.rels:
            await conn.execute(
                f"CREATE REL TABLE {rel.name}(FROM {rel.src} TO {rel.dst})"
            )
        for rel in self.schema.rels:
            path = data_dir / "edges" / f"{rel.name}.parquet"
            await conn.execute(f"COPY {rel.name} FROM '{path}'")
        edges_seconds = time.perf_counter() - edges_start
        return nodes_seconds, edges_seconds

    def build(self, data_dir: Path) -> BuildResult:
        nodes_seconds, edges_seconds = asyncio.run(self._build_async(data_dir))
        self._conn = self._lb.Connection(self._db)
        return BuildResult(nodes_seconds, edges_seconds)

    def run(self, cypher: str) -> list[Record]:
        return self._conn.execute(cypher).get_as_pl().to_dicts()
