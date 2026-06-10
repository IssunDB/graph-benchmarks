## Graph Benchmarks

[![Python version](https://img.shields.io/badge/python-%3E=3.10-3776ab?style=flat&labelColor=282c34&logo=python)](https://github.com/IssunDB/issun-db)
[![License: MIT](https://img.shields.io/badge/license-MIT-ffd343?style=flat&labelColor=282c34&logo=open-source-initiative)](LICENSE)

This repository includes a collection of graph benchmarks to compare the performance of a few graph databases
against IssunDB.

### Benchmarked Graph Databases

| # | Database        | Project Repository or Website                                 |
|---|-----------------|---------------------------------------------------------------|
| 1 | **IssunDB**     | [IssunDB/issun-db](https://github.com/IssunDB/issun-db)       |
| 2 | **LadybugDB**   | [LadybugDB/ladybug](https://github.com/LadybugDB/ladybug)     |
| 3 | **Lance-graph** | [lancedb/lance-graph](https://github.com/lancedb/lance-graph) |
| 4 | **Neo4j**       | [neo4j.com](https://neo4j.com/)                               |

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
aggregations, filter-joins, and path counting.
Each query is categorized by its primary operation type.
See the [query definitions](graphbench/queries.py) for more details.

| # | Query Name                     | Category      | Description                                                                   |
|---|--------------------------------|---------------|-------------------------------------------------------------------------------|
| 1 | **point_lookup**               | `point`       | Look up a single person by id.                                                |
| 2 | **one_hop_neighbors**          | `expand`      | List the people a given person follows.                                       |
| 3 | **top_followed**               | `aggregation` | Top 3 most-followed people.                                                   |
| 4 | **top_followed_city**          | `aggregation` | City of the single most-followed person.                                      |
| 5 | **youngest_cities_in_country** | `aggregation` | 5 cities in a country with the lowest average age, over a 3-hop chain.        |
| 6 | **age_band_by_country**        | `aggregation` | Count of people aged 30-40 per country, over a 3-hop chain.                   |
| 7 | **interest_gender_by_city**    | `filter_join` | Top cities by count of male people with a given interest (using multi-MATCH). |
| 8 | **two_hop_paths**              | `path_count`  | Count of length-2 FOLLOWS paths (self-join on the middle node).               |
| 9 | **two_hop_paths_filtered**     | `path_count`  | Length-2 FOLLOWS paths filtered on intermediate and destination age.          |

---

### Quickstart

#### 1. Prerequisites

- **Python**: Version `3.10` or newer.
- **Docker**: Needed if you want to benchmark **Neo4j**.
- **uv**: (Recommended).

#### 2. Setting up the Environment

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

#### 3. Setting up Neo4j

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

---

### Reporting Bugs

Please report bugs and issues you encounter via the [issue page](https://github.com/IssunDB/graph-benchmarks/issues).

### License

This project is licensed under the MIT License (see [LICENSE](LICENSE)).

