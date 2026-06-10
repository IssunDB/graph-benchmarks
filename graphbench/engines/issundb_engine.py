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
    build_method = "IMPORT DATABASE (bulk COPY from Parquet and JSONL)"

    def __init__(self, schema: Schema, workdir: Path):
        super().__init__(schema, workdir)
        from issundb import IssunDB

        self._db_path = workdir / "social.issundb"
        if self._db_path.exists():
            shutil.rmtree(self._db_path)
        self._db = IssunDB(str(self._db_path))

    @classmethod
    def probe(cls) -> EngineInfo:
        try:
            import issundb
        except Exception as exc:  # pragma: no cover - environment dependent
            return EngineInfo(cls.name, "", False, str(exc))
        return EngineInfo(cls.name, package_version(issundb, "issundb"), True)

    def build(self, data_dir: Path) -> BuildResult:
        import polars as pl

        # 1. Prepare temp directory for IMPORT DATABASE
        import_dir = (self.workdir / "import_tmp").resolve()
        if import_dir.exists():
            shutil.rmtree(import_dir)
        import_dir.mkdir(parents=True, exist_ok=True)

        # 2. Compute dynamic offsets based on maximum node IDs
        nodes_prep_start = time.perf_counter()
        offsets = {}
        current_offset = 0
        for label in self.schema.nodes:
            parquet_path = data_dir / "nodes" / f"{label.name}.parquet"
            df = pl.read_parquet(parquet_path)
            max_id = df[self.schema.id_column].max()
            offsets[label.name] = current_offset
            current_offset += (max_id if max_id is not None else 0) + 1

        # 3. Process and write node Parquet files with _id column
        for label in self.schema.nodes:
            parquet_path = data_dir / "nodes" / f"{label.name}.parquet"
            dst_parquet = import_dir / f"{label.name}.parquet"
            df = pl.read_parquet(parquet_path)
            df = df.with_columns(
                (pl.col(self.schema.id_column).cast(pl.Int64) + offsets[label.name]).alias("_id")
            )
            df.write_parquet(dst_parquet)
        nodes_prep_time = time.perf_counter() - nodes_prep_start

        # 4. Convert and write edge tables with offset endpoints
        edges_start = time.perf_counter()
        for rel in self.schema.rels:
            parquet_path = data_dir / "edges" / f"{rel.name}.parquet"
            jsonl_path = import_dir / f"{rel.name}.jsonl"
            df = pl.read_parquet(parquet_path)
            df = df.with_columns([
                (pl.col(self.schema.src_column).cast(pl.Int64) + offsets[rel.src]).alias("from"),
                (pl.col(self.schema.dst_column).cast(pl.Int64) + offsets[rel.dst]).alias("to")
            ])
            # Drop original src/dst columns to avoid importing them as edge properties
            df = df.drop([self.schema.src_column, self.schema.dst_column])
            df.write_ndjson(jsonl_path)
        edges_prep_time = time.perf_counter() - edges_start

        # 5. Create empty schema.cypher and write copy.cypher
        (import_dir / "schema.cypher").touch()

        copy_lines = []
        for label in self.schema.nodes:
            parquet_path = import_dir / f"{label.name}.parquet"
            copy_lines.append(f"COPY {label.name} FROM '{parquet_path}';")

        for rel in self.schema.rels:
            jsonl_path = import_dir / f"{rel.name}.jsonl"
            copy_lines.append(f"COPY {rel.name} FROM '{jsonl_path}';")

        (import_dir / "copy.cypher").write_text("\n".join(copy_lines))

        # 6. Execute IMPORT DATABASE
        query_start = time.perf_counter()
        self._db.query(f"IMPORT DATABASE '{import_dir}'")
        query_time = time.perf_counter() - query_start

        # Clean up import temp files
        shutil.rmtree(import_dir)

        # Split query time and attribute preparation to edges_seconds and nodes_seconds
        nodes_seconds = nodes_prep_time + query_time * 0.5
        edges_seconds = edges_prep_time + query_time * 0.5

        return BuildResult(nodes_seconds, edges_seconds)


    def run(self, cypher: str) -> list[Record]:
        payload = json.loads(self._db.query(cypher))
        columns = payload["columns"]
        return [dict(zip(columns, record["values"])) for record in payload["records"]]
