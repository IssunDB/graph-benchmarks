"""Synthetic, seeded, vectorized generator for the social graph.

Everything is generated with numpy from a single seed, so a given (scale, seed)
pair is byte-for-byte reproducible on any machine. There is no external data file
and therefore no third-party data license.

Geography (countries, states, cities) is a fixed deterministic hierarchy whose size
does not grow with `scale`; only the Person population and its incident edges scale.
The `FOLLOWS` relation uses a Pareto-weighted destination distribution so a few
persons accumulate many followers (hubs), which is what makes the top-k and
path-count queries non-trivial.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .schema import SOCIAL, Schema

# Fixed geography and interest catalog (independent of person scale).
N_COUNTRIES = 5
STATES_PER_COUNTRY = 10
CITIES_PER_STATE = 40
N_INTERESTS = 40

# Average number of FOLLOWS edges generated per person before de-duplication.
FOLLOWS_FACTOR = 10
# Pareto shape for follower popularity; lower means heavier hubs.
POPULARITY_SHAPE = 1.5
# Range of interests per person (inclusive lower, exclusive upper).
INTERESTS_PER_PERSON = (1, 6)
AGE_RANGE = (18, 81)


@dataclass(frozen=True)
class Manifest:
    """Description of a generated dataset, written next to the Parquet files."""

    scale: int
    seed: int
    counts: dict[str, int]
    # Literal values that exist in the data, used by the query catalog.
    probes: dict[str, object]


def _write(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _country_name(i: np.ndarray | int) -> object:
    def fmt(x: int) -> str:
        return f"Country_{x:02d}"

    return [fmt(int(x)) for x in i] if isinstance(i, np.ndarray) else fmt(i)


def _state_name(i: np.ndarray) -> list[str]:
    return [f"State_{int(x):03d}" for x in i]


def _city_name(i: np.ndarray) -> list[str]:
    return [f"City_{int(x):05d}" for x in i]


def _interest_name(i: np.ndarray) -> list[str]:
    return [f"Interest_{int(x):02d}" for x in i]


def generate(
    out_dir: Path, scale: int, seed: int = 0, schema: Schema = SOCIAL
) -> Manifest:
    """Generate the dataset under `out_dir` and return its manifest."""
    rng = np.random.default_rng(seed)
    nodes_dir = out_dir / "nodes"
    edges_dir = out_dir / "edges"

    n_states = N_COUNTRIES * STATES_PER_COUNTRY
    n_cities = n_states * CITIES_PER_STATE
    n_persons = scale
    counts: dict[str, int] = {}

    # --- Country / State / City nodes (deterministic hierarchy) ---
    country_ids = np.arange(N_COUNTRIES)
    _write(
        pa.table({"id": country_ids, "name": _country_name(country_ids)}),
        nodes_dir / "Country.parquet",
    )
    counts["Country"] = N_COUNTRIES

    state_ids = np.arange(n_states)
    state_country = state_ids // STATES_PER_COUNTRY
    _write(
        pa.table(
            {
                "id": state_ids,
                "name": _state_name(state_ids),
                "country": _country_name(state_country),
            }
        ),
        nodes_dir / "State.parquet",
    )
    counts["State"] = n_states

    city_ids = np.arange(n_cities)
    city_state = city_ids // CITIES_PER_STATE
    city_country = city_state // STATES_PER_COUNTRY
    city_population = rng.integers(10_000, 5_000_000, n_cities)
    _write(
        pa.table(
            {
                "id": city_ids,
                "name": _city_name(city_ids),
                "state": _state_name(city_state),
                "country": _country_name(city_country),
                "population": city_population,
            }
        ),
        nodes_dir / "City.parquet",
    )
    counts["City"] = n_cities

    # --- Interest nodes ---
    interest_ids = np.arange(N_INTERESTS)
    _write(
        pa.table({"id": interest_ids, "name": _interest_name(interest_ids)}),
        nodes_dir / "Interest.parquet",
    )
    counts["Interest"] = N_INTERESTS

    # --- Person nodes ---
    person_ids = np.arange(n_persons)
    genders = np.where(rng.random(n_persons) < 0.5, "male", "female")
    ages = rng.integers(AGE_RANGE[0], AGE_RANGE[1], n_persons)
    married = rng.random(n_persons) < 0.5
    _write(
        pa.table(
            {
                "id": person_ids,
                "name": [f"Person_{int(x):07d}" for x in person_ids],
                "gender": genders,
                "age": ages,
                "is_married": married,
            }
        ),
        nodes_dir / "Person.parquet",
    )
    counts["Person"] = n_persons

    # --- FOLLOWS edges (Pareto-weighted destinations create hubs) ---
    n_raw = FOLLOWS_FACTOR * n_persons
    src = rng.integers(0, n_persons, n_raw)
    popularity = rng.pareto(POPULARITY_SHAPE, n_persons) + 1.0
    dst = rng.choice(n_persons, size=n_raw, p=popularity / popularity.sum())
    keep = src != dst
    follow_key = np.unique(src[keep].astype(np.int64) * n_persons + dst[keep])
    f_src = follow_key // n_persons
    f_dst = follow_key % n_persons
    _write(pa.table({"src": f_src, "dst": f_dst}), edges_dir / "FOLLOWS.parquet")
    counts["FOLLOWS"] = int(f_src.size)

    # --- LIVES_IN edges (one city per person, weighted by population) ---
    city_probs = city_population / city_population.sum()
    lives_dst = rng.choice(n_cities, size=n_persons, p=city_probs)
    _write(
        pa.table({"src": person_ids, "dst": lives_dst}), edges_dir / "LIVES_IN.parquet"
    )
    counts["LIVES_IN"] = n_persons

    # --- HAS_INTEREST edges (1..5 distinct interests per person) ---
    k = rng.integers(INTERESTS_PER_PERSON[0], INTERESTS_PER_PERSON[1], n_persons)
    person_rep = np.repeat(person_ids, k)
    raw_interest = rng.integers(0, N_INTERESTS, person_rep.size)
    int_key = np.unique(person_rep.astype(np.int64) * N_INTERESTS + raw_interest)
    i_src = int_key // N_INTERESTS
    i_dst = int_key % N_INTERESTS
    _write(pa.table({"src": i_src, "dst": i_dst}), edges_dir / "HAS_INTEREST.parquet")
    counts["HAS_INTEREST"] = int(i_src.size)

    # --- CITY_IN and STATE_IN edges (geography hierarchy) ---
    _write(
        pa.table({"src": city_ids, "dst": city_state}), edges_dir / "CITY_IN.parquet"
    )
    counts["CITY_IN"] = n_cities
    _write(
        pa.table({"src": state_ids, "dst": state_country}),
        edges_dir / "STATE_IN.parquet",
    )
    counts["STATE_IN"] = n_states

    probes = {
        "person_id": min(42, n_persons - 1),
        "country": "Country_00",
        "interest": "Interest_00",
        "gender": "male",
        "age_low": 30,
        "age_high": 40,
    }
    manifest = Manifest(scale=scale, seed=seed, counts=counts, probes=probes)
    (out_dir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2))
    return manifest


def load_manifest(out_dir: Path) -> Manifest:
    data = json.loads((out_dir / "manifest.json").read_text())
    return Manifest(**data)
