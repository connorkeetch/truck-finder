# User guide

Truck Finder searches any make/model supported by the listing provider. Start in **Settings → Collection scope**
to save your make/model pairs and limits, and set your home ZIP before using distance-based searches. A new
workspace contains an editable Rivian R1T example; existing workspaces retain their saved preferences.
Model-specific Rivian and EV tools below apply only where that evidence is available.

## A typical shopping session

Browse on **Inventory**, work through favorites in **My shortlist**, and see the summary on **Dashboard**.
The other pages are under **More** in the sidebar.

1. **Run Search** (sidebar) opens a picker for the brands in your saved make/model searches.
   Choose any combination, or **All brands**, then **Start search**.
   The picker remembers your last submitted choice for this session. **Cancel**, the X,
   or clicking outside closes it without searching. **Sources → Run now** and **Run all enabled connectors**
   use the same picker. Saved search limits and connector call budgets still apply; unselected brands are left alone.
   Connectors run one by one; the result line tells you what changed, e.g.
   *"42 matching vehicles, 3 new, 2 price reductions, 1 missing since last successful scan."*
   If a source fails it says so and leaves its previous listings alone.
2. On **Inventory**, add anything you found yourself with **➕ Add a truck** (VIN lookup, paste a listing, manual,
   alert email).
3. Browse the **cards** (or switch to **Table** to edit motor, transport and notes in the row). **Click a photo or
   name** for its
   full details: ★ favorite and 🚫 not interested at the top, *Quick verify* (in-service date, battery, motor,
   tonneau, pasted warranty) below. Tick **✓** on several
   trucks to compare them or hide them together.
4. **Prepare Excel export** (sidebar) when you want to compare in a spreadsheet or share.

## Updated since last refresh

Inventory cards show badges for changes found in the latest **Run Search**, plus updates recorded afterward:
**New**, **New source**, **Price down / up $…**, **Source removed**, or **Not seen**. A price badge shows the net
change on one source listing within that refresh window; mirrored listings are not added together. Its details
identify the source and before/after prices. Table view and CSV exports include an **Updates** column.

Use the **Updates** filter to show only changed trucks, new listings, price changes, or listing status changes.
Your other Inventory filters still apply. An exact VIN or listing-link lookup includes matches outside the
Updates filter. Reloading or reopening the app keeps these badges; the next completed search starts a new window.

The collapsed **Sold, removed & not seen** area below the results stays available even when no active trucks
match your filters. **Recent status changes** identifies each source listing that was removed or not seen.
**All unavailable trucks** keeps trucks with no active listings accessible after later refreshes, including hidden
trucks. Ordinary Inventory filters do not hide this area; your demo-data preference still applies.

**Not seen** means absent from a complete scan, with a sale unconfirmed. Another source may still list the same
truck as active. **Sold or removed (reported)** means the provider reported removal or you marked it removed.
The first search establishes a baseline: “new” means first discovered by this app, rather than newly advertised
by the seller. Incomplete or failed searches are labeled and never establish that unseen listings were sold.

## Dashboard

* **Matching vehicles** — active trucks passing your current filters.
* **New / Price drops (7 days)** — among matching trucks.
* **Missing from last scan** — not observed in the last *complete* scan of that source. Not proof of sale.
* **Top matches** — requirements first, then personal score (0–100). The score uses your saved preferences and
  room under your budget, mileage and distance limits; it does not reward a particular brand's battery or motor names.

## My shortlist and requirements

Star vehicles in Inventory to add them to **My shortlist**. Active listings appear first. This page keeps favorites visible even when normal
inventory filters would hide them; trucks marked Not interested are excluded. The listing's
current status stays visible, including missing or removed listings.

Open **My shopping profile** to set minimum range and towing capacity and choose required or preferred
equipment. No comfort features are selected for you. Budget, mileage and distance use your saved default filters.
Choose **Required**, **Prefer**, or **Ignore** for numeric targets; a feature cannot be both required and preferred.

- **Meets requirements** means the saved required checks pass. It does not certify the truck's overall condition.
- **Needs verification** means required information is unknown, conflicting, or only advertised.
- **Does not qualify** means a saved limit or verified requirement fails.

