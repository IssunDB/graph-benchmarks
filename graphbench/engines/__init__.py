"""Engine adapter registry.

Adapter modules import their client library at module load, so they are imported
lazily through `get_engine_class` to keep an engine's absence from breaking the rest
of the suite. `probe` reports availability without constructing an instance.
"""

from __future__ import annotations

from .base import BuildResult, Engine, EngineInfo, Record, normalize_rows

# Public engine name -> (module, class name). Order is the default run order.
# Correctness is checked against the engine-independent oracle (see `oracle.py`),
# never against another engine.
_REGISTRY: dict[str, tuple[str, str]] = {
    "issundb": ("graphbench.engines.issundb_engine", "IssunDBEngine"),
    "ladybug": ("graphbench.engines.ladybug_engine", "LadybugEngine"),
    "lance-graph": ("graphbench.engines.lancegraph_engine", "LanceGraphEngine"),
    "neo4j": ("graphbench.engines.neo4j_engine", "Neo4jEngine"),
}

ALL_ENGINES = tuple(_REGISTRY)


def get_engine_class(name: str) -> type[Engine]:
    import importlib

    module_name, class_name = _REGISTRY[name]
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def probe(name: str) -> EngineInfo:
    try:
        return get_engine_class(name).probe()
    except Exception as exc:  # pragma: no cover - import-time failure
        return EngineInfo(name, "", False, str(exc))


__all__ = [
    "ALL_ENGINES",
    "BuildResult",
    "Engine",
    "EngineInfo",
    "Record",
    "get_engine_class",
    "normalize_rows",
    "probe",
]
