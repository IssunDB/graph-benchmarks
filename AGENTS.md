# AGENTS.md

This file provides guidance to coding agents collaborating on this repository.

## Mission

Graph Benchmarks is a Python benchmark suite for comparing IssunDB with other graph databases.
It generates a reproducible synthetic property graph, runs a fixed Cypher query catalog, checks every engine against an independent oracle, and
reports latency and scaling results.

Priorities, in order:

1. Correctness of generated datasets, query semantics, oracle comparisons, and result normalization.
2. Reproducible benchmark methodology with deterministic inputs and recorded environment metadata.
3. Small, focused engine adapters that isolate database-specific behavior.
4. Clear reports that distinguish embedded, in-memory, and client-server engines.

## Core Rules

- Use English for code, comments, docs, and tests.
- Prefer small, focused changes over broad refactoring.
- Add comments only when they clarify non-obvious behavior.
- Do not add features, error handling, or abstractions beyond what is needed for the current task.
- Keep benchmark comparisons honest: do not rank unlike load paths, hide correctness failures, or remove failing queries from reports.
- Keep dependencies small. Do not add new benchmark engines, services, or heavy libraries without prior discussion.

## Writing Style

- Use Oxford commas in inline lists: "a, b, and c" not "a, b, c".
- Do not use em dashes. Restructure the sentence, or use a colon or semicolon instead.
- Avoid colorful adjectives and adverbs. Write "instruction decoder" not "elegant instruction decoder".
- Prefer using noun phrases for checklist items, not imperative verbs. Write "opcode timing table" not "build the opcode timing table".
- Headings in Markdown files must be in title case: "Build from Source" not "Build from source". Minor words (a, an, the, and, but, or, for, in, on,
  at, to, by, of) stay lowercase unless they are the first word.

## Repository Layout

- `graphbench/dataset.py`: Synthetic property graph generator and dataset manifest.
- `graphbench/schema.py`: Shared schema definitions.
- `graphbench/queries.py`: Benchmark query catalog and Cypher templates.
- `graphbench/oracle.py`: Engine-independent correctness oracle implemented over the raw Parquet data.
- `graphbench/runner.py`: Benchmark orchestration, correctness checks, timing loops, and environment capture.
- `graphbench/report.py`: Markdown reports and plots from benchmark results.
- `graphbench/cli.py`: `graphbench` command-line entry point.
- `graphbench/_worker.py`: Per-engine worker process used for isolation. Also owns the memory readings, taken at phase boundaries.
- `graphbench/_cold_worker.py`: One-query worker that attaches to an already-built database, so a cold run is measured in a process that did no
  ingestion and ran nothing else.
- `graphbench/engines/`: Engine adapter implementations for IssunDB, LadybugDB, Lance-graph, and Neo4j.
- `tests/`: Unit and integration tests for dataset generation, query definitions, normalization, oracle behavior, engine integration, and the two
  measurements whose validity is easy to break (`test_measurement.py`).
- `deploy/neo4j-compose.yml`: Local Neo4j service for client-server benchmark runs.
- `assets/diagrams/`: Schema diagrams and source files.
- `.github/workflows/tests.yml`: CI workflow for unit tests and a small smoke benchmark.

## Architecture

### Benchmark Flow

The CLI generates a dataset in Parquet form, then the runner loads it through each selected engine adapter.
Before timing matters, query results are checked against `graphbench/oracle.py`.
Timing uses warmup rounds, minimum round counts, time budgets, and per-engine worker processes so allocator state and caches do not leak across
engines.

### Engine Adapters

Engine-specific code belongs under `graphbench/engines/`.
Adapters should implement the shared engine interface in `base.py`, keep setup and query execution separate, and report unsupported features as errors
instead of silently skipping them.
The runner, oracle, and report layers should stay engine-neutral.

### Data and Queries

The dataset generator must remain deterministic for a given scale and seed.
Query definitions should keep placeholders explicit so probe values can rotate across timing rounds.
When changing a query, update the oracle and tests in the same change.

### Reports

Reports should preserve enough context to interpret the numbers: engine kind, load method, correctness status, latency distribution, confidence
interval, memory usage, hardware, and relevant caveats.
Do not remove correctness failures from summaries.

### Measurement Rules

