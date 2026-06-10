"""Declarative schema for the synthetic social graph.

The schema is intentionally small but exercises the patterns graph engines are
benchmarked on: a self-referential `FOLLOWS` relation with a power-law degree
distribution (the path-count workload), and a Person -> City -> State -> Country
hierarchy plus a Person -> Interest relation (the multi-hop join and aggregation
workload).

All identifiers and property names are lower case so the same Cypher text runs on
every engine, including the ones that fold identifiers to lower case.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeLabel:
    """One node label and its property columns. `id` is always the primary key."""

    name: str
    properties: tuple[str, ...]


@dataclass(frozen=True)
class RelType:
    """One relationship type and the labels it connects (src -> dst)."""

    name: str
    src: str
    dst: str


@dataclass(frozen=True)
class Schema:
    nodes: tuple[NodeLabel, ...]
    rels: tuple[RelType, ...]
    # Property name carrying the primary key on every node table.
    id_column: str = "id"
    # Endpoint column names on every edge table.
    src_column: str = "src"
    dst_column: str = "dst"

    def node(self, name: str) -> NodeLabel:
        for label in self.nodes:
            if label.name == name:
                return label
        raise KeyError(name)

    @property
    def node_names(self) -> tuple[str, ...]:
        return tuple(label.name for label in self.nodes)

    @property
    def rel_names(self) -> tuple[str, ...]:
        return tuple(rel.name for rel in self.rels)


SOCIAL = Schema(
    nodes=(
        NodeLabel("Person", ("id", "name", "gender", "age", "is_married")),
        NodeLabel("City", ("id", "name", "state", "country", "population")),
        NodeLabel("State", ("id", "name", "country")),
        NodeLabel("Country", ("id", "name")),
        NodeLabel("Interest", ("id", "name")),
    ),
    rels=(
        RelType("FOLLOWS", "Person", "Person"),
        RelType("LIVES_IN", "Person", "City"),
        RelType("HAS_INTEREST", "Person", "Interest"),
        RelType("CITY_IN", "City", "State"),
        RelType("STATE_IN", "State", "Country"),
    ),
)
