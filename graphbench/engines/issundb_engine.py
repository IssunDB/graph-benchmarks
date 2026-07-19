"""IssunDB adapter.

IssunDB is an embedded engine with a bulk `IMPORT DATABASE` path, so ingestion is one
import call over a generated Parquet/JSONL bundle rather than per-row inserts. IssunDB
allocates its own NodeId per node, so the build offsets each label's dataset id into a
globally unique `_id` (the imported NodeId) while keeping the original `id` as a node
property, and resolves edge endpoints through the same offsets. The `id` property is
what the catalog's Cypher filters on; IssunDB auto-indexes every scalar node property,
so those filters become index/range scans with no explicit index DDL (an explicit
node `CREATE INDEX` would provision a full-text index instead, which the workload does
not use). The binding returns query results as JSON of the shape
`{"columns": [...], "records": [{"values": [...]}]}`.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


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
        self._db = IssunDB(str(self._db_path), map_size_gb=16)

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
        n_node_rows = 0
        for label in self.schema.nodes:
            parquet_path = data_dir / "nodes" / f"{label.name}.parquet"
            dst_parquet = import_dir / f"{label.name}.parquet"
            df = pl.read_parquet(parquet_path)
            n_node_rows += df.height
            df = df.with_columns(
                (
                    pl.col(self.schema.id_column).cast(pl.Int64) + offsets[label.name]
                ).alias("_id")
            )
            df.write_parquet(dst_parquet)
        nodes_prep_time = time.perf_counter() - nodes_prep_start

        # 4. Convert and write edge tables with offset endpoints
        edges_start = time.perf_counter()
        n_edge_rows = 0
        for rel in self.schema.rels:
            parquet_path = data_dir / "edges" / f"{rel.name}.parquet"
            jsonl_path = import_dir / f"{rel.name}.jsonl"
            df = pl.read_parquet(parquet_path)
            n_edge_rows += df.height
            df = df.with_columns(
                [
                    (
                        pl.col(self.schema.src_column).cast(pl.Int64) + offsets[rel.src]
                    ).alias("_from"),
                    (
                        pl.col(self.schema.dst_column).cast(pl.Int64) + offsets[rel.dst]
                    ).alias("_to"),
                ]
            )
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

        # `IMPORT DATABASE` is a single bulk call whose internal node and edge phases
        # are not separately measurable, so its time is apportioned across the two
        # reported phases by row volume (not an arbitrary 50/50 split). Each phase
        # also carries its own deterministic preparation cost (the offset rewrite and
        # the JSONL conversion), which is genuinely per-phase and measured directly.
        total_rows = n_node_rows + n_edge_rows
        node_frac = n_node_rows / total_rows if total_rows else 0.5
        nodes_seconds = nodes_prep_time + query_time * node_frac
        edges_seconds = edges_prep_time + query_time * (1.0 - node_frac)

        return BuildResult(nodes_seconds, edges_seconds)

    def run(self, cypher: str) -> list[Record]:
        payload = json.loads(self._db.query(cypher))
        columns = payload["columns"]
        return [dict(zip(columns, record["values"])) for record in payload["records"]]
