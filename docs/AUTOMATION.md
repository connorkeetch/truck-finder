# Automation and command line

Searches normally start when you press **Run Search**. You can also run them on a schedule, from the command
line, or from your own Python scripts.

## Command line

Run these from the project folder with the virtual environment's Python (`.venv\Scripts\python` on Windows,
`.venv/bin/python` on macOS/Linux):

```bash
python -m rivian_finder.cli run            # search with every enabled, configured connector
python -m rivian_finder.cli run --notify   # same, then show a desktop notification
python -m rivian_finder.cli check-links    # check that saved listing links still work
python -m rivian_finder.cli notify-test    # make sure notifications show up
```

Example output:

```text
$ .venv/bin/python -m rivian_finder.cli run
42 matching vehicles, 3 new, 2 price reductions, 1 missing since last successful scan.
```

Things to know:

- `run` uses every connector that is enabled and has a key, for all brands in your collection scope. If the
  demo connector is still on, it runs too.
- `run` skips a connector when its monthly budget can't cover a full run (with 20% headroom), and says so.
- `run` exits with `0` when at least one source succeeded and `1` otherwise, so you can chain it in scripts.
- `run` logs to `data/logs/scheduled.log`.
- `check-links` makes one request per link, respects `robots.txt`, spaces out requests to each site, and stops
  at the first bot challenge. A dead link doesn't prove the truck sold.

## Scheduled searches

### Windows

**Settings → Alerts**:

1. Choose what to be told about: new matching trucks, price drops on favorites, good deals, a minimum drop.
2. Enter times, for example `08:00, 18:00`.
3. Press **Turn on scheduled search**.

This creates Windows Task Scheduler tasks in a **RivianFinder** folder. The tasks run `run_alerts.pyw`, which
runs `cli run --notify` without a console window. They only run while you're logged in. Use **Send a test
notification** to check that notifications appear (Focus Assist / Do Not Disturb can hide them).

### macOS and Linux

The app can't create the schedule for you yet, but cron works. Run `crontab -e` and add a line like this one
(adjust the path):

```cron
# Search at 8:00 and 18:00 every day and notify about changes
0 8,18 * * * cd "$HOME/truck-finder" && .venv/bin/python -m rivian_finder.cli run --notify
```

Notifications use `osascript` on macOS and `notify-send` on Linux. Cron jobs may not have access to your
desktop session. If no notification appears, run `notify-test` from a terminal first.

### Hosted (Railway)

The cloud deployment runs scheduled searches inside the server, using the times in **Settings → Alerts** and
the `TZ` variable. Missed times aren't caught up after a restart. See
[Private Railway deployment](CLOUD_DEPLOYMENT.md#scheduling-and-desktop-features).

## Watching your API budget

Auto.dev's and MarketCheck's free plans have monthly call limits. The app counts its own calls and stops before
going over its configured caps. Each run is also capped by **Settings → Collection scope → Max pages per
connector per run**.

Example: a scope that needs 4 pages per run, searched twice a day, uses about 4 × 2 × 30 = **240 calls a
month**. Calls you make outside this app (on the provider's dashboard or from other tools) aren't counted.

## From Python

The app is a regular Python package, so you can script it. Save scripts in the project folder and run them with
`.venv`'s Python. Back up first (**Settings → Backup & data → Back up now**) if a script writes to your
database.

### Export your filtered inventory

```python
# export_view.py: write the trucks that match your saved filters to a CSV
from rivian_finder import db, queries

conn = db.connect()
settings = db.load_settings(conn)
view = queries.apply_filters(queries.inventory_frame(conn, settings), settings["filters"])

columns = ["year", "make", "model", "trim", "price", "miles", "location", "distance_mi", "deal_label", "url"]
view.sort_values("price")[columns].to_csv("my_trucks.csv", index=False)
print(f"Wrote {len(view)} trucks to my_trucks.csv")
```

### List recent price drops

```python
# price_drops.py
from rivian_finder import db, queries

conn = db.connect()
events = queries.events_frame(conn)
drops = events[events["event_type"] == "price_drop"]
for _, e in drops.head(10).iterrows():
    print(f"{e['year']} {e['make']} {e['model']}  ${e['old_value']} → ${e['new_value']}  {e['url']}")
```

### Run a search

```python
from rivian_finder import db, services

conn = db.connect()
summary = services.run_sources(conn)  # same as Run Search with every ready connector
print(summary["text"])
```

`services.run_sources(conn, keys=["autodev"], brands=["Ford"])` limits the run to one connector and one brand.
The internal API isn't stable yet, so pin a commit if you depend on it.