Personal score helps rank candidates within those groups. Preferred features affect the score, not eligibility.
The legacy **Fit score** sort remains available separately. Inventory's **My requirements** filter lets you choose
which groups to view; leaving it empty keeps all groups. The same saved filter applies to Dashboard and exports.

Each favorite shows what needs proof, saved evidence, and a seller request you can copy. Record equipment as
**Advertised yes/no** when a listing or seller claims it, and **Verified yes/no** when you have checked supporting
evidence. Verified entries survive refreshes. Choosing **Unknown** clears your verification; historical source
claims remain available. Verify numeric range/towing values in the vehicle's **Verify equipment** tab.

**Open details → Checklist & contacts** exposes the existing inspection checklist and seller-contact/follow-up
tools. Seller requests are prepared locally for you to copy; the app does not send them. Updating requirements,
recording proof, and viewing favorites do not spend listing API calls.

## Where is it actually for sale?

Many sites only re-list dealer inventory. Truck Finder labels every listing:

* **🏷️ Seller's listing** — the page of whoever holds the truck: the dealer's own website, Rivian, CarMax,
  Carvana, or a private seller's ad (KSL, Facebook, or a private-party ad on AutoTrader/Cars.com).
* **🔁 Aggregator** — AutoTrader, Cars.com, CarGurus, TrueCar, AutoTempest, Autolist and similar.

Because listings are grouped by VIN, an AutoTrader alert and the dealer's own page (often supplied by Auto.dev or
MarketCheck) end up on the same truck automatically. The **Seller listing** column / button always points at the
seller's page. When a truck has only been seen on aggregators:

1. Click **Find seller** — a web search for the exact VIN (or the dealer name, or year + price + city).
2. Open the dealer's page, copy its URL, and paste it into **Vehicle details → Where it's sold → Link it**
   (optionally with the price shown there). Future scans that see the same VIN attach to it automatically.

MarketCheck also reports each dealer's website, shown as a **Dealer website** button.

**Wrong link?** In the truck's details, click the **✏️ pencil** next to *Open seller's listing* to paste the right
link or remove the wrong one. A link you added yourself is corrected in place; a provider's link is overridden for
that truck, so the next search can't put the wrong one back. Removing it brings back **Find seller**.

## Not interested (hiding trucks)

* **One truck**: click its name → **🚫 Not interested…** (top of the pop-up) → reason + optional note → *Hide this
  truck*. Use **Sold / dead link** when the seller's page is gone.
* **Several**: tick **✓** on each → in the sidebar box pick a reason → **🚫 Hide these**.
* **Vehicle details**: **🚫 Not interested…** → reason + optional note (e.g. "Carfax: rebuilt title, 2024 flood").
* Four reasons: **Title issues** (also records the title as branded), **Too far**, **Sold / dead link** (also marks
  its listings removed — they stay removed even if a provider keeps returning the listing, as Auto.dev sometimes does
  for days) and **Other**. Add a note for detail (e.g. "Carfax: rebuilt title, 2024 flood").
* Hidden trucks disappear from the Dashboard, Inventory, run counts and the Excel *Current Inventory* sheet (they're
  listed on the *Not Interested* sheet instead). They stay hidden if the same VIN shows up on another site; the run
  summary just notes "N updates on trucks you marked not interested".
* To undo: Inventory → **🚫 Hidden (n)** toggle → click the truck's name → **↩ Restore** (or tick ✓ on several →
  **↩ Restore**). Facts you recorded (like the branded title) are kept.

## Deal rating, negotiation, history

