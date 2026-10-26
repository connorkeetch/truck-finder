# Improvements

Known issues and ideas, gathered while writing the open-source docs (October 2026). Each item says where the
problem is, why it matters, and a suggested fix. Items marked **verified** were reproduced by running the
code. The rest come from reading it.

Good first tasks are marked 🟢.

## Before announcing the release

| # | What | Why | Suggested fix |
|---|---|---|---|
| R2 | 🟢 No screenshot in the README | A picture of the Inventory cards sells the project in seconds | Run with demo data in a throwaway data folder, capture Inventory + vehicle details, save under `docs/images/` |
| R3 | Turn on GitHub **private vulnerability reporting** | [`SECURITY.md`](../SECURITY.md) tells people to use it | Repository **Settings → Code security** |
| R4 | 🟢 Python version is stated three ways | README says 3.12. `launcher.py` accepts 3.10+. TROUBLESHOOTING says "3.10+". CI tests only 3.12. | Either require 3.12 in `launcher.py`, or add 3.10/3.11 to the CI matrix and document "3.10+" |
| R5 | 🟢 CI doesn't test macOS | `run.sh` and `scripts/create_mac_launcher.sh` are shipped for macOS | Add `macos-latest` to `.github/workflows/tests.yml` |
| R6 | No version number or changelog | Users can't tell what changed between pulls. The extension says 1.1.0, but the app has no version. | Add `__version__` in `rivian_finder/__init__.py`, a `CHANGELOG.md`, and Git tags |
| R7 | 🟢 No `CODE_OF_CONDUCT.md` | GitHub's community checklist expects one | Add the Contributor Covenant |

## Bugs

### B1. Negated tonneau text is read as "yes" (verified)

`importers/manual.py` → `_tonneau_from_text()`. CSV/JSON/manual values like `not powered` or
`non-powered soft cover` become **yes**, because the check looks for "power" after only a few negations.
`manual tonneau` becomes **unknown**, although the project treats a manual or soft cover as **no**.

| Input | Today | Expected |
|---|---|---|
| `not powered` | yes | no |
| `non-powered soft cover` | yes | no |
| `manual tonneau` | unknown | no |

Fix: check negations (`not`, `non-`, `no `, `without`, `manual`, `soft`) before positives, and add a
parametrized test.

### B2. 🟢 Sample CSV uses a retired tonneau value

`examples/sample_listings.csv` row 1 has `tonneau=listed_unverified`. It only imports as "yes" because of the
loose matching in B1. Change it to `yes`. While you're there, add a non-Rivian row and the newer columns
(`epa_range`, `tow_capacity_lbs`, `wheels`).

### B3. `RIVIAN_FINDER_PORT` in `.env` is ignored by the launcher

`launcher.py` reads only `RIVIAN_FINDER_DATA_DIR` from `.env`. `PORT` and `NO_BROWSER` come from the real
environment. But `.env.example` and TROUBLESHOOTING both say to set the port in `.env`. Worse, the app *does*
load `.env`, so **Settings → Phone access** shows the `.env` port while the server runs on 8501.

Fix: have `launcher.py` parse all `RIVIAN_FINDER_*` keys from `.env` (it already has the parsing loop in
`data_dir()`).

### B4. "Full JSON export" leaves out the checklist and contact log

`backup.py` → `EXPORT_TABLES` was written before migrations 003–006. It skips `checklist` and `contacts`
(data you typed yourself), plus `link_checks`, `recalls` and `api_usage`. Restoring from a JSON export silently
loses checklist items and seller-contact history.

Fix: build the list from `sqlite_master` (minus `schema_migrations`), or add the missing tables and a test that
fails when a new table isn't exported.

### B5. Old manual backups get pruned

`backup.py` → `prune()` keeps the newest 30 files, counting manual and automatic backups together. A manual
"before I try something" backup is deleted after about a month of daily auto-backups.

Fix: prune only `*_auto.db`, or keep manual backups separately.

### B6. Default model-year range already excludes 2027 models

