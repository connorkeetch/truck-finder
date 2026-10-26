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
python -m rivian_finder.cli check-email    # import new alert emails from your mailbox
python -m rivian_finder.cli notify-test    # make sure notifications show up
```

Example output:

```text
$ .venv/bin/python -m rivian_finder.cli run
42 matching vehicles, 3 new, 2 price reductions, 1 missing since last successful scan.
```

Things to know:

- `run` uses every connector that is enabled and has a key, for all brands in your collection scope. If the
  demo connector is still on, it runs too. When [mailbox import](#import-alert-emails-automatically) is on, it
  reads your alert emails first, even if no connector is ready.
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

## Import alert emails automatically

KSL, RivianForums, AutoTrader, Cars.com and most other sites can email you when a saved search finds something.
Truck Finder can read those emails from one mailbox folder and import their listings on every **Run Search** and
scheduled search. It costs no listing API calls, and the app never visits the sites. This is the way to get KSL
and forum listings automatically: those sites don't allow automated collection.

### Set it up (Gmail)

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification), then create an
   [app password](https://myaccount.google.com/apppasswords). Your normal Gmail password won't work.
2. Create a label, e.g. **Truck alerts**, and a filter that applies it to alert emails:

   ```text
   from:(ksl.com OR rivianforums.com OR autotrader.com OR cars.com OR cargurus.com OR carmax.com OR carvana.com)
   ```

3. Turn on alerts: save a search on KSL with email notifications, and on RivianForums open
   **Rivians / Vehicles For Sale** → **Watch** → email notifications.
4. In Truck Finder: **More → Sources → Email alerts → Automatic import from your mailbox → Set up / change**.
   Turn it on, enter your Gmail address, the label name and the app password, then **Save**.
5. Press **Check mailbox now** to try it.

Other providers work too: enter their IMAP server (for example `outlook.office365.com`) and a folder name.

### What it does

- Reads **only that folder or label**, read-only. Nothing is marked read, moved or deleted.
- Imports each email once, remembered by its Message-ID. It reads emails from the last 14 days (adjustable), up to
  50 per check; the rest wait for the next check.
- Saves listings that match your saved make/model searches. Wanted-to-buy posts and SOLD forum threads are
  skipped. Imported listings follow the usual [import rules](IMPORTING.md): duplicates merge by VIN or link, and
  nothing is ever marked missing.
- Shows the last result and recent emails on the Sources page. `data/logs/scheduled.log` has scheduled runs.

To import emails without a browser open, turn on the scheduled search (Windows), add the cron line above
(macOS/Linux), or use the hosted scheduler. On Railway, set the app password as the `TRUCK_FINDER_IMAP_PASSWORD`
variable.

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
