# How Truck Finder works

This guide is for contributors. It explains how data moves through the app, the few ideas that everything
else depends on, and how to extend it.

## The big picture

```text
 Listing providers            Things you bring in
 (Auto.dev, MarketCheck,      (CSV/JSON, alert emails, pasted pages,
  demo)                        browser extension, manual entry)
        │                                │
 sources/*.py  ──fetch()──┐    ┌── importers/*.py
                          ▼    ▼
                   NormalizedListing          models.py: one shape for every input
                          │
                   pipeline.Ingestor          match by VIN/URL, record price & miles,
                          │                   store equipment claims, emit change events
                          ▼
                 SQLite  (data/rivian_finder.db)
                          │
                 queries.inventory_frame()    one pandas row per vehicle: resolved fields,
                          │                   deal rating, costs, warranty, match status
            ┌─────────────┼──────────────┐
            ▼             ▼              ▼
     ui/*.py pages   export_xlsx.py   cli.py / alerts.py
     (Streamlit)     (Excel)          (scheduled runs, notifications)
```

`app.py` only sets up Streamlit navigation. The pages live in `rivian_finder/ui/`.

## Core ideas

### Vehicle, listing, observation

- A **vehicle** is one physical truck, identified by its VIN.
- A **listing** is one ad for that vehicle on one site. The same truck on AutoTrader and on the dealer's own
  site is one vehicle with two listings.
- An **observation** is the price and mileage of a listing at one point in time. Price history is built from
  these.

A listing with a valid VIN always attaches to that VIN's vehicle. A listing without one gets a provisional
vehicle. `dedup.py` then suggests possible matches for you to merge or dismiss. Nothing is merged
automatically without a shared VIN.

### Claims and confidence

Listings disagree, and they're often wrong. So equipment such as battery, motor, tonneau, range or towing is
never stored as a single value. Each source adds an `AttributeClaim` with a confidence and the evidence it came
from:

| Confidence | Comes from |
|---|---|
| `verified` | You, on **Verify equipment** / **Quick verify**. Always wins and survives refreshes. |
| `high` | VIN decoding or manufacturer data |
| `medium` | A structured listing field |
| `low` | Text parsed from a description or pasted page |

`attributes.resolve()` picks the value to show. When sources disagree at the same level, the field shows as
**Uncertain** with every claim listed, rather than guessing. Filters keep uncertain vehicles visible.

The rule of thumb is **unknown stays unknown**. Don't fill a gap with a model's typical value. An individual
truck's tow rating is never replaced with the model's advertised maximum.

### Complete scans and "missing"

A listing is marked **missing** only when all of these are true:

1. the connector returned `FetchResult(complete=True)`, meaning every page was fetched;
2. the collection scope is the same as last time (compared by `scope_hash`);
3. the listing is inside that scope and wasn't seen.

Failed, partial or rate-limited runs, imports, and runs after a scope change never mark anything missing.
**Missing** is not **removed**. *Removed* needs evidence: the provider says so, or you marked it sold.

### Collection scope vs. display filters

`settings["collection"]` decides what connectors *fetch*, and that costs API calls. `settings["filters"]`
decides what the UI *shows*, and it's applied locally in `queries.apply_filters()`. Changing a filter never
triggers a fetch.

## Code map

| Area | Files |
|---|---|
| Entry points | `app.py` (UI), `launcher.py` (venv + start), `rivian_finder/cli.py`, `run_alerts.pyw` |
| Hosted runtime | `rivian_finder/cloud.py` (Streamlit + in-process scheduler), `Dockerfile`, `Caddyfile` (login proxy), `docker-entrypoint.sh` |
| Data shapes | `models.py` (`NormalizedListing`, `AttributeClaim`, `FetchResult`) |
| Storage | `db.py` (connect, migrations, settings), `migrations/*.sql`, `repairs.py`, `backup.py` |
| Collecting | `sources/base.py` (HTTP, retries, budgets), `sources/autodev.py`, `sources/marketcheck.py`, `sources/demo.py` |
| Importing | `importers/manual.py` (form/CSV/JSON), `email_alerts.py`, `capture.py` + `capture_server.py` (extension), `rivian_page.py` |
| Ingest | `pipeline.py` (runs, change events, missing detection), `dedup.py`, `attributes.py` |
| Parsing | `extract.py` (prices, miles, locations, equipment from text), `vin.py`, `trims.py` |
| Analysis | `queries.py` (inventory frame, filters, sorting), `deals.py`, `matching.py`, `price_insights.py`, `negotiation.py`, `flips.py`, `compare.py` |
| Costs | `finance.py`, `shipping.py`, `adjust.py` |
| Model-specific | `epa.py` + `data/epa_r1t.json`, `warranty.py`, `subframe.py` (Rivian R1T only) |
| Extras | `enrich.py` (NHTSA vPIC), `recalls.py`, `photos.py`, `linkcheck.py`, `links.py`, `notifier.py`, `scheduler.py`, `access.py` |
| UI | `ui/common.py` (boot, sidebar, cached inventory), one module per page, `ui/cards.py` (card grid) |

The package is named `rivian_finder` because the project started as a Rivian R1T tracker. The app itself
works for any make and model.

## Adding a listing source

