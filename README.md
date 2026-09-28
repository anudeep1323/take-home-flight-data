# Task 2: Flight Data Simulation, Analysis & Cleaning

Python 3.7+, stdlib only for Phase 2's core logic (Phase 1 also stdlib-only). Tested with Python 3.13.

## Files

- [`cities.py`](cities.py) — pool of 212 unique real city names to sample K=[100-200] from.
- [`generate_flights.py`](generate_flights.py) — **Phase 1**: generates ~5000 JSON flight files.
- [`analyze_flights.py`](analyze_flights.py) — **Phase 2**: loads, cleans, and analyzes them.

## Run it

```bash
python3 generate_flights.py     # writes to /tmp/flights (override with FLIGHTS_DIR env var)
python3 analyze_flights.py      # reads from the same directory, prints report,
                                 # writes /tmp/flight_analysis_result.json
```

Override defaults with env vars, e.g. `FLIGHTS_DIR=/tmp/flights_test NUM_FILES=20 python3 generate_flights.py`
for a quick smoke test.

## Phase 1 — Data Generation

- Writes `NUM_FILES` (default **5000**) JSON files into `/tmp/flights/`.
- Each file is a JSON array of `M` flight records, `M ~ Uniform[50, 100]`.
- Each record has exactly the 5 required fields: `date` (ISO `YYYY-MM-DD`, random day in the current
  month), `origin_city`, `destination_city` (always different from origin), `flight_duration_secs`
  (30 min – 12 h), `#_of_passengers_on_board` (10–300).
- **City pool:** `K ~ Uniform[100, 200]` cities are sampled once per run from `cities.py` and reused across
  all files in that run (so aggregate stats in Phase 2 are meaningful across files).
- **Dirty records:** each record independently has probability `L ~ Uniform[0.5%, 1%]` (drawn once per run)
  of being "dirty" — if selected, 1 to 5 of its fields are set to `null`.
- **Filename design decision:** the spec's literal pattern
  `/tmp/flights/%MM-YY%-%origin_city%-flights.json` only varies by month and origin city. With one current
  month and ≤200 cities, that alone can't produce ~5000 *distinct* filenames without collisions. We keep the
  required `<MM>-<YY>-<origin_city>-flights` prefix and append a zero-padded sequence number
  (`...-flights-00042.json`), modeling one file per flight-log batch generated for that origin city that
  month. City names are filesystem-slugified (spaces/punctuation → `_`) for the filename only; the JSON
  content keeps the original city name (e.g. `"New York"`).
- Also writes `_generation_meta.json` (chosen `K`, `L`, totals) for reproducibility/debugging; Phase 2's
  file glob (`*-flights-*.json`) ignores it.

Actual run: **5000 files, 374,059 total records, 150 cities, dirty_prob≈0.78%**, generated in ~3.2s.

## Phase 2 — Data Analysis & Cleaning

**Cleaning policy:** a record is "dirty" if *any* of its 5 fields is `null`. Dirty records are still counted
in the totals, and each metric below uses whatever fields a record *does* have rather than discarding the
whole record — e.g. a record with a null `date` but valid `origin_city`/`destination_city`/passenger count
still contributes to the passenger-balance and duration stats. A metric only skips a record when the
specific field(s) it needs are null. This preserves more real signal than an all-or-nothing drop, and is
called out explicitly since the spec doesn't mandate one policy over the other.

**Efficiency:** the ~5000 files are split into `os.cpu_count()` chunks and parsed in parallel worker
processes (`ProcessPoolExecutor`); each worker streams through its files and returns compact partial
aggregates (counters + duration lists per city) rather than raw records, and the main process merges them.
No full record set is ever held in memory at once.

**Outputs (printed + written to `/tmp/flight_analysis_result.json`):**
1. Total records processed, total dirty records, analysis runtime in milliseconds.
2. Top 25 destination cities by total arriving passengers, with AVG and P95 `flight_duration_secs` for
   flights landing in each (P95 computed with a stdlib-only linear-interpolation percentile — no numpy
   dependency).
3. Passenger balance per city (every city starts at 0; `+passengers` on arrival, `-passengers` on
   departure) → the city with the max and the city with the min net remaining passengers.

### Actual run (5000 files / 374,059 records)

```
Files processed:        5000
Records processed:      374059
Dirty records:          2838 (0.759%)
Analysis runtime:       416.40 ms

Top 25 destination cities by total arriving passengers (excerpt):
   1. Rochester            arriving_pax= 403877  avg_duration_secs= 22343.4  p95_duration_secs= 41097.4
   2. Santa Clarita        arriving_pax= 403536  avg_duration_secs= 22204.8  p95_duration_secs= 41062.2
   ...
  25. Allentown            arriving_pax= 393037  avg_duration_secs= 22237.6  p95_duration_secs= 41109.1

Passenger balance — max: Des Moines (+26310)
Passenger balance — min: Knoxville (-37016)
```

(Full 25-row table and complete JSON in `/tmp/flight_analysis_result.json` after running.) Because
`origin_city`/`destination_city` are drawn uniformly at random, arriving-passenger totals across the top 25
cities cluster tightly (~393K–404K) — this is the expected result of a uniform random simulator, not a bug;
a real-world dataset would show far more skew.
