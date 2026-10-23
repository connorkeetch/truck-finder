# Historical research — Truck Finder's initial Rivian scope

Research date: **2026-10-20**. This is a frozen record of the initial Rivian-focused investigation, not current
setup guidance. Provider pricing, quotas, repository status, site terms, and product specifications below may
have changed. "Verified" describes checks reported during that original session, not verification today.
Use the current [README](README.md) and [Sources](docs/SOURCES.md) for application behavior.

## 1. Bottom line

| Decision | Why |
|---|---|
| **Auto.dev Listings API is the primary automatic source** | Documented REST API, free plan (1,000 calls/month, no card), nationwide dealer listings with VIN, price, miles, dealer, location and VDP link. Called directly from Python, so no Node.js dependency. |
| **MarketCheck is a secondary connector** | Inventory API with dealer + some private-party listings. The plan examined during this investigation limited searches to a **100-mile radius**; verify current account restrictions. |
| **NHTSA vPIC is used for VIN enrichment** | Free government API, no key. **Verified live**: for Rivian R1T VINs it returns the drive unit (`Dual Motor` / `Triple Motor` / `Quad Motor`), trim family, model year and plant. It does *not* report battery pack or the Performance upgrade. |
| **No scraping of retail/classified sites** | CarMax, Carvana, AutoTrader, Cars.com, CarGurus, KSL and Facebook all restrict automated collection in their terms. Those sites are covered by **saved-search email alerts**, **user-initiated assisted capture**, and **manual entry**. |
| **Build our own (small) aggregation core** | No maintained, licensed, US-focused open-source project does VIN-level dedup + history + change detection for a specific model. The pieces we need are small; we reuse libraries (openpyxl, zipcodes, keyring, BeautifulSoup) rather than whole projects. |

## 2. Requested repositories

