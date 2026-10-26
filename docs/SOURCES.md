# Sources and collection

Truck Finder can search any make/model supported by the configured inventory provider. Save make/model pairs
under **Settings → Collection scope**. The Run Search picker selects which of those brands to refresh; **Start
search** begins collection. The picker itself makes no inventory requests.

## Collection methods

| Method | What happens | API account needed? |
|---|---|---|
| Auto.dev | Authorized listing searches for the selected make/models, with price, mileage, years, and geographic limits | Your Auto.dev key |
| MarketCheck | Authorized listing searches, subject to the radius and pagination allowed by your plan | Your MarketCheck key |
| Demo | A clearly labeled synthetic Rivian inventory timeline for trying the app | No |
| Email alerts | Import a saved-search email file or paste its contents, then review parsed listings | No |
| Assisted capture | Open a listing yourself, copy/highlight the details, then paste or send the selection for review | No |
| Manual / CSV / JSON | Enter or import the facts and links you have | No |

CarMax, Carvana, AutoTrader, Cars.com, CarGurus, TrueCar, and dealer inventory may appear through a provider;
coverage is not guaranteed. Rivian Pre-Owned pages can be pasted for review. KSL and other private-party
sources depend on the information you import. Facebook Marketplace is manual-only; the capture extension
refuses to run there.

The app does not automate sign-in, solve challenges, or navigate classified sites to collect inventory.
Email formats vary, and all parsed values should be reviewed before saving.

## Private-party and enthusiast sources

These sites forbid automated collection in their terms, so the app never visits them. Each has a path you
start yourself:

| Site | How listings get in | What the app reads |
|---|---|---|
| **KSL Cars** | Saved-search alert emails, or paste/capture a listing page | Price, miles, location, VIN. "For Sale By Owner" / "Seller Type" sets the seller type; "Title Type: Rebuilt/Reconstructed" or "Salvage" records a branded title. |
| **RivianForums** ("Rivians / Vehicles For Sale") | Watch the forum with email notifications and import those emails, or paste/capture a thread | The thread title ("Texas - For Sale: 2022 R1T …, 26k miles; $56k, PENDING") and the **first post only**. The title's price wins over an MSRP in the post. Seller type is private. SOLD threads save as sold; wanted-to-buy (WTB) posts are flagged. |
| **Rivian Roamer** | Browse only | Nothing. Roamer's terms forbid feeding its data into other apps, so paste and the extension refuse its pages. Open the truck's rivian.com listing from Roamer and paste Rivian's page instead. It has the VIN and build details that Roamer's cards don't. Roamer's Atom feed ("Copy Atom Feed" on its inventory page) works in your own feed reader for alerts. |

Saved links for RivianForums and Rivian Roamer appear under **Sources → Saved searches**, including in existing
workspaces. Delete one and it stays deleted.

## Search scope and request limits

Collection settings control what is sent to the provider. Inventory display filters operate locally and do
not trigger more calls. Use a collection scope broad enough to catch relevant price changes, and use display
filters to narrow your current view.

Only selected brands are refreshed. Other brands' saved listings, photos, and VIN evidence are left alone.
Providers may require separate requests for different make/model pairs. Selecting more models can therefore
cost more calls, even when they share a brand.

`max_pages_per_run` limits HTTP attempts per provider, including retries. Local request accounting also stops
at the app's monthly cap. These counters do not include calls made from other apps or the provider's dashboard.
Provider plan restrictions can limit radius, pages, fields, or coverage before the app's own cap is reached.
Check [Auto.dev plans](https://auto.dev/pricing) and
[MarketCheck plans](https://www.marketcheck.com/apis/pricing) against your account.

Existing electric-truck workspaces retain their earlier Rivian/competitor collection limits until customized
searches are explicitly saved. Optional MarketCheck second opinions are Rivian battery checks, use additional
calls, and run only when Rivian and the MarketCheck connector are selected.

An incomplete or failed scan leaves unseen listings unchanged. Unselected makes/models and vehicles outside
the scanned geographic scope also retain their status. A changed collection scope skips disappearance
detection on the first complete scan. Missing does not mean confirmed sold.

References: [Auto.dev listing filters](https://docs.auto.dev/v2/reference/searchVehicleListings),
[Auto.dev pagination](https://docs.auto.dev/v2/products/vehicle-listings),
[MarketCheck inventory search](https://docs.marketcheck.com/docs/api/cars/inventory/inventory-search).

## Extra information

| Information | Source and limits |
|---|---|
| VIN evidence | Optional NHTSA vPIC decode, cached per vehicle; it does not establish every option or battery configuration |
| Range / towing | Provider fields, imported text, or your verification; missing values stay unknown |
| Carfax link | Dealer-supplied report link when provided in listing data |
| Clean-title / one-owner flags | MarketCheck fields; false is treated as unconfirmed, rather than evidence of damage or multiple owners |
| Days listed / seller phone | Provider fields when available |
| Rivian recalls | NHTSA model-year recalls, cached weekly; VIN-specific repair completion requires a separate check |
| Photos | A listing's supplied image URL, your pasted image URL, or an upload; no dealer image gallery scraping |

Model-specific EPA, battery, and warranty helpers currently focus on Rivian R1T. Do not interpret that evidence
as a rating or warranty for a different vehicle.

## Optional link checks

**Check listing links** checks existing URLs with robots.txt handling, pacing, and no challenge bypass. It
stores HTTP status and a short result, and stops when a site blocks automated checks. A dead link is not proof
of sale: dealers may replace pages or change URLs. Review the seller's current listing before contacting them.
