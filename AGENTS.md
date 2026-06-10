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
- Use noun phrases for checklist items, not imperative verbs. Write "opcode timing table" not "build the opcode timing table".
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
- `graphbench/_worker.py`: Per-engine worker process used for isolation.
- `graphbench/engines/`: Engine adapter implementations for IssunDB, LadybugDB, Lance-graph, and Neo4j.
- `tests/`: Unit and integration tests for dataset generation, query definitions, normalization, oracle behavior, and engine integration.
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
