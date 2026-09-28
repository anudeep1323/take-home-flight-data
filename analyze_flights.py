"""
Task 2, Phase 2 — Data Analysis & Cleaning.

Loads every generated flight JSON file, identifies "dirty" records (any NULL
field), and computes:
  - total records processed, total dirty records, analysis runtime (ms)
  - AVG and P95 of flight_duration_secs for the top 25 destination cities by
    total arriving passengers
  - the city with the max and the city with the min net remaining passengers
    (arrivals - departures), starting every city at 0

Cleaning policy: a record is "dirty" if ANY of its 5 fields is null. Dirty
records are still counted and, per metric, contribute whatever fields they
DO have (e.g. a record missing `date` but with valid origin/destination/
passengers still counts toward passenger-balance and duration stats) —
excluding a dirty record entirely would throw away good data unnecessarily.
A metric only skips a record if the specific field(s) it needs are null.

Efficiency: files are split into chunks (one per CPU core) and processed in
parallel worker processes; each worker returns partial aggregates that the
main process merges. This keeps memory bounded to durations/counts (no raw
records are ever held in memory all at once).
"""
from __future__ import annotations

import glob
import json
import math
import os
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

FLIGHTS_DIR = Path(os.environ.get("FLIGHTS_DIR", "/tmp/flights"))
FIELDS = ["date", "origin_city", "destination_city", "flight_duration_secs", "#_of_passengers_on_board"]
TOP_N_DESTINATIONS = 25


def percentile(sorted_values: list, q: float):
    """Linear-interpolation percentile (matches numpy's default 'linear' method), stdlib-only."""
    if not sorted_values:
        return None
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * (q / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def process_file_chunk(filepaths: list[str]) -> dict:
    """Runs in a worker process: parses each file and returns partial aggregates."""
    total = 0
    dirty = 0
    arrivals = Counter()          # destination_city -> total arriving passengers
    durations_by_dest = defaultdict(list)  # destination_city -> [flight_duration_secs, ...]
    balance = Counter()           # city -> net passengers (arrivals - departures)

    for path in filepaths:
        with open(path) as f:
            records = json.load(f)

        for rec in records:
            total += 1
            is_dirty = any(rec.get(field) is None for field in FIELDS)
            if is_dirty:
                dirty += 1

            origin = rec.get("origin_city")
            dest = rec.get("destination_city")
            passengers = rec.get("#_of_passengers_on_board")
            duration = rec.get("flight_duration_secs")

            if dest is not None and passengers is not None:
                arrivals[dest] += passengers
                balance[dest] += passengers
            if origin is not None and passengers is not None:
                balance[origin] -= passengers
            if dest is not None and duration is not None:
                durations_by_dest[dest].append(duration)

    return {
        "total": total,
        "dirty": dirty,
        "arrivals": arrivals,
        "durations_by_dest": dict(durations_by_dest),
        "balance": balance,
    }


def merge(results: list[dict]) -> dict:
    total = sum(r["total"] for r in results)
    dirty = sum(r["dirty"] for r in results)
    arrivals = Counter()
    balance = Counter()
    durations_by_dest = defaultdict(list)

    for r in results:
        arrivals.update(r["arrivals"])
        balance.update(r["balance"])
        for city, durs in r["durations_by_dest"].items():
            durations_by_dest[city].extend(durs)

    return {"total": total, "dirty": dirty, "arrivals": arrivals,
            "balance": balance, "durations_by_dest": durations_by_dest}


def analyze(flights_dir: Path = FLIGHTS_DIR, num_workers: int | None = None) -> dict:
    all_files = sorted(glob.glob(str(flights_dir / "*-flights-*.json")))
    if not all_files:
        raise FileNotFoundError(f"No flight files found in {flights_dir}. Run generate_flights.py first.")

    num_workers = num_workers or os.cpu_count() or 4
    chunks = [all_files[i::num_workers] for i in range(num_workers)]
    chunks = [c for c in chunks if c]

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=len(chunks)) as executor:
        results = list(executor.map(process_file_chunk, chunks))
    merged = merge(results)
    runtime_ms = (time.perf_counter() - t0) * 1000.0

    # Top 25 destination cities by total arriving passengers.
    top_destinations = merged["arrivals"].most_common(TOP_N_DESTINATIONS)

    top_stats = []
    for city, total_passengers in top_destinations:
        durs = sorted(merged["durations_by_dest"].get(city, []))
        avg = sum(durs) / len(durs) if durs else None
        p95 = percentile(durs, 95)
        top_stats.append({
            "city": city,
            "total_arriving_passengers": total_passengers,
            "num_flights_with_duration": len(durs),
            "avg_flight_duration_secs": avg,
            "p95_flight_duration_secs": p95,
        })

    balance = merged["balance"]
    max_city, max_balance = max(balance.items(), key=lambda kv: kv[1]) if balance else (None, None)
    min_city, min_balance = min(balance.items(), key=lambda kv: kv[1]) if balance else (None, None)

    return {
        "num_files_processed": len(all_files),
        "total_records_processed": merged["total"],
        "total_dirty_records": merged["dirty"],
        "analysis_runtime_ms": runtime_ms,
        "top_25_destinations_by_arriving_passengers": top_stats,
        "passenger_balance": {
            "max_city": max_city,
            "max_remaining_passengers": max_balance,
            "min_city": min_city,
            "min_remaining_passengers": min_balance,
            "num_cities_with_activity": len(balance),
        },
    }


def print_report(result: dict) -> None:
    print(f"Files processed:        {result['num_files_processed']}")
    print(f"Records processed:      {result['total_records_processed']}")
    print(f"Dirty records:          {result['total_dirty_records']} "
          f"({result['total_dirty_records'] / result['total_records_processed']:.3%})")
    print(f"Analysis runtime:       {result['analysis_runtime_ms']:.2f} ms")
    print()
    print(f"Top {TOP_N_DESTINATIONS} destination cities by total arriving passengers:")
    for i, s in enumerate(result["top_25_destinations_by_arriving_passengers"], 1):
        avg = f"{s['avg_flight_duration_secs']:.1f}" if s["avg_flight_duration_secs"] is not None else "N/A"
        p95 = f"{s['p95_flight_duration_secs']:.1f}" if s["p95_flight_duration_secs"] is not None else "N/A"
        print(f"  {i:2d}. {s['city']:<20} arriving_pax={s['total_arriving_passengers']:>7}  "
              f"avg_duration_secs={avg:>8}  p95_duration_secs={p95:>8}")
    print()
    pb = result["passenger_balance"]
    print(f"Passenger balance — max: {pb['max_city']} ({pb['max_remaining_passengers']:+d})")
    print(f"Passenger balance — min: {pb['min_city']} ({pb['min_remaining_passengers']:+d})")


if __name__ == "__main__":
    result = analyze()
    print_report(result)
    with open(FLIGHTS_DIR.parent / "flight_analysis_result.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