`config.DEFAULT_SETTINGS` sets `year_max: 2026` for filters and collection. `sources/autodev.build_params()`
defaults to 2026 too. The year sliders in `ui/inventory.py` and `ui/settings_page.py` top out at 2027.
Most model-year 2027 vehicles go on sale during 2026, so new users miss them by default.

Fix: compute the default and slider maximum from `date.today().year + 1`.

### B7. Seller names with a dash separator swallow the city (verified)

Pasted text `Sold by: Sample Motors - St George, UT 84770` gives seller **and** city `Sample Motors - St George`.
The `·` and `,` separators work. Fix in the seller/location parsing used by `importers/capture.draft_from_text()`.

## Unverified email and page formats

The KSL and RivianForums importers (October 2026) are tested against **synthetic** samples, because the real
formats weren't available while building them:

| What | Risk | Next step |
|---|---|---|
| KSL saved-search alert emails | Real emails may use tracking links that hide the listing address, which would give zero listings | Import one real KSL alert. If it fails, save a redacted copy as a test fixture and adjust `email_alerts.py`. |
| KSL listing-page labels ("Title Type", "Seller Type") | A different label layout means the seller type or branded title isn't detected | Paste one real KSL ad and check the draft |
| RivianForums watched-forum emails | The subject and link layout were modeled on XenForo's usual notification email | Import one real notification and compare with `tests/fixtures/synthetic_rivianforums_alert.eml` |
| Forum threads whose title has no year, price or WTB | The title isn't found in a full-page paste, so price and miles come from the post | Fall back to the browser tab title, which the extension already sends |
| Automatic mailbox import against real Gmail | Tested only against a fake IMAP server | Turn it on with a real app password and press **Check mailbox now** |

## More sources

| Idea | What we know | Next step |
|---|---|---|
| MarketCheck private-party search (`/v2/search/car/fsbo/active`) | One facets-only call (Oct 26, 2026): 67,571 listings from 24 sites, including 131 Rivians. Craigslist, KBB, FindMyElectric, PrivateAuto, eBay and OfferUp are in it; KSL isn't. Updated daily. Billed at a premium rate. | A second search mode in `sources/marketcheck.py` mapping `source` to site keys, with its own call budget |
| Alert emails from more sites (Cars & Bids, Bring a Trailer, FindMyElectric) | The mailbox import reads any email with listing links, but site-specific layouts are untested | Import one real email from each and add a redacted fixture |

## Leftovers from the Rivian-only days

The app now supports any make/model, but some defaults still assume a Rivian R1T shopper near Draper, Utah.
Most of these are latent, but they surprise contributors and can leak into edge cases.

| Where | What | Suggested fix |
|---|---|---|
| `sources/base.py`, `sources/autodev.py`, `sources/marketcheck.py`, `pipeline.py`, `queries.py` | `"84020"` (Draper, UT) as the fallback ZIP | No fallback: require Home ZIP for radius searches (`services.run_sources` already checks) |
| `services.add_listing_link()`, `enrich.py`, `queries.filter_checks()` | A vehicle with no make/model is treated as **Rivian R1T** | Leave unknown as unknown. Only apply R1T rules when the make/model says so. |
| `extract.extract_attributes()` | Text with no detectable make is parsed with Rivian battery rules | Default to generic parsing when the make is unknown |
| `ui/sources.py` | CSV template downloads as `rivian_listings_template.csv` | 🟢 Rename to `truck_finder_listings_template.csv` |
| `importers/manual.csv_template()` | Template example row is a Draper, UT Rivian | 🟢 Use a neutral example |
| Package, env vars, keyring service, task folder, capture server header | Named `rivian_finder` / `RIVIAN_FINDER_*` / `rivian-finder` / `RivianFinder` | Accept `TRUCK_FINDER_*` env vars as aliases first. A package rename can come later. |
| `.streamlit/config.toml` | Comment says "Rivian-ish amber" | 🟢 Cosmetic |

## Security hardening

