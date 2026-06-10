"""IssunDB adapter.

IssunDB is an embedded engine with no bulk COPY path, so nodes and edges are inserted
one row at a time through `add_node`/`add_edge`. IssunDB allocates its own NodeId per
node, so the build keeps a per-label map from the dataset id to the allocated NodeId
and resolves edge endpoints through it. The dataset id is stored as a node property so
queries can return it. The binding returns query results as JSON of the shape
`{"columns": [...], "records": [{"values": [...]}]}`.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pyarrow.parquet as pq

from .base import BuildResult, Engine, EngineInfo, Record, package_version
from ..schema import Schema


class IssunDBEngine(Engine):
    name = "issundb"
    kind = "embedded"
    build_method = "row-at-a-time add_node/add_edge (binding has no bulk-load path)"

    def __init__(self, schema: Schema, workdir: Path):
        super().__init__(schema, workdir)
        from issundb import IssunDB

        self._db_path = workdir / "social.issundb"
        if self._db_path.exists():
            shutil.rmtree(self._db_path)
        self._db = IssunDB(str(self._db_path))
        # Per-label map: dataset id -> allocated IssunDB NodeId.
        self._id_map: dict[str, dict[int, int]] = {}

    @classmethod
    def probe(cls) -> EngineInfo:
        try:
            import issundb
        except Exception as exc:  # pragma: no cover - environment dependent
            return EngineInfo(cls.name, "", False, str(exc))
        return EngineInfo(cls.name, package_version(issundb, "issundb"), True)

    def build(self, data_dir: Path) -> BuildResult:
        nodes_start = time.perf_counter()
        for label in self.schema.nodes:
            table = pq.read_table(data_dir / "nodes" / f"{label.name}.parquet")
            rows = table.to_pylist()
            mapping: dict[int, int] = {}
            for row in rows:
                node_id = self._db.add_node(label.name, json.dumps(row, default=str))
                mapping[int(row[self.schema.id_column])] = node_id
            self._id_map[label.name] = mapping
        nodes_seconds = time.perf_counter() - nodes_start

        edges_start = time.perf_counter()
        for rel in self.schema.rels:
            table = pq.read_table(data_dir / "edges" / f"{rel.name}.parquet")
            src_map = self._id_map[rel.src]
            dst_map = self._id_map[rel.dst]
            src_col = table.column(self.schema.src_column).to_pylist()
            dst_col = table.column(self.schema.dst_column).to_pylist()
            for src, dst in zip(src_col, dst_col):
                self._db.add_edge(src_map[int(src)], dst_map[int(dst)], rel.name, "{}")
        edges_seconds = time.perf_counter() - edges_start
        return BuildResult(nodes_seconds, edges_seconds)

    def run(self, cypher: str) -> list[Record]:
        payload = json.loads(self._db.query(cypher))
        columns = payload["columns"]
        return [dict(zip(columns, record["values"])) for record in payload["records"]]
