## Contribution Guidelines

Thank you for considering contributing to the project.
Contributions are welcome.

### How to Contribute

Please check the [issue tracker](https://github.com/IssunDB/graph-benchmarks/issues) to see whether there is an issue you would like to work on or
whether it has already been resolved.

#### Reporting Bugs

1. Open an issue on the [issue tracker](https://github.com/IssunDB/graph-benchmarks/issues).
2. Include steps to reproduce, expected behavior, actual behavior, environment details, and relevant logs or screenshots.
3. For benchmark bugs, include the command you ran, selected engines, dataset scale, seed, and result files when possible.

#### Suggesting Features

1. Open an issue on the [issue tracker](https://github.com/IssunDB/graph-benchmarks/issues).
2. Provide the feature goal, expected output, affected engines, and any methodology concerns.

### Submitting Pull Requests

- Make sure relevant tests pass before submitting a pull request.
- Write a clear description of the behavior change and the reason for it.
- Mention any optional engines you could not test locally.

> [!IMPORTANT]
> If you use an AI-assisted coding tool like Claude Code or Codex, make sure it follows the instructions in the root [AGENTS.md](AGENTS.md) file.

### Development Workflow

#### Architecture Considerations

Graph Benchmarks is organized around a small benchmark pipeline:

1. Dataset generation in `graphbench/dataset.py`.
2. Query definitions in `graphbench/queries.py`.
3. Engine-independent correctness checks in `graphbench/oracle.py`.
4. Engine adapters in `graphbench/engines/`.
5. Benchmark orchestration in `graphbench/runner.py`.
6. Report generation in `graphbench/report.py`.

Keep engine-specific behavior inside the relevant adapter.
Shared benchmark semantics belong in the query catalog, oracle, runner, and tests.
Correctness failures should remain visible in results and reports.

#### Code Style

- Use the existing Python style in `graphbench/`.
- Keep changes small and focused.
- Use deterministic ordering for generated data, reports, and tests.
- Use `make test` to run the test suite.

#### Running Tests

```bash
make test
```

#### Local Benchmark Smoke Test

```bash
make gen SCALE=1000
make run ENGINES=issundb MIN_ROUNDS=3 TIME_BUDGET=0.2 WARMUP=1
```

Optional engines may require extra dependencies or services.
Use `make engines` to check what is available in your environment.

#### Neo4j

Neo4j benchmark runs require Docker:

```bash
make neo4j-up
make neo4j-down
```

#### See Available Commands

```bash
make help
```

### Code of Conduct

We adhere to the project's [Code of Conduct](CODE_OF_CONDUCT.md).
