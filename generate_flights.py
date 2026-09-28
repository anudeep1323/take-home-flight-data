"""
Task 2, Phase 1 — Data Generation.

Generates ~5000 JSON files of randomly generated flight data under
/tmp/flights/, one file per (origin_city, batch) named
"<MM>-<YY>-<origin_city>-flights-<seq>.json".

Design note on the filename pattern: the spec's literal template
(`%MM-YY%-%origin_city%-flights.json`) only varies by month/city, but with a
single current month and only K=[100-200] cities it cannot produce ~5000
distinct filenames on its own (that would need ~25-50 files per city in the
same month). We keep the required "<MM>-<YY>-<origin_city>-flights" prefix
and append a zero-padded sequence number to guarantee uniqueness, modeling
multiple flight batches/logs generated for the same origin city in the same
month (e.g. one file per departure batch).
"""
from __future__ import annotations

import json
import os
import random
import string
from datetime import date, timedelta
from pathlib import Path

from cities import CITY_POOL

OUTPUT_DIR = Path(os.environ.get("FLIGHTS_DIR", "/tmp/flights"))
NUM_FILES = int(os.environ.get("NUM_FILES", 5000))
MIN_RECORDS_PER_FILE = 50
MAX_RECORDS_PER_FILE = 100
MIN_CITIES = 100
MAX_CITIES = 200
MIN_DIRTY_PROB = 0.005
MAX_DIRTY_PROB = 0.01
MIN_DURATION_SECS = 1800      # 30 minutes
MAX_DURATION_SECS = 43200     # 12 hours
MIN_PASSENGERS = 10
MAX_PASSENGERS = 300

FIELDS = ["date", "origin_city", "destination_city", "flight_duration_secs", "#_of_passengers_on_board"]


def slugify(city: str) -> str:
    keep = string.ascii_letters + string.digits
    return "".join(c if c in keep else "_" for c in city.replace(" ", "_"))


def random_date_in_current_month() -> str:
    today = date.today()
    start = today.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    days_in_month = (next_month - start).days
    day_offset = random.randint(0, days_in_month - 1)
    return (start + timedelta(days=day_offset)).isoformat()


def make_record(cities: list[str], dirty_prob: float) -> dict:
    origin, destination = random.sample(cities, 2)
    record = {
        "date": random_date_in_current_month(),
        "origin_city": origin,
        "destination_city": destination,
        "flight_duration_secs": random.randint(MIN_DURATION_SECS, MAX_DURATION_SECS),
        "#_of_passengers_on_board": random.randint(MIN_PASSENGERS, MAX_PASSENGERS),
    }
    if random.random() < dirty_prob:
        num_null_fields = random.randint(1, len(FIELDS))
        for field in random.sample(FIELDS, num_null_fields):
            record[field] = None
    return record


def generate(num_files: int = NUM_FILES, output_dir: Path = OUTPUT_DIR) -> dict:
    random.seed()  # non-deterministic across runs; fine for a simulator
    output_dir.mkdir(parents=True, exist_ok=True)

    num_cities = random.randint(MIN_CITIES, MAX_CITIES)
    cities = random.sample(list(dict.fromkeys(CITY_POOL)), num_cities)
    dirty_prob = random.uniform(MIN_DIRTY_PROB, MAX_DIRTY_PROB)

    today = date.today()
    mm_yy = today.strftime("%m-%y")

    total_records = 0
    for seq in range(num_files):
        origin_city = random.choice(cities)
        num_records = random.randint(MIN_RECORDS_PER_FILE, MAX_RECORDS_PER_FILE)
        records = [make_record(cities, dirty_prob) for _ in range(num_records)]
        total_records += len(records)

        filename = f"{mm_yy}-{slugify(origin_city)}-flights-{seq:05d}.json"
        with open(output_dir / filename, "w") as f:
            json.dump(records, f)

    meta = {
        "num_files": num_files,
        "num_cities": num_cities,
        "dirty_prob": dirty_prob,
        "total_records": total_records,
        "output_dir": str(output_dir),
    }
    with open(output_dir / "_generation_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    return meta


if __name__ == "__main__":
    info = generate()
    print(f"Generated {info['num_files']} files, {info['total_records']} total records, "
          f"{info['num_cities']} cities, dirty_prob={info['dirty_prob']:.4%}, "
          f"into {info['output_dir']}")