A connector is a class with a `key`, a `name`, and a `fetch(scope)` that returns a `FetchResult`. Here's a
complete minimal one:

```python
# rivian_finder/sources/mydealer.py
from ..models import FetchResult, NormalizedListing
from .base import SourceAdapter, scope_hash


class MyDealerFeed(SourceAdapter):
    key = "mydealer"
    name = "My dealer feed"

    def fetch(self, scope: dict) -> FetchResult:
        listings = [NormalizedListing(
            source_key=self.key, import_method="api", source_listing_id="stock-123",
            url="https://example.com/stock-123", year=2024, make="Ford", model="F-150 Lightning",
            price=48500, miles=12000, seller_name="Example Ford", seller_type="dealer",
            city="Boise", state="ID", zip="83702")]
        return FetchResult(listings=listings, complete=True, scope_hash=scope_hash(scope), api_calls=1)
```

You can run it directly:

```python
from rivian_finder import db, pipeline
from rivian_finder.sources.mydealer import MyDealerFeed

conn = db.connect()
summary = pipeline.run_search(conn, [MyDealerFeed()], {"make": "Ford", "model": "F-150 Lightning"})
print(summary["status"], summary["counts"]["new_listing"])   # success 1
```

For a real HTTP API, subclass `HttpSourceAdapter` and call `self.get_json(url, params=...)`. You get request
pacing, retries with `Retry-After` support, monthly budget accounting, and error messages with credentials
removed. See `sources/autodev.py` for a full example with pagination.

The rules that matter:

- **Set `complete=True` only when you fetched every page.** If you stop early because of a page cap, budget,
  or error, return `complete=False`. Otherwise the app will mark unseen trucks missing.
- **Return only listings inside the scope.** Filter by the make/model you were asked for.
- **Put equipment in `attributes`** as `AttributeClaim`s with an honest confidence. `extract.extract_attributes()`
  can parse common text for you.
- **Use authorized APIs only.** No scraping of sites whose terms forbid it, no spoofed browser identities, and
  no getting around bot checks.

To show the connector in the app, register it in these places (a registry that replaces this list would be a
welcome change, see [Improvements](IMPROVEMENTS.md)):

1. `services.make_adapter()`: construct it. Add its key to `services.API_SOURCES` so it appears on the
   Sources page and in Run Search.
2. `db.SOURCE_SEED`: add a `(key, name, kind, enabled)` row. It's inserted on next start, including for
   existing databases.
3. `credentials.KEYS`: add the environment variable name if it needs an API key.
4. `sources/base.API_CAPS`: add a monthly call cap if the provider has a quota.
5. `queries.SOURCE_LABELS`: add a short display name.

Add a test that feeds a saved response from `tests/fixtures/` through `fetch()`. Tests must never call the
real API.

## Adding an import format

Turn your input into `NormalizedListing` objects (use `import_method="csv"`, `"email"` and so on), then call:

```python
pipeline.import_listings(conn, listings, trigger="my_format")
```

Imports never count as complete scans, so they can't mark anything missing.

## Changing the database

- Add a new file, `rivian_finder/migrations/008_short_name.sql`. Migrations run in filename order the next time
  the database is opened, and each one runs once.
- Never edit a migration that has already shipped. People's databases have already applied it.
- For a one-time fix to existing *data* (not schema), add a function to `repairs.py` and call it from
  `run_all()`. Mark it done with a `repair:<key>` preference so it runs once. Make a backup first if it
  deletes anything.
- New settings go in `config.DEFAULT_SETTINGS`. `merge_settings()` fills new keys in for existing users, so
  their saved values are kept.

## Model-specific rules

Some logic only applies to one vehicle, such as Rivian R1T battery packs, EPA ratings, warranty terms and
front-subframe estimates. Keep that logic behind an explicit make/model check, and keep its labels honest
(*est.*, *Unsure*). Another brand must never inherit a Rivian rule. When you add rules for a new model, put
them in their own module, the way `subframe.py` and `epa.py` do.

## Tests

```bash
python -m pytest                       # everything (700+ tests, no API keys needed)
python -m pytest tests/test_pipeline.py -k disappear
```

`tests/conftest.py` points every data path at a temporary folder, so tests can't touch your real `data/`.
Useful helpers:

```python
from conftest import FakeAdapter, listing, vin
from rivian_finder.models import FetchResult
from rivian_finder import pipeline


def test_missing_needs_a_complete_scan(conn):
    first = FetchResult([listing(vin=vin(1)), listing(vin=vin(2))], complete=True, scope_hash="s")
    partial = FetchResult([listing(vin=vin(1))], complete=False, scope_hash="s")
    adapter = FakeAdapter("autodev", [first, partial])

    pipeline.run_search(conn, [adapter], {})
    pipeline.run_search(conn, [adapter], {})

    statuses = {r["status"] for r in conn.execute("SELECT status FROM listings")}
    assert statuses == {"active"}   # the partial scan didn't mark vin(2) missing
```

- `conn`: a migrated in-memory database.
- `settings`: a saved EV-truck setup.
- `listing(**fields)`: a `NormalizedListing` with sensible defaults.
- `vin(serial)`: a checksum-valid synthetic R1T VIN.
- `FakeAdapter(key, results)`: a connector that returns, or raises, the queued results in order.
