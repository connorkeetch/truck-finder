# Quickstart

Get MotorSift running and see it work in about five minutes. You don't need an API key for this.

## 1. Install and start

You need **Python 3.12 or newer**; Python 3.12 is the tested version. The launcher also checks an existing
`.venv` and asks you to recreate it if its Python is older than 3.12. On Windows, tick **Add python.exe to PATH**
during install. See [Release checks](PUBLIC_RELEASE.md) for the tested platform scope.

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

**Try demo** imports synthetic cars, SUVs, and Rivian R1T listings directly into an empty workspace. Every demo vehicle is
labeled **DEMO**, and its listing URLs point at `example.com`. This import needs no provider credentials and
does not run your configured listing connectors.

1. On the empty **Inventory** page, choose **Try demo**. The app loads clearly labeled synthetic listings
   without provider credentials.
2. Explore the sidebar filters, try **Cards | Table**, and star a few vehicles for **My shortlist**.
3. Click a vehicle's photo or name to open its details: price history, where it's sold, and evidence for each
   equipment claim.
4. Tick **✓** on two or three vehicles and press **Compare** in the selection controls.

When you're done exploring, remove the fake data with **Settings → Backup & data → Purge all demo data**.
The optional **Demo** connector under **Sources → Automatic connectors** is a separate way to simulate later
inventory snapshots. **Refresh listings** runs enabled, configured connectors for the brands selected in its picker.

## 3. Set up your own search

Choose **Set up my search** on an empty Inventory page, or open **Settings** from the top navigation:

1. **Location → Home ZIP**: your ZIP code, so distances and radius searches work.
2. **Collection scope**: the make/model pairs to collect, for example:

   | Make | Model |
   |---|---|
   | Ford | F-150 Lightning |
   | Toyota | RAV4 |

   Also set the price, mileage, year and distance limits sent to the provider. Make these a little *broader*
   than what you want to see. You narrow the view later with Inventory filters, which cost no API calls.
3. **Vehicle filters**: your normal view (max price, max miles, years, distance).

## 4. Get listings in

Pick whatever fits. You can mix them, and duplicates merge by VIN.

| You have | Do this | Guide |
|---|---|---|
| An Auto.dev or MarketCheck API key | **Settings → API credentials**, then **Inventory → Refresh listings** | [Get a key and connect](API_KEYS.md) |
| A spreadsheet of listings | **Import listings** on an empty Inventory page, or **Sources → CSV / JSON import** | [Importing](IMPORTING.md) |
| Saved-search alert emails | Drop the `.eml` files into **Sources → Email alerts** | [Importing](IMPORTING.md#email-alerts) |
| A listing open in your browser | Copy the page text, then **Add vehicle → Paste listing** | [Importing](IMPORTING.md#paste-a-listing) |
| Just a VIN | **Add vehicle → By VIN** (1 Auto.dev call) | |

Want something to import right now? Try the bundled sample file:
**Sources → CSV / JSON import → upload `examples/sample_listings.csv` → Import**.

Need a provider account? [Get API keys](API_KEYS.md) links to official signup/key pages and explains package
access and local/Railway storage. Start with one provider. For MarketCheck, explicitly subscribe to an API
package before generating a key; creating a login alone does not complete setup.

## 5. Day-to-day

- **Refresh listings** whenever you want fresh prices. Each run tells you what's new, what dropped, and what wasn't
  seen.
- **★** a vehicle to add it to **My shortlist**, where you track what still needs proof from the seller.
- **🚫 Not interested** hides a vehicle everywhere, even if it shows up again on another site.
- Narrow your view in Inventory's **sidebar filters**. The active-filter summary shows what is applied;
  changing display filters does not fetch listings.
- **Save as my default filters** keeps the view for future sessions, Dashboard, and Excel. **Reset to saved
  defaults** restores that view; **Clear all** broadens the current view without overwriting your saved defaults.
- **Sources → Tools → Prepare Excel export** builds a spreadsheet using your saved default filters.

The [User guide](USER_GUIDE.md) covers every screen. If something goes wrong, see
[Troubleshooting](TROUBLESHOOTING.md).

## Where your data lives

Everything stays on your computer in `data/` (database, backups, exports, logs, photos). It's excluded from
Git. To start over, close the app and rename `data/`.
