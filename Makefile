SCALE ?= 1000
SEED ?= 0
ENGINES ?= issundb,ladybug,lance-graph,neo4j
ROUNDS ?= 10
WARMUP ?= 3

.PHONY: help gen engines run report issundb neo4j-up neo4j-down clean setup-hooks test-hooks

help:
	@echo "graphbench targets:"
	@echo "  make gen SCALE=10000      # Generate a synthetic graph dataset (SCALE=number of nodes)"
	@echo "  make engines               # List which graph database engines are available"
	@echo "  make run [ENGINES=issundb,ladybug]  # Run the benchmark for specified engines (default: all)"
	@echo "  make report                # Generate a report from the results in the results/ directory"
	@echo "  make neo4j-up or neo4j-down # Start and stop the Neo4j container"
	@echo "  make setup-hooks           # Install Git hooks (pre-commit and pre-push)"
	@echo "  make test-hooks            # Test Git hooks on all files"
	@echo "  make clean                 # Remove generated data, temp files, results, etc."

gen:
	graphbench gen --scale $(SCALE) --seed $(SEED)

engines:
	graphbench engines

run:
	graphbench run --engines "$(ENGINES)" --rounds $(ROUNDS) --warmup $(WARMUP)

report:
	graphbench report

neo4j-up:
	docker compose -f deploy/neo4j-compose.yml up -d

neo4j-down:
	docker compose -f deploy/neo4j-compose.yml down

clean:
	rm -rf data work results/*.json results/*.png results/*.md

setup-hooks: ## Install Git hooks (pre-commit and pre-push)
	@echo "Setting up Git hooks..."
	@if ! command -v pre-commit &> /dev/null; then \
		echo "pre-commit not found. Please install it using 'pip install pre-commit'"; \
		exit 1; \
	fi
	@pre-commit install --hook-type pre-commit
	@pre-commit install --hook-type pre-push
	@pre-commit install-hooks

test-hooks: ## Test Git hooks on all files
	@echo "Testing Git hooks..."
	@pre-commit run --all-files