See [`SECURITY.md`](../SECURITY.md) for the current model.

| What | Why | Suggested fix |
|---|---|---|
| Phone-access PIN can be 4 digits, and the 1.5 s delay is per browser session | Opening new sessions in parallel gets around the delay. 10,000 PINs is a small space on a LAN. | Require 6+ digits, and add a global failed-attempt counter with a lockout in `access.py` |
| On the desktop, the PIN gate trusts any request whose IP Streamlit reports as `None` (local). The hosted version checks a proxy token instead. | A home-made reverse proxy or tunnel in front of the desktop app makes remote users look local | Keep pointing people to the cloud deployment. Optionally require the PIN whenever an `X-Forwarded-For` header is present. |
| `backup.import_json()` builds `INSERT` column lists from keys in the JSON file | A crafted file could inject SQL into your own database. Low risk because it's your own file. | Check keys against `PRAGMA table_info(<table>)` |
| `USER_AGENT` has no contact URL | Site owners can't find out who is checking links | 🟢 `TruckFinder/1.0 (+https://github.com/connorkeetch/truck-finder)` |

**Hosted deployment** ([CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md)):

| What | Why | Suggested fix |
|---|---|---|
| Caddy's `basic_auth` doesn't limit repeated login attempts | Only the strength of the password stops guessing | Recommend a long random password (SECURITY.md does). Consider a rate-limiting Caddy plugin or a small fail counter. |
| 🟢 `cloud.schedule_timezone()` falls back to `America/Denver` when `TZ` isn't set | Another user's searches would run at Mountain-time hours without warning | Fall back to `UTC` and log a warning, or refuse to start scheduling until `TZ` is set |

## Developer experience

| What | Suggested fix |
|---|---|
| Adding a connector means editing five places (see [Architecture](ARCHITECTURE.md#adding-a-listing-source)), and `pipeline.run_source()` hard-codes `("autodev", "marketcheck")` for make/model filtering | A small registry in `sources/__init__.py`: each adapter declares its key, name, env var, monthly cap and whether it is a "search API" |
| `API_CAPS` (1,000 Auto.dev / 500 MarketCheck) is hard-coded to free-plan quotas | Make the monthly cap a setting so paid-plan users aren't stopped early |
| No `pyproject.toml`: nothing to `pip install`, no console command, no lint config, even though the code has `# noqa` markers for Ruff | Add `pyproject.toml` with project metadata, a `truck-finder` entry point, and Ruff settings. Run `ruff check` in CI. |
| On the desktop, scheduled searches are Windows-only | `cloud.Scheduler` already runs searches inside the server process for the hosted version. Reuse it on macOS/Linux while the app is open, or write a `launchd` plist / `systemd --user` timer from **Settings → Alerts**. [Automation](AUTOMATION.md#macos-and-linux) documents cron for now. |
| `python -m rivian_finder.cli run` always runs every connector and brand | Add `--source` and `--brand` options (`services.run_sources()` already takes them) |

## Docs follow-ups

These are in older docs that the new guides didn't rewrite:

- **`docs/USER_GUIDE.md`** (490+ lines) mixes general features with Rivian-only ones (battery, subframe, EPA,
  warranty rules). Split it: general features first, then a **Rivian R1T extras** section. Move personal
  observations ("Rivian's own pre-owned listings currently come through MarketCheck without photos") into
  Sources or drop them.
- **`docs/TROUBLESHOOTING.md`** has a stale "Fixed:" row (distances of ~7,356 mi), provider quota numbers that
  will go out of date ("5 req/s and 1,000 calls/month"), and says "Python 3.10+". Group the rows into
  Install / Searching / Data / Notifications.
- **`.env.example`** should say which variables the launcher reads (until B3 is fixed).
- **Photos**: README says `static/photos/`, USER_GUIDE says `data/photos/`. Both are right (the cache lives in
  `data/photos/` and is mirrored to `static/photos/` for the browser). Say that once, in
  [Configuration](CONFIGURATION.md#where-your-data-lives).
