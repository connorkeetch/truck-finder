# Quickstart

Get Truck Finder running and see it work in about five minutes. You don't need an API key for this.

## 1. Install and start

You need **Python 3.12** (3.10+ starts, but 3.12 is what CI tests). On Windows, tick **Add python.exe to PATH**
during install.

```bash
git clone https://github.com/connorkeetch/truck-finder.git
cd truck-finder
```

Then start it:

| Platform | Command |
|---|---|
| Windows | Double-click `run.bat`, or run `run.bat` in a terminal |
| macOS / Linux | `chmod +x run.sh && ./run.sh` |

The first start creates `.venv/` and installs dependencies (a minute or two). Your browser then opens
<http://127.0.0.1:8501>. Later starts are fast and reinstall only when `requirements.txt` changes.

> Port 8501 busy? Set `RIVIAN_FINDER_PORT=8502` (see [Configuration](CONFIGURATION.md)).

## 2. Try it with demo data

A fresh workspace includes a **demo connector** that serves 36 fake Rivian R1T listings (all URLs point at
`example.com`). Every demo vehicle is labeled **DEMO**.

1. In the sidebar, press **▶ Run Search**, pick **Rivian**, then **Start search**.
   You'll see something like *"26 new"*.
2. Press **Run Search** again. The demo moves forward in time, so this run reports changes such as price drops
   and listings that were not seen.
3. Click a truck's photo or name to open its details: price history, where it's sold, and evidence for each
   equipment claim.
4. Tick **✓** on two or three trucks and press **⚖ Compare** in the sidebar.

When you're done exploring, remove the fake data with **Settings → Backup & data → Purge all demo data**, then
turn off **Include demo connector in Run Search**.

## 3. Set up your own search

Open **Settings** (under **More** in the sidebar):

1. **Location → Home ZIP**: your ZIP code, so distances and radius searches work.
2. **Collection scope**: the make/model pairs to collect, for example:

   | Make | Model |
   |---|---|
   | Ford | F-150 Lightning |
   | Toyota | Tacoma |

   Also set the price, mileage, year and distance limits sent to the provider. Make these a little *broader*
   than what you want to see. You narrow the view later with Inventory filters, which cost no API calls.
3. **Vehicle filters**: your normal view (max price, max miles, years, distance).

## 4. Get listings in

Pick whatever fits. You can mix them, and duplicates merge by VIN.

| You have | Do this | Guide |
|---|---|---|
| An Auto.dev or MarketCheck API key | **Settings → API credentials**, then **Run Search** | [Sources](SOURCES.md) |
| A spreadsheet of listings | **More → Sources → CSV / JSON import** | [Importing](IMPORTING.md) |
| Saved-search alert emails | Drop the `.eml` files into **Sources → Email alerts** | [Importing](IMPORTING.md#email-alerts) |
| A listing open in your browser | Copy the page text, then **➕ Add a truck → Paste listing** | [Importing](IMPORTING.md#paste-a-listing) |
| Just a VIN | **➕ Add a truck → By VIN** (1 Auto.dev call) | |

Want something to import right now? Try the bundled sample file:
**More → Sources → CSV / JSON import → upload `examples/sample_listings.csv` → Import**.

## 5. Day-to-day

- **Run Search** whenever you want fresh prices. Each run tells you what's new, what dropped, and what wasn't
  seen.
- **★** a truck to add it to **My shortlist**, where you track what still needs proof from the seller.
- **🚫 Not interested** hides a truck everywhere, even if it shows up again on another site.
- **Prepare Excel export** (sidebar) builds a spreadsheet of your current view.

The [User guide](USER_GUIDE.md) covers every screen. If something goes wrong, see
[Troubleshooting](TROUBLESHOOTING.md).

## Where your data lives

Everything stays on your computer in `data/` (database, backups, exports, logs, photos). It's excluded from
Git. To start over, close the app and rename `data/`.
