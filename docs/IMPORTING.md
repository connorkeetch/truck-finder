# Importing listings

You don't need an API account to use MotorSift. You can bring listings in from a spreadsheet, a JSON file,
alert emails, or text copied from a listing page.

Every import follows the same rules:

- **You review before saving.** Parsed values are shown first, and nothing is stored until you confirm.
- **Duplicates merge.** A listing with the same VIN or the same link updates the existing vehicle instead of
  adding a second copy.
- **Imports never mark vehicles missing.** Only a complete automatic scan can do that.
- **Imported equipment is a claim, not a fact.** It's stored with its source and confidence. To mark something
  as checked, use **Verify equipment** on the vehicle's details.
- **Links are stored, never fetched.** MotorSift doesn't visit the URLs you import.

## CSV

**Sources → CSV / JSON import**. Download the template there, or start from
[`examples/sample_listings.csv`](../examples/sample_listings.csv).

```csv
url,year,make,model,trim,price,miles,seller_name,seller_type,city,state,zip,tow_capacity_lbs,epa_range,title_status,description
https://example.com/lightning-1,2023,Ford,F-150 Lightning,Lariat,48500,21000,Example Ford,dealer,Boise,ID,83702,7700,320,clean,Extended range battery. Max Trailer Tow package.
https://example.com/tacoma-7,2021,Toyota,Tacoma,TRD Off-Road,33900,52000,Pat (private seller),private,"Reno, NV 89501",,,,,unknown,One owner. New tires.
```

Things to know:

- Only include the columns you have. Blank cells are fine.
- `price` and `miles` accept `$48,500` or `21,000 mi`.
- If `state` is blank, `city` can hold the whole location: `"Reno, NV 89501"`.
- No `vin` column? A VIN anywhere in `description` is picked up.
- `description` is scanned for equipment such as battery, motor, wheels and tonneau. A column you fill in wins
  over what's found in the text.

### Columns

| Column | Example | Notes |
|---|---|---|
| `url` | `https://example.com/listing/123` | The listing page. Used to recognize the site (Carvana, KSL…). |
| `vin` | `1FTVW1EL5PWG12345` | Strongly recommended: VINs are how duplicates merge. |
| `year`, `make`, `model`, `trim` | `2023`, `Ford`, `F-150 Lightning`, `Lariat` | |
| `price`, `miles` | `48500`, `21000` | |
| `seller_name` | `Example Ford` | |
| `seller_type` | `dealer` | `dealer`, `private`, `manufacturer`, `retailer`, or `unknown` |
| `city`, `state`, `zip` | `Boise`, `ID`, `83702` | Used for distance and transport estimates |
| `exterior_color`, `interior_color` | `Antimatter Blue` | |
| `epa_range` | `320` | Miles. Mainly for EVs. |
| `tow_capacity_lbs` | `7700` | This vehicle's own rating, if you know it |
| `wheels` | `20" All-Terrain` | |
| `battery`, `motor` | `Large`, `Dual` | Rivian-style values. Other makes can leave these blank. |
| `tonneau` | `yes` | Powered tonneau cover: `yes`, `no`, or `unknown` |
| `in_service_date` | `2024-03-15` | First-sold date. Starts warranty calculations. |
| `warranty_expiration` | `2028-03-15` | |
| `title_status` | `clean` | `clean`, `branded`, or `unknown` |
| `accident_history` | `none_reported` | `none_reported`, `reported`, or `unknown` |
| `transport_cost` | `650` | Your known delivery or pickup cost, in dollars |
| `description` | free text | Listing text. Scanned for equipment and a VIN. |
| `source` | `ksl` | Site name to use when there's no `url` |

Common alternative names work too: `link` or `listing_url` → `url`, `mileage` or `odometer` → `miles`,
`dealer` or `seller` → `seller_name`, `color` → `exterior_color`, `notes` → `description`,
`location` → `city`, `asking price` → `price`.

## JSON

Use the same keys as the CSV columns, as a list or wrapped in `{"listings": [...]}`:

```json
{
  "listings": [
    {
      "link": "https://example.com/silverado-42",
      "year": 2022,
      "make": "Chevrolet",
      "model": "Silverado 1500",
      "asking price": "$41,250",
      "odometer": "38,100 mi",
      "dealer": "Example Chevy",
      "location": "Mesa, AZ 85201"
    }
  ]
}
```

See also [`examples/sample_listings.json`](../examples/sample_listings.json).

## Email alerts

