"""The benchmark query catalog.

Each query is one Cypher string that runs verbatim on every engine. This is possible
because ingestion stores identical lower-case property names and relationship types
across all engines, and predicate values are inlined as literals (the IssunDB binding
has no query-parameter API, so parameters are avoided entirely rather than emulated
per engine).

Literal values (`Country_00`, `Interest_00`, person id 42, ...) are guaranteed to
exist by the deterministic generator; see `dataset.generate`'s probes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Query:
    name: str
    category: str
    description: str
    cypher: str
    # True when the query's meaning depends on row order (ORDER BY ... LIMIT). Results
    # are still compared as a multiset; this flag drives reporting only.
    ordered: bool = False


CATALOG: tuple[Query, ...] = (
    Query(
        name="point_lookup",
        category="point",
        description="Look up a single person by id.",
        cypher="MATCH (p:Person) WHERE p.id = 42 RETURN p.name AS name, p.age AS age",
    ),
    Query(
        name="one_hop_neighbors",
        category="expand",
        description="List the people a given person follows.",
        cypher=(
            "MATCH (p:Person)-[:FOLLOWS]->(f:Person) WHERE p.id = 42 "
            "RETURN f.id AS id ORDER BY id"
        ),
        ordered=True,
    ),
    Query(
        name="top_followed",
        category="aggregation",
        description="Top 3 most-followed people.",
        cypher=(
            "MATCH (f:Person)-[:FOLLOWS]->(p:Person) "
            "RETURN p.id AS id, p.name AS name, count(f.id) AS num "
            "ORDER BY num DESC, id LIMIT 3"
        ),
        ordered=True,
    ),
    Query(
        name="top_followed_city",
        category="aggregation",
        description="City of the single most-followed person.",
        cypher=(
            "MATCH (f:Person)-[:FOLLOWS]->(p:Person)-[:LIVES_IN]->(c:City) "
            "RETURN p.id AS id, count(f.id) AS num, c.name AS city "
            "ORDER BY num DESC, id LIMIT 1"
        ),
        ordered=True,
    ),
    Query(
        name="youngest_cities_in_country",
        category="aggregation",
        description="5 cities in a country with the lowest average age, over a 4-hop chain.",
        cypher=(
            "MATCH (p:Person)-[:LIVES_IN]->(c:City)-[:CITY_IN]->(s:State)-[:STATE_IN]->(co:Country) "
            "WHERE co.name = 'Country_00' "
            "RETURN c.name AS city, avg(p.age) AS avg_age "
            "ORDER BY avg_age, city LIMIT 5"
        ),
        ordered=True,
    ),
    Query(
        name="age_band_by_country",
        category="aggregation",
        description="Count of people aged 30-40 per country, over a 4-hop chain.",
        cypher=(
            "MATCH (p:Person)-[:LIVES_IN]->(c:City)-[:CITY_IN]->(s:State)-[:STATE_IN]->(co:Country) "
            "WHERE p.age >= 30 AND p.age <= 40 "
            "RETURN co.name AS country, count(p.id) AS num "
            "ORDER BY num DESC, country LIMIT 5"
        ),
        ordered=True,
    ),
    Query(
        name="interest_gender_by_city",
        category="filter_join",
        description="Top cities by count of male people with a given interest (multi-MATCH).",
        cypher=(
            "MATCH (p:Person)-[:HAS_INTEREST]->(i:Interest) "
            "MATCH (p)-[:LIVES_IN]->(c:City) "
            "WHERE i.name = 'Interest_00' AND p.gender = 'male' "
            "RETURN count(p.id) AS num, c.name AS city "
            "ORDER BY num DESC, city LIMIT 5"
        ),
        ordered=True,
    ),
    Query(
        name="two_hop_paths",
        category="path_count",
        description="Count of length-2 FOLLOWS paths (self-join on the middle vertex).",
        cypher=(
            "MATCH (a:Person)-[r1:FOLLOWS]->(b:Person)-[r2:FOLLOWS]->(c:Person) "
            "RETURN count(*) AS num"
        ),
    ),
    Query(
        name="two_hop_paths_filtered",
        category="path_count",
        description="Length-2 FOLLOWS paths filtered on intermediate and destination age.",
        cypher=(
            "MATCH (a:Person)-[r1:FOLLOWS]->(b:Person)-[r2:FOLLOWS]->(c:Person) "
            "WHERE b.age < 50 AND c.age > 25 "
            "RETURN count(*) AS num"
        ),
    ),
)


def by_name(name: str) -> Query:
    for query in CATALOG:
        if query.name == name:
            return query
    raise KeyError(name)
