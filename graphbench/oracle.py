"""Engine-independent ground truth for the correctness gate.

Every catalog query is re-implemented here as a polars program over the raw Parquet
dataset, so the expected result of a query is computed without involving any of the
benchmarked engines — including IssunDB. The runner compares each engine's rows
against this oracle; no engine is ever its own (or another engine's) reference.

The implementations mirror the Cypher semantics exactly: counts are row counts over
the matched pattern, ORDER BY tie-breakers match the catalog's, and LIMIT is applied
after the full sort. Comparison happens on `engines.normalize_rows` output, so float
rounding and row/column order are already taken care of by the gate.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .queries import Query
from .schema import SOCIAL, Schema

Record = dict


def load_tables(data_dir: Path, schema: Schema = SOCIAL) -> dict[str, pl.DataFrame]:
    tables: dict[str, pl.DataFrame] = {}
    for label in schema.nodes:
        tables[label.name] = pl.read_parquet(
            data_dir / "nodes" / f"{label.name}.parquet"
        )
    for rel in schema.rels:
        tables[rel.name] = pl.read_parquet(data_dir / "edges" / f"{rel.name}.parquet")
    return tables


def _city_named(t: dict) -> pl.DataFrame:
    return t["City"].select(pl.col("id").alias("city_id"), pl.col("name").alias("city"))


def _person_city_country(t: dict) -> pl.DataFrame:
    """Person -> City -> State -> Country chain via the edge tables, one row per person."""
    return (
        t["LIVES_IN"]
        .rename({"src": "person_id", "dst": "city_id"})
        .join(t["CITY_IN"].rename({"src": "city_id", "dst": "state_id"}), on="city_id")
        .join(
            t["STATE_IN"].rename({"src": "state_id", "dst": "country_id"}),
            on="state_id",
        )
        .join(
            t["Country"].select(
                pl.col("id").alias("country_id"), pl.col("name").alias("country")
            ),
            on="country_id",
        )
    )


def _follow_counts(t: dict) -> pl.DataFrame:
    return t["FOLLOWS"].group_by("dst").agg(pl.len().alias("num")).rename({"dst": "id"})


def _point_lookup(t: dict, p: dict) -> list[Record]:
    df = t["Person"].filter(pl.col("id") == p["person_id"]).select("name", "age")
    return df.to_dicts()


def _one_hop_neighbors(t: dict, p: dict) -> list[Record]:
    df = (
        t["FOLLOWS"]
        .filter(pl.col("src") == p["person_id"])
        .select(pl.col("dst").alias("id"))
        .sort("id")
    )
    return df.to_dicts()


def _top_followed(t: dict, p: dict) -> list[Record]:
    df = (
        _follow_counts(t)
        .join(t["Person"].select("id", "name"), on="id")
        .select("id", "name", "num")
        .sort(["num", "id"], descending=[True, False])
        .head(3)
    )
    return df.to_dicts()


def _top_followed_city(t: dict, p: dict) -> list[Record]:
    df = (
        _follow_counts(t)
        .join(t["LIVES_IN"].rename({"src": "id", "dst": "city_id"}), on="id")
        .join(_city_named(t), on="city_id")
        .select("id", "num", "city")
        .sort(["num", "id"], descending=[True, False])
        .head(1)
    )
    return df.to_dicts()


def _youngest_cities_in_country(t: dict, p: dict) -> list[Record]:
    df = (
        _person_city_country(t)
        .filter(pl.col("country") == p["country"])
        .join(
            t["Person"].select(pl.col("id").alias("person_id"), "age"), on="person_id"
        )
        .join(_city_named(t), on="city_id")
        .group_by("city")
        .agg(pl.col("age").mean().alias("avg_age"))
        .sort(["avg_age", "city"])
        .head(5)
    )
    return df.to_dicts()


def _age_band_by_country(t: dict, p: dict) -> list[Record]:
    in_band = (
        t["Person"]
        .filter(pl.col("age").is_between(30, 40))
        .select(pl.col("id").alias("person_id"))
    )
    df = (
        _person_city_country(t)
        .join(in_band, on="person_id")
        .group_by("country")
        .agg(pl.len().alias("num"))
        .select("country", "num")
        .sort(["num", "country"], descending=[True, False])
        .head(5)
    )
    return df.to_dicts()


def _interest_gender_by_city(t: dict, p: dict) -> list[Record]:
    interest_ids = (
        t["Interest"]
        .filter(pl.col("name") == p["interest"])
        .select(pl.col("id").alias("interest_id"))
    )
    df = (
        t["Person"]
        .filter(pl.col("gender") == "male")
        .select(pl.col("id").alias("person_id"))
        .join(
            t["HAS_INTEREST"].rename({"src": "person_id", "dst": "interest_id"}),
            on="person_id",
        )
        .join(interest_ids, on="interest_id")
        .join(
            t["LIVES_IN"].rename({"src": "person_id", "dst": "city_id"}), on="person_id"
        )
        .join(_city_named(t), on="city_id")
        .group_by("city")
        .agg(pl.len().alias("num"))
        .select("num", "city")
        .sort(["num", "city"], descending=[True, False])
        .head(5)
    )
    return df.to_dicts()


def _two_hop_join(t: dict) -> pl.DataFrame:
    follows = t["FOLLOWS"]
    return follows.rename({"dst": "mid"}).join(follows.rename({"src": "mid"}), on="mid")


def _two_hop_paths(t: dict, p: dict) -> list[Record]:
    return [{"num": _two_hop_join(t).height}]


def _two_hop_paths_filtered(t: dict, p: dict) -> list[Record]:
    age = t["Person"].select("id", "age")
    df = (
        _two_hop_join(t)
        .join(age.rename({"id": "mid", "age": "mid_age"}), on="mid")
        .filter(pl.col("mid_age") < 50)
        .join(age.rename({"id": "dst", "age": "dst_age"}), on="dst")
        .filter(pl.col("dst_age") > 25)
    )
    return [{"num": df.height}]


def _follows_reach(t: dict, p: dict) -> list[Record]:
    # 1..2-hop reachability. Edge-uniqueness (Cypher's per-path constraint) holds for
    # free: a 2-hop path cannot reuse its first edge because self-loops do not exist.
    follows = t["FOLLOWS"]
    one = follows.filter(pl.col("src") == p["person_id"]).select("dst")
    two = one.rename({"dst": "src"}).join(follows, on="src").select("dst")
    return [{"num": pl.concat([one, two]).unique().height}]


_EVALUATORS = {
    "point_lookup": _point_lookup,
    "one_hop_neighbors": _one_hop_neighbors,
    "top_followed": _top_followed,
    "top_followed_city": _top_followed_city,
    "youngest_cities_in_country": _youngest_cities_in_country,
    "age_band_by_country": _age_band_by_country,
    "interest_gender_by_city": _interest_gender_by_city,
    "two_hop_paths": _two_hop_paths,
    "two_hop_paths_filtered": _two_hop_paths_filtered,
    "follows_reach": _follows_reach,
}


def evaluate(
    tables: dict[str, pl.DataFrame], query: Query, params: dict
) -> list[Record]:
    """Compute the expected rows for one instantiation of `query`."""
    try:
        fn = _EVALUATORS[query.name]
    except KeyError:
        raise KeyError(
            f"query {query.name!r} has no oracle implementation; every catalog "
            "query must have one so the correctness gate stays engine-independent"
        ) from None
    return fn(tables, params)