* **Deal rating** (Inventory *Deal* / *vs market* columns, top of each truck's page, Compare, Excel): the app
  estimates what each truck "should" cost from the listings you've collected — model year, mileage, battery, motor
  and whether a tonneau is listed — and compares the asking price. Each truck is left out of its own estimate.
  Trucks with a branded title or reported accident aren't used to set prices, and a branded truck is labeled
  *Not rated (branded title)* rather than a "deal". The comparables line ("9 comparable 2023 Quad trucks, median
  $54,900") is the sanity check. Ratings need at least 20 priced trucks and get better as you collect more.
* **⚠ Check title**: a truck priced 15% or more under the estimate (and without a verified clean title) is flagged
  instead of being called a great deal — in practice those have been branded/rebuilt. Open the Carfax; if it's
  branded, tick it in Inventory → reason *Branded / salvage / rebuilt title* → **🚫 Not interested**. That records
  the title as branded, hides the truck, and stops it from pulling down other trucks' estimates.
  Note: MarketCheck's `carfax_clean_title = false` is *not* used as evidence of a branded title — it is false for
  most ordinary dealer stock.
* **Negotiation**: *Days listed* takes the longest evidence available (MarketCheck days-on-market, the provider's
  first-seen date, or when Truck Finder first saw it — hover for which). *Price drops* counts cuts Truck Finder
  has observed. *Leverage* is a rule of thumb: High = listed 60+ days or 2+ cuts; Medium = 30+ days or 1 cut.
  The dealer's phone appears when MarketCheck supplies it.
* **Vehicle details → Price history → Price-drop patterns** shows the selected listing's average reduction,
  cumulative reductions, net price change, and observed time between cuts. The average amount is calculated per
  cut; increases can make the net change smaller than cumulative reductions. One listing timeline per vehicle is
  selected, so provider mirrors are not added together and differences between sources are not counted as cuts.
  Its source, observation window and recorded availability are shown beside the results.
  Rivian vehicles also show a benchmark for saved listings attributed to Rivian itself, with the number of cuts,
  trucks and intervals behind the averages. Unknown timing stays unknown when fewer than two cuts are recorded.
  A single observed interval is labeled as insufficient to establish a typical schedule. These are detection
  times from saved observations, rather than confirmed dealer change dates, and opening the page spends no
  listing API calls. Normal Inventory filters do not change this historical benchmark.
* **History & recalls** tab: the dealer's free Carfax link when Auto.dev provides one (check title, accidents,
  owners, and the first-sold date — that's the warranty in-service date), MarketCheck's Carfax clean-title /
  one-owner flags, and NHTSA recalls for the model year (refreshed weekly during Run Search; *Refresh recalls* forces
  it). Recalls are per model year; to see whether this exact truck has unrepaired recalls, open NHTSA's VIN lookup
  (it's reCAPTCHA-protected, so paste the VIN shown) or ask Rivian.

## Photos

Each truck gets one photo so you can tell them apart: taken from the provider's image link during Run Search (or
*Sources → Automatic connectors → Photos → Fetch missing photos*), from alert emails, or from the extension (the
page's preview image). A small copy is saved in `data/photos/`, so the picture stays after a listing disappears.
To change it: truck page → *Notes & identity* → *Photo* → paste an image URL (right-click a photo → *Copy image
address*) or upload a picture; *Go back to the listing's photo* undoes it. Rivian's own pre-owned listings
currently come through MarketCheck without photos — add one by hand if you like.

## Shipping estimates

Each vehicle's *Transport* comes from your typed amount first, then the configured local-pickup, seller-fee,
included-delivery, and base-plus-distance rules. Enter the seller's actual delivery charge when known.
Configure estimates under **Settings → Shipping**; a fresh workspace does not assume delivery is included or
apply a particular retailer's fee. Distance and transport figures are estimates rather than quotes.

**Fly & drive** is an optional EV calculator, disabled in fresh workspaces. It compares configured airfare,
ground costs, charging efficiency, initial charge, and electricity prices with transport. Set those assumptions
for the actual EV before enabling it in **💲 My price adjustments**. It does not calculate gasoline fuel costs.

## History flags (relist / flip detector)

*History flags* marks trucks that **changed dealers**, were **relisted after a gap**, or were **listed elsewhere
first** (MarketCheck reports more total days on market than days at the current dealer). Dealer-to-dealer moves are
often auction/wholesale flips — sometimes after a problem. Ask the seller why, and check the Carfax for auction and
ownership history. It needs at least two searches (or MarketCheck data) to show anything.

## Notes and favorites

* **Notes**: every truck's details have a **📝 Notes** box right under the warranty line. Type anything (tonneau,
  condition, what the seller said); it saves when you click outside the box or press Ctrl+Enter, and shows in the
  Table view's *Notes* column too.
* **Favorites**: click the **☆** next to a card's title to make it a favorite (it fills in **★**); click again to
  remove it. *★ Favorites only* (top of Inventory) shows just those.

## Alerts (optional)

*Settings → Alerts*: choose what to be told about (new matching trucks, favorite price drops, good deals, a minimum
drop), pick times (e.g. `08:00, 18:00`), then **Turn on scheduled search**. Windows runs the search in the
background while you're logged in (Task Scheduler → *RivianFinder*) and shows a notification; clicking it opens the
app if it's running. A run is skipped automatically when the month's free API calls are running low. **Send a test
notification** checks that notifications show (Focus Assist / Do Not Disturb can hide them). Log:
`data/logs/scheduled.log`.

## Phone access (optional)

*Settings → Phone access*: set a PIN, turn it on, and restart the app. Your phone (same Wi-Fi) opens the address
shown there (e.g. `http://192.168.1.17:8501`) and enters the PIN; this computer never asks. The first time, Windows
Firewall may ask — allow **private networks** only. Use it on home Wi-Fi, not public networks.

## Compare

Inventory → tick **✓** on 2–4 rows → **⚖ Compare** (top of the sidebar). The comparison opens as a pop-up;
its **Details** buttons open each truck's details. (**More → Compare** still works and defaults to your favorites.)
Green cells are the best of the group for that row: lowest price/miles/cost/distance/recalls, best deal, longest
listed and most price cuts (more leverage), highest battery/warranty/range/fit, confirmed tonneau, clean title.
Unknown values are never highlighted.

**💵 Payments** (below the comparison): one table per vehicle — *current vehicle sells for* → *cash left after payoff* →
*amount financed* → the monthly payment at two APRs. The header shows the out-the-door cost (price + sales tax +
fees + shipping). Set the sale-price range (from / to / step), both APRs and the term right there; they're
remembered. **🤝 Dealer trade-in offers** add a trade row for that dealer's vehicles. The caption compares tax and
loan amounts using your chosen tax-treatment settings; enter the rules and figures applicable to your purchase.
Offers match the vehicle's seller name. Payoff, tax rate, fees and tax treatment come from Settings → Loan assumptions.

## Inventory (the main workspace)

* **View: Cards | Table** (top right, remembered). **Cards** — two or three per row on a wide screen — show the
  photo, a **price tag colored by the deal rating** (green great/good, blue fair, orange above market, red
  overpriced, yellow ⚠ check title, gray not rated), your price with the list price struck through when a discount
  applies, *vs market*, and icon rows for miles, days listed, price drops, location · distance, seller, battery ·
  EPA range, motor, warranty, est. monthly and shipping, plus chips for branded title, near miss, uncertain battery,
  dead link and relists. Click the photo or name for details; tick the box on the photo to select it (compare /
  hide several in the sidebar). 40 cards show at first — **Show more** adds 40. **Table** is the editable grid with
  every column.

* **Search** matches VIN, seller, location, color, trim, sources and your notes. **Paste a VIN or a listing link**
  (e.g. `https://www.carvana.com/vehicle/4596079`) to find that truck *whatever your filters say* — a banner tells
  you whether it's in your list or exactly what hides it ("price $65,590 is $590 over your $65,000 max").
* **➕ Add a truck** (top): *By VIN* (asks Auto.dev for that VIN, 1 API call — or tells you you already have it),
  *Paste listing*, *Manual*, *Alert email*. Same tools as **More → Sources**.
* **Rivian Pre-Owned pages**: open a truck on rivian.com, press Ctrl+A, Ctrl+C and paste into *Paste listing* (you
  can paste several pages at once). The app recognises Rivian's page, shows what it found, and **Save from Rivian**
  adds or updates each truck by VIN: price, miles, pickup location, colors, wheels, EPA range, and — as verified
  values — battery, motor, powered tonneau (Yes only if Rivian's build list shows *Powered Tonneau Cover*) and the
  exact warranty dates and mileage caps.
* **Filters** (expander): price, mileage, years, distance, deal rating, seller type, generation, battery, motor,
  tonneau status, states, branded titles, accidents, missing/removed, demo data, plus:
  * **Deal rating**: choose any combination of Great deal, Good deal, Fair price, Above market, Overpriced,
    Check title, or the separate Not rated categories. Accident warnings remain on the listing; selecting Good
    deal also includes Good deal listings labeled with an accident warning unless you hide reported accidents.
  * **Seller type**: show dealers, private sellers, manufacturers, retailers, or unknown sellers.
  * **Only listings with price drops**: show listings with at least one recorded price reduction. This uses
    saved history and does not start a new search.
  * **Include near misses** (on): also shows trucks up to 5 % over your max price or 10 % over your max miles,
    marked **⚠** after the truck's name; the reason is at the top of its details. Nothing else is relaxed.
  * **Use my price after discounts** (on): the price filter uses *Your price* — e.g. Carvana's $1,000 trade-in
    discount (Settings → Loan assumptions → Seller discounts). The *Price* column then reads
    "$59,990 (list $60,990)".
  * *Save as my default filters* stores them.
* Unknown values are **not** hidden by numeric filters, and a truck whose sources disagree on battery or motor is
  kept if *any* claimed value matches — you never miss a truck because a field was missing or mislabeled.
* **Sort by** applies to both Cards and Table. In addition to fit, adjusted price and existing sorts, choose deal
  rating, price/mileage/distance in either direction, monthly payment, range, towing capacity, model year,
  dollar savings versus market, or the most recent price change. Missing values stay at the end. **Best deal**
  puts ordinary deal ratings ahead of unrated listings and title warnings, then compares the percentage versus
  market within each rating. Price-change recency includes both increases and decreases.
* **Click a truck's name** (next to the photo; ★ marks favorites) to open its full details in a pop-up —
  everything from the Vehicle details page, with **★ Favorite** and **🚫 Not interested…** at the top and
  *Quick verify* below. (Streamlit tables can't react to clicks on a picture, so the name is the click target.)
* **✓** (left edge) selects trucks; the sidebar then offers **⚖ Compare** (2–4), **🚫 Hide these** with a reason,
  **↩ Restore** for hidden ones, and **Clear selection**.
* **Edit right in the table** — columns with a ✎ pencil in the header: *Motor*, *Transport*, *Notes* (one notes
  column — put tonneau or anything else you learn there). Saved and kept through every search. Battery, in-service
  date and tonneau are set in the truck's *Quick verify*.
* Columns (kept to what helps compare): ✓ **Photo → Truck → Sold by** stay pinned while you scroll right; then
  *Location · distance*, *Fit*, *Seller listing*, *Deal*, *Price* (your price, with the list price when a discount
  applies), *Est. /mo*, *Transport*, *vs market* (with the market estimate), *Miles*, *Battery · EPA range*,
  *Battery sources*, *Motor*, *Warranty ends* (date · mileage cap), *Warranty left*, *Notes*, then days listed,
  price drops, leverage, generation, color, history flags, Carfax, find seller, status, first seen, VIN. You can
  also drag column headers to rearrange them for the session.
* **Photo size** (S / M / L / XL, top right) sets the thumbnail and row height; the choice is remembered. The table
  grows to show every row, so you only use the page's own scrollbar.
* *Download this view as CSV* exports exactly what you see.

## Checking that links still work

Providers sometimes keep listing a truck after the dealer's page is gone. **🔗 Check listing links** (sidebar,
a minute or two) opens each active listing link once and records the result in the **Link** column (next to
*Seller listing*) and at the top of the truck's details:

* **✓ live** — the page loads and still points at the truck (often "page shows this VIN").
* **✗ dead link** — that address answers *404 Not Found* / *410 Gone*. Often the truck sold, but dealers sometimes
  move a listing to a new address (or a dealer group lists it on a sister store's site). The truck's details then
  offer **Find seller (web search)** and a box to paste the new address; hide it only once you've confirmed it's sold.
* **↪ moved** — the link now redirects to a general inventory page; often sold, but check the dealer's inventory.
* **⚠ sold?** — the page loads but its heading says the vehicle is no longer available.
* **? check** — open it yourself: the site blocks automated checks (Carvana, CarMax and many dealer sites answer
  "Access Denied" / "Just a moment…"), its robots.txt asks tools not to open those pages, or the
  link is a search page or an expiring listing-network click-through (Autolist, Vast) that can't confirm one truck.

It's polite by design: an honest User-Agent, robots.txt respected, requests to one site spaced a few seconds
apart, and a site that blocks the first check is not retried or worked around. Only the result is stored. Sort by
**Link problems first** to review them; once you've confirmed one is sold, hide it (✓ → **🚫 Hide these** →
*Sold / dead link*). Also
available as `python -m rivian_finder.cli check-links`.

CARFAX is always manual-only: the checker skips CARFAX addresses before requesting robots.txt or a page and
stops redirects before following them to CARFAX. History-report links still open directly in a new tab.
If CARFAX shows an access restriction, copy the link into your usual browser with JavaScript and cookies
enabled. If you were using an automated browser, use your normal browser without developer tools attached.
Avoid repeated retries. The app cannot guarantee access or clear CARFAX's restriction; use
[CARFAX support](https://support.carfax.com/contact-us/general/) and include the restriction ID from their page.

## Battery: when sources disagree

The VIN doesn't encode the battery pack, so it always comes from listings — and listings are sometimes wrong (a
Max listed as Standard). When sources disagree the **Battery** cell says **Uncertain** and **Battery sources**
shows who says what, e.g. *"Standard: Auto.dev spec text · Large: Auto.dev trim name"*. Uncertain trucks:

* are **never filtered out** (they pass the battery filter if any claimed pack matches);
* get neutral battery credit in the fit score and aren't used to set market prices;
* show an EPA range spanning every claimed pack.

To settle it: ask the seller for a photo of the truck's *Vehicle* screen or window sticker, or have Rivian confirm by
VIN — then pick the pack in the truck's *Quick verify*. **Get a MarketCheck second opinion** (in the truck's details, 1 call)
adds MarketCheck's decode and, when it reports an EPA range, the only pack with that rating for the year/motor
(e.g. 352 mi on a 2024 Dual = Large). It's another listing-derived opinion, not factory data. Search runs ask for
second opinions automatically for matching trucks with an unknown or disputed battery, once per VIN, while the
MarketCheck budget allows.

## My price adjustments (adjusted price)

**💲 My price adjustments** (Inventory, under Filters) expresses what features are worth *to you*:
**adjusted price = your price (after seller discounts) + optional shipping − feature values.** Fresh workspaces
start with no feature rules and shipping excluded. Add a feature, matching value, and amount. Positive amounts
lower the adjusted price; negative amounts increase it. These values are your preferences, not market estimates.

**Range value** is optional and disabled in fresh workspaces. Choose a preferred range, a dollar penalty per
mile below it, and any extra penalty below your floor. Verified or listed range is used when available;
model-specific Rivian EPA estimates are labeled *est.* and can show a span when wheels are unknown. An estimated
span uses its best case until the configuration is confirmed. This tool is intended for EV comparisons.

**Unconfirmed data never costs a truck money.** A rule never matches an *unsure* or *unknown* value (a front subframe
that could be either way), a disputed battery isn't credited, and an estimated range only counts its best case.
Instead the truck gets a **❓ Confirm frame · battery · wheels** tag (a chip on cards, the end of the *Adjustments*
column in the Table) — confirm those in the truck's **Quick verify** and the full adjustment applies. *Wheels* only
shows when the wheel size would change the range penalty.

**Warranty value** is also disabled in fresh workspaces. If enabled, set your own dollar value per month,
baseline warranty date, and annual mileage. Effective months end at the date or mileage cap, whichever comes
first. Enter the vehicle's actual warranty dates and limits. Rivian-specific estimates are labeled *est.*;
they do not establish another manufacturer's coverage.

Cards show **≈ $57,500 for you** with the breakdown under the price; the Table view has *Adjusted* and *Adjustments*
columns; sort by **Adjusted price ↑** to rank trucks on your terms; Excel has the same columns. The price filter
still uses the real price.

## Front subframe (welded or cast)

Early R1Ts were built with a multi-piece **welded** front subframe that could crack at the welds; Rivian switched to
a single-piece **cast** subframe in early 2023. Rivian hasn't published a VIN cutoff, so the app estimates it from
the VIN: **2022 → welded**, **2024 and later → cast**, and for 2023 by the build serial (the VIN's last six digits):
below 18,000 welded, above 20,500 cast, in between **Unsure** (owner reports put the switch around serial 19,000,
Feb–Mar 2023 builds). Use **Filters → Front subframe** to hide welded (or unsure) trucks; cards show a *Welded front
subframe* chip (or *❓ Confirm frame* when unsure — unsure trucks are never penalized), and the Table view has a
*Front subframe* column.

Rivian replaced many welded subframes with the cast part under warranty, so a "welded" truck may already be fixed —
ask the seller or check the service history, then record it in **Quick verify → Front subframe** (that always wins).

## Warranty & in-service date

* Enter the **in-service date** (Carfax "first sold", or Rivian) in the truck's **Quick verify** — warranty
  remaining appears immediately and survives every refresh.
* Or paste the truck's warranty lines into **Quick verify → Paste warranty info**, e.g.
  *Comprehensive Apr 2028 or 60k mi · Battery pack & drivetrain Apr 2031 or 175k mi*. The truck's own dates beat
  the rules (a month-only date counts from the 1st of that month).
* Rules when only the in-service date is known (Settings → Warranty): comprehensive 4 yr / 50k, but 5 yr / 60k for
  Quad-Motor; battery & drivetrain 8 yr, 175k mi for Quad (or a Max pack), otherwise 150k — that's what Rivian's own
  pages show (a Dual with the Large pack is 150k).

## Make/model searches, EV presets, and towing

Save make/model pairs in **Settings → Collection scope** and select brands in the **Run Search** popup. The
same flow works for cars, SUVs, and trucks supported by the provider. Price, years, mileage, and radius are sent
to the provider where supported. A provider's account restrictions may limit the requested radius or pages.
Each provider's page/call allowance is shared across the selected searches.

Fresh searches do not impose an EV range minimum or exclude base trims or Standard Range batteries. Older EV
truck workspaces retain their saved exclusions and limits until changed. EV range filters remain available;
unknown range is labeled for verification and never presented as meeting a range preference.

Ford Lightning, Chevrolet Silverado EV, and GMC Sierra EV remain convenient EV choices. Optional trim
exclusions hide matching stored listings and skip matching new results without deleting vehicles.

**Inventory → Filters → Brands** shows all trucks when empty, or only the selected brands. **Trims (empty = all)**
lets you choose specific trims from stored inventory, labeled by brand. The same control is available under
**Settings → Vehicle filters** for saved defaults. Collection-scope exclusions still apply to these choices.
Generation, battery, motor, and front-subframe filters use Rivian-specific rules. Other vehicles keep their
listed specifications. EPA range preferences are checked locally after retrieval.

Vehicle details → Overview → **Look up listed specifications (1 API call)** requests MarketCheck specs only for
the truck you choose. It can fill in reported range and any explicit installed towing rating. Missing ratings
remain unknown; this does not spend calls decoding every comparison truck. Verify towing against that truck's
sticker and equipment, or enter a confirmed rating under **Verify equipment**.

**Tow capacity (lb)** appears in Inventory, cards, Compare and Excel with its source and confidence. An unknown
capacity stays unknown. Open the truck's **Verify equipment** tab to enter the capacity confirmed for its actual
battery, configuration and towing package; your verified value wins on future searches. Confirm the rating and
door-placard payload before towing. The app does not treat a model's maximum advertised capacity as VIN-specific.

Rivian warranty and EPA estimates and model-year recall caching apply only to R1T. For another brand, enter the
truck's actual warranty dates and mileage limits and use the NHTSA VIN recall link in its details.

## EPA range

When a listing doesn't state range, the *EPA range* column shows the official fueleconomy.gov rating for the
year + motor + battery (+ wheel size when known, all-terrain tires included). Unknown wheels → a span, e.g.
*307–352 est.* for a 2024 Dual Large. Hover the column header for details; the truck's page shows the basis.

## Vehicle details

* **Overview** — every resolved field with *Source*, *Confidence* and the *Evidence* snippet it came from.
  ⚠️ marks fields where sources disagree; the conflict table shows every claim.
  Confidence: **verified** (you) · **high** (VIN/manufacturer data) · **medium** (structured listing field) ·
  **low** (parsed from listing text).
* **Verify equipment** — record what *you* confirmed (seller call, in-person look, Carfax, Rivian app). Verified
  values override all sources and survive every future scan. Powered tonneau is simply **Yes / No / Unknown**
  (a manual or soft cover counts as No).
  Entering the **in-service date** turns on the warranty-remaining calculation. **Quick verify** (top of the
  page / pop-up) is the fast way: in-service date, battery, motor, tonneau and pasted warranty lines in one form.
* **Price history** — step chart per listing (each source/seller separately) plus the raw observations.
* **Listings & sources** — all URLs for this VIN, each with status, first/last seen, a per-listing
  **transport estimate**, and *Mark sold*.
* **Financing** — every scenario × term × APR.
* **Notes & identity** — notes; add a VIN to a VIN-less vehicle (if another vehicle already has that VIN they
  merge); review possible duplicates.
* **Change log** — every event for this truck.

## Sources page

### Automatic connectors
Enable/disable, run individually, see API calls used this month. *Check 'missing' Auto.dev listings* spends up
to N calls asking Auto.dev whether missing VINs were delisted (they become *removed* if so).

### Saved searches
Starting links for Rivian Pre-Owned, CarMax, Carvana, AutoTrader, AutoTempest, KSL, Facebook, Cars.com,
CarGurus and TrueCar. Links marked *template* are best guesses — open, refine filters on the site, save the
search there (with email alerts on), and paste your own URL back via *Edit*.

### Email alerts
* Gmail: open the alert → ⋮ → **Download message** → drop the `.eml` files here (several at once is fine).
  Outlook: drag the message to a folder (saves `.eml`/`.msg`; use *Save as* → `.eml`) or just paste the body.
* The table shows listing links found for review. Check the selected rows and fix parsed values, then
  *Save selected*. Re-importing the same email updates the existing listings instead of duplicating them.

### Assisted capture
* **Paste**: on the listing page press Ctrl+A, Ctrl+C; paste here with the URL; *Parse*; review; *Save*.
* **Browser extension** (Chrome/Edge/Brave): `chrome://extensions` → Developer mode → *Load unpacked* →
  choose the `extension` folder. On a listing, highlight the details (or Ctrl+A) → click the extension →
  *Send selection*. Captures wait in *Browser extension queue* for review. The app must be open in a browser tab
  for the receiver to be running. If the app isn't running, use *Copy for pasting* instead.
* Facebook is blocked in both paths — use Manual entry.

### Manual entry / CSV / JSON
* Manual form: any subset of fields. A URL is stored as a link only.
* CSV: download the template; columns are listed in `examples/sample_listings.csv`.
  JSON: a list of objects or `{"listings": [...]}` with the same keys (aliases like `mileage`, `link`, `dealer`
  are accepted).

### Review duplicates
Pairs of trucks without a shared VIN that look alike (same year/color, mileage within a few hundred miles,
same seller/city…). *Same truck — merge* combines them keeping every listing and observation;
*Different trucks* dismisses the suggestion permanently.

### Diagnostics
Host OS, database and log locations, source status, and the last 15 runs with per-source notes (provider totals,
pages fetched, why disappearance detection was skipped, etc.).

## Financing

* *Settings → Loan assumptions*: target payment, terms, APRs, payoff, trade-in range, cash offer, tax rate,
  DMV, doc fee, extra cash down, default transport, and two explicit tax switches:
  * *Trading in to the selling dealer reduces the taxable price*.
  * *Selling my current vehicle separately reduces the taxable price*.
  Both switches start off in a fresh workspace. Tax, fees, and trade-in figures start at zero; enter the rules
  and amounts that apply to your transaction before relying on the estimates.
* Payment = P·r / (1 − (1+r)^−n), r = APR/12. *Cash for target* = amount financed − the largest loan your
  target payment supports at that term/APR.
* The **Financing** page has a calculator for any price and a comparison of all matching trucks.

## Settings worth knowing

* **API budget** (top of Collection scope) — locally recorded calls used this month and estimated runs remaining.
* **Collection scope** — make/model pairs and the limits connectors ask providers for. Keep it broader than your filters. Changing it makes
  the next scan skip disappearance detection once (so listings aren't falsely marked missing).
* **MarketCheck radius** — set it within the limit allowed by your provider account.
* **Warranty** — model-specific Rivian assumptions; a vehicle's own verified warranty dates always win.
* **Seller discounts** (Loan assumptions) — add discounts confirmed for your transaction. They affect *Your price*,
  the price filter, and finance scenarios; no discounts are assumed in a fresh workspace.
* **Backup & data** — back up now, restore (current DB is backed up first), full JSON export, purge demo data,
  include/exclude the demo connector.

## Where things live

`data/rivian_finder.db` (database) · `data/backups/` (daily automatic + manual) · `data/exports/` (xlsx) ·
`data/logs/` (rotating log, keys redacted). Set `RIVIAN_FINDER_DATA_DIR` to move all of it (e.g. into OneDrive).