| Repository | Maintenance (verified) | License (verified) | What it offers | Reuse decision |
|---|---|---|---|---|
| [auto-dot-dev/sdk](https://github.com/auto-dot-dev/sdk) | Very active: last push 2026-10-19; TypeScript | GitHub reports **no license file** at the repo root (README badge points at the npm package's license) | TypeScript SDK, CLI and MCP server for auto.dev: `decode`, `photos`, `listings` (free); specs, build, recalls, payments, APR, TCO (Growth $299/mo+); plate-to-VIN, taxes (Scale). Remote MCP at `https://mcp.auto.dev/mcp`. | **Not vendored.** We call the same documented REST endpoint (`GET https://api.auto.dev/listings`, `Authorization: Bearer`) from Python. The MCP server is handy for ad-hoc questions from Claude, but an app needs deterministic code, not an LLM tool loop. |
| [drivly/auto-dev-skill](https://github.com/drivly/auto-dev-skill) | Last push 2026-08-20, 18★ | **MIT** | Agent "skill": markdown docs for the v2 listings API (filters, ranges, `.not` negation, response fields), pricing tiers and error handling. | **Used as reference** for parameter names, pricing and error recovery. No executable code to reuse. |
| [Simon-Cheek/KSLCarScraper](https://github.com/Simon-Cheek/KSLCarScraper) | Last push 2024-11-28, 0★ | **MIT** | Posts to KSL's internal Next.js proxy (`cars.ksl.com/nextjs-api/proxy`, endpoint `/classifieds/cars/search/searchByUrlParams`) with spoofed browser-identity headers, then ranks deals with a price-vs-mileage linear regression. | **Not used.** Undocumented private endpoint with a spoofed client identity — exactly what this project must avoid. The regression "deal score" idea is a possible future feature. |
| [nishantgoyal01/autohive](https://github.com/nishantgoyal01/autohive) | Last push 2026-06-01, 0★ | **None** (all rights reserved) | BeautifulSoup/Playwright scraper for CarDekho (India), pandas cleaning, SQLite, Streamlit dashboard. | **Not reusable** (no license, wrong market, scraping). Confirms the SQLite + Streamlit + Excel stack is a sensible shape. |
| [MarketcheckCarsInc/marketcheck_api_sdk_python](https://github.com/MarketcheckCarsInc/marketcheck_api_sdk_python) | **Stale**: last push 2018-08-25 | None detected | Swagger-generated Python client for an older API version. | **Not used.** The v2 REST API is simple; a 100-line `requests` adapter is easier to maintain than an 8-year-old generated client. |

## 3. Better / additional candidates found

| Project / service | Notes (verified unless stated) | Decision |
|---|---|---|
| **NHTSA vPIC** (`vpic.nhtsa.dot.gov/api`) | Free, keyless, batch endpoint `DecodeVINValuesBatch` (50 VINs/call). Probed Rivian VDS patterns live: position 4 `T` = R1T; drive-unit codes are model-year specific (e.g. 2023 `7FCTGA…` → Quad, `7FCTGB…` → Dual; 2026 `7FCTGB…` → Triple). | **Used** for motor enrichment (confidence *high*), only for real VINs, results cached as attributes. |
| [davidpeckham/vpic-api](https://github.com/davidpeckham/vpic-api) | MIT, Python vPIC client, last push 2024-01 | Not needed — one endpoint. |
| [Wal33D/nhtsa-vin-decoder](https://github.com/Wal33D/nhtsa-vin-decoder) | MIT, vPIC wrapper with offline WMI fallback, last push 2025-10 | Not needed. |
| [AlexaAndreas99/carwatch](https://github.com/AlexaAndreas99/carwatch) | MIT, Oct 2026; tracks Romanian listing sites with price history and delisting detection | Different market; validates the observation/"missing vs. sold" model we use. |
| [Frojoe6969/usa-car-search](https://github.com/Frojoe6969/usa-car-search) | MIT; scrapes CarGurus, AutoTrader, Cars.com, Craigslist | Not used (scraping). |
| [K0rsantan/reverse-engineered-apis](https://github.com/K0rsantan/reverse-engineered-apis) | "Unofficial" AutoTempest client | Not used (reverse-engineered private API). |
| Apify actors (Carvana / AutoTempest / CarGurus scrapers), `rebrowser/carguruscom-dataset` | Commercial scraping | Not used. |
| **Rivian Pre-Owned** (`rivian.com/configurations/list?INVENTORY_TYPE=PRE_OWNED_VEHICLE`) | Official R1 Shop pre-owned inventory. Listings can show options, odometer, VIN-specific warranty and history. Verify current purchase eligibility, inspection and return terms directly with Rivian. | Saved link + assisted capture/manual; useful for confirming listed options. |
| **Rivian Roamer** (`rivianroamer.com`) | Independent owner-run companion site with an inventory browser; no public API documented. | Saved link only. |
| `zipcodes` (PyPI) | MIT, bundled offline ZIP → lat/lon data | **Used** for straight-line distance from the configured home ZIP without a network call. |
| `keyring` | OS credential store (Windows Credential Manager / macOS Keychain / Secret Service) | **Used** for API keys entered in the UI. |

## 4. Automotive inventory APIs

| | Auto.dev | MarketCheck | NHTSA vPIC |
|---|---|---|---|
| What | Dealer retail listings (+ wholesale) | Dealer + some private-party listings, history | VIN decoding only |
| Auth | `Authorization: Bearer <key>` (verified: unauthenticated → HTTP 401 JSON) | `api_key` query param (verified: unauthenticated → HTTP 401) | none |
| Free tier | 1,000 calls/month hard cap, 5 req/s, **20 results/page** on Free (100 Growth, 500 Scale; larger `limit` silently clamped) | 500 calls/month, 5 req/s, **100-mile radius** (pricing page dated June 2024 — re-check) | unlimited (fair use) |
| Paid | Growth $299/mo + $0.0015/listing call; Scale $599/mo | Basic $299/mo, Standard $749/mo + data fees | — |
| Pagination | `page`/`limit`, `links.next` (switches to cursors past ~page 50), `includes=total` for counts | `start`/`rows` (max 50); HTTP 422 past plan limit | — |
| Freshness | "Real-time pricing and availability"; `/listings/{vin}` returns `removedAt` for delisted vehicles | `first_seen_at`/`last_seen_at` per listing | — |
| Rivian coverage | **Not verifiable without a key.** The app logs the provider's reported total on every run so you can judge coverage on day one. | Same. | Verified for R1T VIN patterns. |
| Cost of one run | ~⌈listings ÷ 20⌉ calls. 300 R1Ts → 15 calls → ~60 runs/month on Free. | ~⌈listings ÷ 50⌉ calls within 100 mi. | 1 call per 50 new VINs. |

Other APIs considered but not integrated (no free tier suitable for a personal app, consumer API discontinued,
or listing coverage unclear): Edmunds (public API retired), CarsXE, Vehicle Databases, DataOne. These are
general knowledge, not verified this session.

**Is Auto.dev the best foundation?** For a free, personal, nationwide dealer feed: yes. Its MCP/SDK are good
for exploration, but the app talks to the REST API directly so runs are deterministic, cheap, and testable.

## 5. Original site-access notes

These notes record the original conservative implementation choices, not a legal determination that a
particular use is permitted. Check current provider/site terms for the intended use.

| Site | Automated collection | What Truck Finder does |
|---|---|---|
| Facebook Marketplace | Meta's Terms prohibit accessing or collecting data "using automated means" without permission | **Manual only.** The extension and the capture receiver refuse facebook.com. |
| KSL Cars | KSL's terms restrict automated access (their page did not load in this session; treat as prohibited) | Email alerts, assisted capture, manual |
| CarMax, Carvana, AutoTrader, Cars.com, CarGurus, TrueCar, AutoTempest | Terms of use for these sites generally prohibit robots/scrapers/data mining (general knowledge; Carvana's terms page returned HTTP 403 to automated fetch in this session) | Email alerts where offered, assisted capture, manual. Dealer inventory that these sites syndicate often appears through Auto.dev/MarketCheck anyway. |
| Rivian.com | Treat as no automated collection | Saved link, assisted capture, manual |
| Independent dealers | Varies | Mostly covered by the APIs; otherwise assisted capture/manual |

**Assisted capture behavior:** it never navigates, paginates, schedules, or fetches inventory pages. The user
opens the page, highlights or copies what they want, and clicks. The extension uses only `activeTab` + `scripting`
(granted per click) and can only talk to `127.0.0.1:8765`. Nothing is saved until the user reviews it.

## 6. Rivian facts used (and how far they are trusted)

* **Generation**: Gen 2 R1 began with model year 2025, so MY2022–2024 → Gen 1, MY2025+ → Gen 2. Applied from
  the VIN's model-year character (confidence *high*) or a listed year (*medium*). User can override.
* **Motor**: from vPIC (*high*) or listing text (*low*). vPIC can't distinguish Performance Dual from Dual; a
  listing that says "Performance Dual" refines a vPIC "Dual" without being flagged as a conflict.
* **Battery, EPA range, wheels, tonneau, in-service date, warranty, title, accidents**: only from listing data
  or the user. Never inferred from trim or year. Unknown stays unknown.
* **Warranty terms** (defaults, editable): 5 yr/60,000 mi comprehensive; 8 yr battery & drive unit
  (175,000 mi Large/Max, 150,000 mi Standard). Remaining coverage is computed **only** when an in-service date is
  known. Verify for the specific VIN with Rivian.