Two measurements were reporting something other than what they claimed, and both are easy to reintroduce.

- Memory comes from `/proc/self/status`, `VmHWM` for a peak and `VmRSS` for a current reading. Do not go back to
  `resource.getrusage(RUSAGE_SELF).ru_maxrss`: that high-water mark is inherited through fork *and* exec, and because the runner builds the polars oracle
  before spawning any worker, every worker inherited the parent's multi-gigabyte peak. Three engines, one of them a bare network client, reported the same
  number to one decimal place. Record memory at phase boundaries (before build, after build, after queries) rather than as one peak, since the ingestion
  peak is the larger on every engine measured so far and hides the serving footprint, and reset the peak between the two phases through
  `clear_refs` where the kernel allows it.
- A cold run is measured in its own process, one per query, by `_cold_worker` attaching to the database the build left behind through
  `Engine.open_built`. Do not report the first execution inside the long-lived worker as a cold run: an engine arrives there already warmed by whatever
  its ingestion built eagerly (IssunDB's `IMPORT DATABASE` ends with a full CSR-snapshot rebuild, so that cost lands in load time) and by every earlier
  query. An `open_built` implementation must never delete or rebuild the artifacts, which is exactly what the normal constructor does; `tests/test_measurement.py`
  pins that by running two cold workers in a row. An engine with nothing persistent to reopen reports no cold figure rather than a misleading one, and the
  open is timed apart from the query so an engine that loads eagerly cannot look fast in one column and slow in none.
- Both numbers are cold in the process, not on disk: the database file stays in the page cache from the build, and dropping it needs privileges a
  benchmark should not ask for. Say so wherever the figures appear.

## Python Conventions

- Python version: `>=3.10,<4.0` as declared in `pyproject.toml`.
- Dependency management uses `uv`.
- Tests use `pytest`.
- Keep public CLI behavior stable unless the task explicitly changes it.
- Prefer `pathlib.Path`, typed function signatures where practical, and deterministic ordering in generated outputs.

## Required Validation

Run the relevant targets for any change:

| Target              | Command                                                          | What It Runs                                           |
|---------------------|------------------------------------------------------------------|--------------------------------------------------------|
| Unit tests          | `make test`                                                      | `pytest`                                               |
| Engine availability | `make engines`                                                   | Adapter discovery and version probes                   |
| Dataset generation  | `make gen SCALE=1000`                                            | Synthetic graph generation                             |
| Smoke benchmark     | `make run ENGINES=issundb MIN_ROUNDS=3 TIME_BUDGET=0.2 WARMUP=1` | Oracle gate and timing loop for one engine             |
| Scaling sweep       | `make sweep SCALES=1000,10000`                                   | Multi-scale benchmark and plot generation              |
| Report              | `make report`                                                    | Markdown report and latency plot from existing results |

## First Contribution Flow

1. Relevant module review under `graphbench/`.
2. Smallest behavior change that satisfies the requirement.
3. Focused tests for changed dataset, query, oracle, runner, report, or engine behavior.
4. `make test` validation.
5. Smoke benchmark validation when runner, oracle, query, or engine behavior changes.

## Testing Expectations

- Dataset changes need determinism tests and count/schema checks.
- Query changes need oracle updates and tests that exercise representative probe values.
- Engine adapter changes need availability behavior and normalization tests where possible.
- Report changes need tests or fixtures that cover missing values, errors, and unsupported queries.
- Correctness mismatches should fail tests or smoke checks rather than being hidden by report formatting.

## Change Design Checklist

Before coding:

1. Affected layer identification: dataset, query catalog, oracle, engine adapter, runner, report, or CLI.
2. Correctness oracle implications.
3. Result schema and backward-compatibility implications.
4. Reproducibility implications: seed, ordering, environment capture, or timing parameters.
5. Client-server caveats for Neo4j or other remote engines.

Before submitting:

1. `make test` passing status.
2. Smoke benchmark status when benchmark behavior changed.
3. Report output review when formatting changed.
4. Documentation updates for new commands, engines, options, or result fields.

## Commit and PR Hygiene

- Keep commits scoped to one logical change.
- PR descriptions should include:
    1. Behavioral change summary.
    2. Tests added or updated.
    3. Benchmark or smoke run status.
    4. Known caveats, especially skipped optional engines.
