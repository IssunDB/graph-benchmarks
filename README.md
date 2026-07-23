## Graph Benchmarks

[![Tests](https://img.shields.io/github/actions/workflow/status/IssunDB/graph-benchmarks/tests.yml?label=tests&style=flat&labelColor=282c34&logo=github)](https://github.com/IssunDB/graph-benchmarks/actions/workflows/tests.yml)
[![Code Coverage](https://img.shields.io/codecov/c/github/IssunDB/graph-benchmarks?label=coverage&style=flat&labelColor=282c34&logo=codecov)](https://codecov.io/gh/IssunDB/graph-benchmarks)
[![Python Version](https://img.shields.io/badge/python-%3E=3.10-3776ab?style=flat&labelColor=282c34&logo=python)](https://github.com/IssunDB/graph-benchmarks)
[![License](https://img.shields.io/badge/license-MIT-3776ab?style=flat&labelColor=282c34&logo=open-source-initiative)](LICENSE)

This repository includes a collection of graph benchmarks to compare the performance of a few graph databases against IssunDB.

### Benchmarked Graph Databases

| # | Database        | Project Repository or Website                                 |
|---|-----------------|---------------------------------------------------------------|
| 1 | **IssunDB**     | [IssunDB/issun-db](https://github.com/IssunDB/issun-db)       |
| 2 | **LadybugDB**   | [LadybugDB/ladybug](https://github.com/LadybugDB/ladybug)     |
| 3 | **Lance-graph** | [lancedb/lance-graph](https://github.com/lancedb/lance-graph) |
| 4 | **Neo4j**       | [neo4j.com](https://neo4j.com/)                               |

> [!NOTE]
> Technically `Lance-graph` is not a graph database, but an in-memory graph query engine over Apache Arrow tables.
> In this repository when the word `engine` or `graph engine` are used, it referse to `Lance-graph` plus the other graph databases in the table above.

### Schema and Queries

#### Benchmark Graph Dataset

Benchmark dataset is a synthetic property graph with the following schema representations (property graph and relational):

<div align="center">
  <picture>
    <img alt="PG Schema" src="assets/diagrams/schema-pg.svg" height="80%" width="80%">
  </picture>
</div>

<div align="center">
  <picture>
    <img alt="Relational Schema" src="assets/diagrams/schema-rel.svg" height="80%" width="80%">
  </picture>
</div>

#### Benchmark Queries

The benchmark queries cover a range of graph query patterns, including point lookups, neighborhood expansions,
aggregations, filter-joins, path counting, and variable-length traversal.
Each query is categorized by its primary operation type.
See the [query definitions](graphbench/queries.py) for more details.

| #  | Query Name                     | Category      | Description                                                              |
|----|--------------------------------|---------------|--------------------------------------------------------------------------|
| 1  | **point_lookup**               | `point`       | Look up a single person by id.                                           |
| 2  | **one_hop_neighbors**          | `expand`      | List the people a given person follows.                                  |
| 3  | **top_followed**               | `aggregation` | Top three most-followed people.                                          |
| 4  | **top_followed_city**          | `aggregation` | City of the single most-followed person.                                 |
| 5  | **youngest_cities_in_country** | `aggregation` | Five cities in a country with the lowest average age.                    |
| 6  | **age_band_by_country**        | `aggregation` | Count of people aged 30-40 per country.                                  |
| 7  | **interest_gender_by_city**    | `filter_join` | Top cities by count of male people with a given interest.                |
| 8  | **two_hop_paths**              | `path_count`  | Count of length-2 FOLLOWS paths.                                         |
| 9  | **two_hop_paths_filtered**     | `path_count`  | Length-2 FOLLOWS paths filtered on intermediate and destination age.     |
| 10 | **follows_reach**              | `var_path`    | Distinct people reachable from a person via 1..2 FOLLOWS hops (`*1..2`). |

### Methodology

To ensure reproducible, objective, and comparable performance metrics, the benchmark suite follows these practices:

- **Correctness oracle**: Every query is re-implemented in [`graphbench/oracle.py`](graphbench/oracle.py) using Polars. Engine result rows are diffed
  against this oracle to verify correctness before timing, and mismatching queries fail validation.
- **Process isolation**: Each engine executes queries in a dedicated worker process ([`graphbench/_worker.py`](graphbench/_worker.py)) to prevent
  cache, allocator, and heap contamination.
- **Statistical rigor**: Query timing runs with the garbage collector disabled until a minimum round count and a time budget are met. Reports display
  the median latency, a distribution-free 95% confidence interval, and p25 to p75 error bars. Cold runs are measured and reported separately.
- **Categorization**: Engines are categorized by architecture (embedded, in-memory, or client-server) and ingestion method. Latency reports include
  network round-trip caveats for client-server engines and log live server settings.
- **Index disclosure**: Engine index models are documented (such as IssunDB auto-indexing, Neo4j range indexing, LadybugDB primary key indexing, and
  Lance-graph no-indexing) to provide context for query latency differences.
- **Determinism**: Datasets are generated from a single seed, and edge rows are shuffled to eliminate insertion-order locality benefits. CPU, core
  count, and RAM specifications are saved with every run.
- **Multi-scale scaling**: The suite measures scaling characteristics by running a sweep across dataset sizes rather than relying on a single-point
  snapshot.

#### Scope and Limitations

The suite currently measures single-threaded read-only latency.
Concurrent throughput, write workloads, and update workloads are out of scope.
Unsupported queries are reported as errors rather than being omitted.

> [!IMPORTANT]
> Benchmarking different systems (with different design philosophies, architectures, feature sets, etc.) is not straightforward and is tricky.
> Given that it is recommended to run the benchmarks on your environment (or machine) and interpret the results carefully,
> considering the limitations mentioned above and specific requirements of your use case.

---

### Quickstart

#### 1. Prerequisites

- **Python**: Version `3.10` or newer.
- **Docker**: Needed if you want to benchmark **Neo4j**.
- **uv**: (Recommended).

#### 2. Setting Up the Environment

```bash
git clone https://github.com/IssunDB/graph-benchmarks.git
cd graph-benchmarks
```

```bash
uv sync --all-extras
```

```bash
source .venv/bin/activate
make help
```

#### 3. Setting Up Neo4j

You need to have Docker installed on your machine for this step.

```bash
make neo4j-up
```

```bash
make neo4j-down
```

#### 4. Running the Benchmarks

##### Step A: Generate Synthetic Dataset

```bash
# Generate a benchmark dataset with 1000 Person nodes
make gen SCALE=1000
```

##### Step B: Run the Queries

```bash
# Run the benchmarks with default parameters
make run
```

##### Step C: Check the Results

All results are saved in the `results/` directory.

##### Optional: Scaling Sweep

```bash
# Generate and benchmark a series of scales, then plot scaling curves
make sweep SCALES=1000,10000,100000
```

#### 5. Running the Tests

```bash
make test
```

---

### Reporting Bugs

Please report bugs and issues you encounter via the [issue page](https://github.com/IssunDB/graph-benchmarks/issues).

### License

This project is licensed under the MIT License (see [LICENSE](LICENSE)).
