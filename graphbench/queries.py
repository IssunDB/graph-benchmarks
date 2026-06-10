"""The benchmark query catalog.

Each query is one Cypher template that runs verbatim on every engine once its
placeholders are filled in. This is possible because ingestion stores identical
lower-case property names and relationship types across all engines, and predicate
values are inlined as literals (the IssunDB binding has no query-parameter API, so
parameters are avoided entirely rather than emulated per engine).

Placeholders (`{person_id}`, `{country}`, `{interest}`) are filled from the dataset
manifest's probe pools (see `dataset.generate`). The runner rotates the literal
values across timing rounds so engines cannot serve repeated identical statements
from a plan or result cache. Queries with no placeholders are whole-graph
aggregations whose statement is necessarily constant; this is called out in the
report.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Query:
    name: str
    category: str
    description: str
    # Cypher template; `{name}` placeholders are filled by `instantiate`.
    cypher: str
    # Placeholder names that must be supplied to `instantiate`.
    params: tuple[str, ...] = ()
    # True when the query's meaning depends on row order (ORDER BY ... LIMIT). Results
    # are still compared as a multiset; this flag drives reporting only.
    ordered: bool = False

    def instantiate(self, values: dict) -> str:
        """Fill the template's placeholders from `values` (extra keys are ignored)."""
        return self.cypher.format(**{p: values[p] for p in self.params})


CATALOG: tuple[Query, ...] = (
    Query(
        name="point_lookup",
        category="point",
        description="Look up a single person by id.",
        cypher=(
            "MATCH (p:Person) WHERE p.id = {person_id} "
            "RETURN p.name AS name, p.age AS age"
        ),
        params=("person_id",),
    ),
    Query(
        name="one_hop_neighbors",
        category="expand",
        description="List the people a given person follows.",
        cypher=(
            "MATCH (p:Person)-[:FOLLOWS]->(f:Person) WHERE p.id = {person_id} "
            "RETURN f.id AS id ORDER BY id"
        ),
        params=("person_id",),
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
        description="5 cities in a country with the lowest average age, over a 3-hop chain.",
        cypher=(
            "MATCH (p:Person)-[:LIVES_IN]->(c:City)-[:CITY_IN]->(s:State)-[:STATE_IN]->(co:Country) "
            "WHERE co.name = '{country}' "
            "RETURN c.name AS city, avg(p.age) AS avg_age "
            "ORDER BY avg_age, city LIMIT 5"
        ),
        params=("country",),
        ordered=True,
    ),
    Query(
        name="age_band_by_country",
        category="aggregation",
        description="Count of people aged 30-40 per country, over a 3-hop chain.",
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
            "WHERE i.name = '{interest}' AND p.gender = 'male' "
            "RETURN count(p.id) AS num, c.name AS city "
            "ORDER BY num DESC, city LIMIT 5"
        ),
        params=("interest",),
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
    Query(
        name="follows_reach",
        category="var_path",
        description="Distinct people reachable from a person via 1..2 FOLLOWS hops.",
        cypher=(
            "MATCH (a:Person)-[:FOLLOWS*1..2]->(b:Person) WHERE a.id = {person_id} "
            "RETURN count(DISTINCT b.id) AS num"
        ),
        params=("person_id",),
    ),
)


def by_name(name: str) -> Query:
    for query in CATALOG:
        if query.name == name:
            return query
    raise KeyError(name)
