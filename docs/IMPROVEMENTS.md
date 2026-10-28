# Improvements

Known issues and ideas, gathered while writing the open-source docs (October 2026). Each item says where the
problem is, why it matters, and a suggested fix. Items marked **verified** were reproduced by running the
code. The rest come from reading it.

Good first tasks are marked 🟢.

## Before announcing the release

| # | What | Why | Suggested fix |
|---|---|---|---|
| R2 | Done: synthetic screenshots in the README | Inventory, vehicle details, and phone layout are shown from an isolated demo workspace | Keep `docs/images/` screenshots current when the UI changes |
| R3 | Done: GitHub **private vulnerability reporting** enabled | Confirmed October 28, 2026, matching [`SECURITY.md`](../SECURITY.md) | Keep the reporting instructions current |
| R4 | Done: enforce the Python minimum | `launcher.py` requires 3.12+ for the host interpreter and an existing `.venv`; only 3.12 is tested | Verify additional versions before expanding the tested support matrix |
| R5 | 🟢 CI doesn't test macOS | `run.sh` and `scripts/create_mac_launcher.sh` are shipped for macOS | Add `macos-latest` to `.github/workflows/tests.yml` |
| R6 | Beta version and release docs prepared | `__version__ = "0.2.0b1"` matches the [v0.2.0b1 prerelease](https://github.com/connorkeetch/truck-finder/releases/tag/v0.2.0b1) and dated [changelog](../CHANGELOG.md) | Record exact validation scope in [Release checks](PUBLIC_RELEASE.md) |
| R7 | 🟢 No `CODE_OF_CONDUCT.md` | GitHub's community checklist expects one | Add the Contributor Covenant |

## Bugs

### B1. Fixed: negated powered-tonneau descriptions

`importers/manual.py` → `_tonneau_from_text()` handles `not powered`, `non-powered soft cover`, and manual
covers before positive powered-cover claims. Regression tests cover these descriptions and preserve legacy
structured values such as `listed_unverified`.

### B2. 🟢 Sample CSV could use current fields and broader examples

`examples/sample_listings.csv` row 1 uses `tonneau=listed_unverified`, a supported legacy alias for `yes`.
Modernize the example to `yes`, add a non-Rivian row, and show newer columns (`epa_range`,
`tow_capacity_lbs`, `wheels`). This is sample cleanup, not a dependency on B1's former parsing bug.

### B3. `RIVIAN_FINDER_PORT` in `.env` is ignored by the launcher

`launcher.py` reads only `RIVIAN_FINDER_DATA_DIR` from `.env`. `PORT` and `NO_BROWSER` come from the real
environment. `.env.example` suggests setting the port in `.env`, but the launcher will still use its shell
environment or default. The app *does* load `.env`, so **Settings → Phone access** can show a different port
from the running server. The configuration/troubleshooting guides now explain the workaround.

Fix: have `launcher.py` parse all `RIVIAN_FINDER_*` keys from `.env` (it already has the parsing loop in
`data_dir()`).

### B4. JSON export omission — fixed in 0.2.0 beta 1

`backup.py` → `EXPORT_TABLES` now includes checklist, contacts, API usage, recalls, link checks, and email-inbox
records. Regression coverage checks that application tables are exported and that the added records survive
an export/import round trip. Older exports cannot recover records that were never included.

### B5. Old manual backups get pruned

`backup.py` → `prune()` keeps the newest 30 files, counting manual and automatic backups together. A manual
"before I try something" backup is deleted after about a month of daily auto-backups.

Fix: prune only `*_auto.db`, or keep manual backups separately.

### B6. Fixed: next-model-year searches

New workspaces and provider fallback ranges include the current year plus one. The year sliders grow with
the current year and any saved upper limit. Explicit year limits in existing workspaces are preserved.
Regression tests cover 2027 general-vehicle searches and saved-limit compatibility.

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
| `ui/sources.py` | CSV template downloads as `rivian_listings_template.csv` | 🟢 Use a neutral public filename in a future compatibility pass |
| `importers/manual.csv_template()` | Template example row is a Draper, UT Rivian | 🟢 Use a neutral example |
| Package, env vars, keyring service, task folder, capture server header | Named `rivian_finder` / `RIVIAN_FINDER_*` / `rivian-finder` / `RivianFinder` | Intentionally retained for compatibility; document the names rather than renaming saved paths or task identifiers |
| `.streamlit/config.toml` | Comment says "Rivian-ish amber" | 🟢 Cosmetic |

## Security hardening

See [`SECURITY.md`](../SECURITY.md) for the current model.

| What | Why | Suggested fix |
|---|---|---|
| Phone-access PIN can be 4 digits, and the 1.5 s delay is per browser session | Opening new sessions in parallel gets around the delay. 10,000 PINs is a small space on a LAN. | Require 6+ digits, and add a global failed-attempt counter with a lockout in `access.py` |
| On the desktop, the PIN gate trusts any request whose IP Streamlit reports as `None` (local). The hosted version checks a proxy token instead. | A home-made reverse proxy or tunnel in front of the desktop app makes remote users look local | Keep pointing people to the cloud deployment. Optionally require the PIN whenever an `X-Forwarded-For` header is present. |
| `backup.import_json()` builds `INSERT` column lists from keys in the JSON file | A crafted file could inject SQL into your own database. Low risk because it's your own file. | Check keys against `PRAGMA table_info(<table>)` |
| `USER_AGENT` has no contact URL | Site owners can't find out who is checking links | 🟢 Include the public MotorSift name, version, and repository URL |

**Hosted deployment** ([CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md)):

| What | Why | Suggested fix |
|---|---|---|
| Caddy's `basic_auth` doesn't limit repeated login attempts | Only the strength of the password stops guessing | Recommend a long random password (SECURITY.md does). Consider a rate-limiting Caddy plugin or a small fail counter. |
| 🟢 `cloud.schedule_timezone()` falls back to `America/Denver` when `TZ` isn't set | Another user's searches would run at Mountain-time hours without warning | Fall back to `UTC` and log a warning, or refuse to start scheduling until `TZ` is set |

## Developer experience

| What | Suggested fix |
|---|---|
| Adding a connector means editing five places (see [Architecture](ARCHITECTURE.md#adding-a-listing-source)), and `pipeline.run_source()` hard-codes `("autodev", "marketcheck")` for make/model filtering | A small registry in `sources/__init__.py`: each adapter declares its key, name, env var, monthly cap and whether it is a "search API" |
| `API_CAPS` (1,000 Auto.dev / 500 MarketCheck) is a fixed local safety budget, independent of provider entitlements | Make the local cap a setting for users who have verified their provider package and spending limits |
| No `pyproject.toml`: nothing to `pip install`, no console command, no lint config, even though the code has `# noqa` markers for Ruff | Add `pyproject.toml` with project metadata, a `motorsift` entry point, and Ruff settings. Run `ruff check` in CI. |
| On the desktop, scheduled searches are Windows-only | `cloud.Scheduler` already runs searches inside the server process for the hosted version. Reuse it on macOS/Linux while the app is open, or write a `launchd` plist / `systemd --user` timer from **Settings → Alerts**. [Automation](AUTOMATION.md#macos-and-linux) documents cron for now. |
| `python -m rivian_finder.cli run` always runs every connector and brand | Add `--source` and `--brand` options (`services.run_sources()` already takes them) |

## Docs follow-ups

These are in older docs that the new guides didn't rewrite:

- **`docs/USER_GUIDE.md`** (490+ lines) mixes general features with Rivian-only ones (battery, subframe, EPA,
  warranty rules). Split it: general features first, then a **Rivian R1T extras** section. Move personal
  observations ("Rivian's own pre-owned listings currently come through MarketCheck without photos") into
  Sources or drop them.
- **`docs/TROUBLESHOOTING.md`** has a stale "Fixed:" row (distances of ~7,356 mi). Group the rows into
  Install / Searching / Data / Notifications.
- **`.env.example`** should say which variables the launcher reads (until B3 is fixed).
- **Photos**: README says `static/photos/`, USER_GUIDE says `data/photos/`. Both are right (the cache lives in
  `data/photos/` and is mirrored to `static/photos/` for the browser). Say that once, in
  [Configuration](CONFIGURATION.md#where-your-data-lives).