Most listing sites (AutoTrader, Cars.com, KSL, CarGurus…) can email you when a saved search finds something.
MotorSift reads those emails. To have it read them from your mailbox automatically, see
[Import alert emails automatically](AUTOMATION.md#import-alert-emails-automatically). To import by hand:

1. Save the email as a file:
   - **Gmail**: open the email → **⋮** → **Download message** (saves an `.eml`).
   - **Outlook**: drag the message into a folder, or **File → Save as** `.eml`.
2. **Inventory → Add vehicle → Alert email** (or **Sources → Email alerts**) and drop the files in.
   Several at once is fine. You can also paste the email body instead.
3. Check the rows, fix anything parsed wrong, then **Save selected**.

To try it, use the synthetic emails in [`examples/emails/`](../examples/emails/).

If an email gives you zero listings, it probably only has tracking links or images. Open the listing from the
email and use [Paste a listing](#paste-a-listing) instead.

**RivianForums**: sign in, open **Rivians / Vehicles For Sale**, choose **Watch** and turn on email
notifications. Each new thread then arrives as an email you can import here. Wanted-to-buy posts and SOLD threads
start unticked.

## Paste a listing

For a single listing you're looking at in your browser:

1. On the listing page, press **Ctrl+A** then **Ctrl+C** (or highlight just the details).
2. **Inventory → Add vehicle → Paste listing**. Paste the text and the page's URL.
3. Check what was found, then save.

Try it with [`examples/sample_capture.txt`](../examples/sample_capture.txt). From this text:

```text
2024 Rivian R1T Adventure
$61,250
Mileage: 12,980
Performance Dual-Motor AWD · Large Pack · 21" Road wheels
Sold by: Sample Motors · St George, UT 84770
```

the parser fills in year, make, model, trim, price, miles, seller, city/state/ZIP, battery, motor and wheels.
Values parsed from free text are marked **low** confidence until you verify them.

**Rivian Pre-Owned pages** are recognized automatically. You can paste several at once, and they save battery,
motor, tonneau and warranty dates as verified values.

**KSL ads**: "For Sale By Owner" or "Seller Type: Dealer" sets the seller type, and a "Title Type" of
Rebuilt/Reconstructed or Salvage is recorded as a branded title. Check the title before you get attached to a
cheap vehicle.

**RivianForums threads**: paste the thread's URL and the whole page. Only the title and the first post are read,
because replies often quote other vehicles' prices. For example, from:

```text
Utah - For Sale: 2022 R1T Launch Green, Quad, 31k miles; $54,500
Thread starter trailrunner42 Start date Oct 20, 2026
…
#1
Selling my 2022 R1T Adventure … Original MSRP was $89,000.
…
#2
Nice truck! Mine was $49,900 with 40k miles …
```

you get $54,500 (from the title, not the MSRP), 31,000 miles, Utah, a private seller named
"trailrunner42 (RivianForums)", and nothing from reply #2. A thread marked SOLD is saved as sold, which still
helps price comparisons. A wanted-to-buy (WTB) post shows a warning.

**Rivian Roamer pages can't be pasted.** Roamer's terms forbid feeding its data into other apps. Open the vehicle's
rivian.com listing from Roamer and paste that page instead.

## Browser extension (optional)

The extension does the same thing as pasting, with one click. It runs only when you click it, and it only reads
the text you've highlighted, the page title and the URL.

1. Open `chrome://extensions` (Chrome, Edge or Brave) and turn on **Developer mode**.
2. **Load unpacked** → choose the `extension/` folder.
3. On a listing, highlight the details, click the extension → **Send selection**.
4. Review it in **Sources → Assisted capture → Browser extension queue**.

The app must be open in a browser tab for the extension to reach it. Facebook Marketplace and Rivian Roamer are
blocked on purpose. Use manual entry for Facebook, and the rivian.com listing for Roamer vehicles. After updating
the extension folder, press **Reload** on `chrome://extensions`.

## From a script

The importers are plain Python, so you can feed in a file from your own tooling. Back up your database first
(**Settings → Backup & data → Back up now**).

```python
# import_csv.py: save in the project folder and run it with .venv's Python
import sys
from pathlib import Path

from rivian_finder import db, pipeline
from rivian_finder.importers import manual

conn = db.connect()  # opens data/rivian_finder.db (or RIVIAN_FINDER_DATA_DIR)
listings = manual.parse_csv(Path(sys.argv[1]).read_bytes())
summary = pipeline.import_listings(conn, listings, "csv_import")
print(f"{len(summary['vehicle_ids'])} listings, {summary['counts']['new_listing']} new vehicles")
```

```bash
.venv/bin/python import_csv.py my_listings.csv
```

On Windows, use `.venv\Scripts\python import_csv.py my_listings.csv`.
