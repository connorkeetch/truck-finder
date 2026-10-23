# Troubleshooting

| Symptom | Fix |
|---|---|
| `run.bat` closes immediately / "Python was not found" | Install Python 3.10+ from python.org with *Add python.exe to PATH*. The Microsoft Store stub `python.exe` doesn't count; `py -3 --version` should work. |
| "Port 8501 is used by another program" | Another app (or another Streamlit) uses it. Set `RIVIAN_FINDER_PORT=8502` in `.env` or the environment and relaunch. If it's an old Truck Finder window, close it. |
| Browser didn't open | Go to `http://127.0.0.1:8501` yourself. |
| Dependency install fails behind a proxy | Set `HTTPS_PROXY` for pip, or run `.venv\Scripts\python -m pip install -r requirements.txt` manually to see the error. Delete `.venv` to start fresh. |
| **Auto.dev: "rejected the API key (HTTP 401)"** | Key mistyped/revoked. Re-save it in *Settings → API credentials*. Check whether a stale `AUTODEV_API_KEY` in `.env` overrides the keychain (env wins; the Settings page says which is in use). |
| Auto.dev: "Rate limited" | Free plan allows 5 req/s and 1,000 calls/month. The app paces requests and retries with backoff; if the monthly cap is hit, wait for the reset or lower *Max pages per connector per run*. Nothing is marked missing on a failed run. |
| Auto.dev: `INVALID_PARAMETER` | The provider changed a filter name. Note the parameter in the error, and edit `build_params` in `rivian_finder/sources/autodev.py`. |
| Run says "Incomplete scan" | The page cap (*Settings → Collection scope*) was reached or the provider stopped early. Raise the cap if you have calls to spare. Incomplete scans never mark listings missing. |
| "Collection scope changed … disappearance detection was skipped" | Expected once after you change collection scope; the next run compares like with like. |
| MarketCheck finds only Utah trucks | Free plan is limited to a 100-mile radius around the search ZIP. That's by design; set radius to 0 only on a paid plan. |
| Everything says DEMO | No API key yet, so Run Search uses the demo connector. Add a key, then *Settings → Backup & data → Purge all demo data* and toggle off *Include demo connector*. |
| Email import finds 0 listings | The email may only contain tracking links whose destination isn't embedded, or images only. Open the listing from the email in your browser and use *Assisted capture → Paste* instead. |
| Extension says "Truck Finder isn't running" | The receiver starts when the app is open in a browser tab. Open the app, then retry. If you changed `RIVIAN_FINDER_CAPTURE_PORT`, also change the port in `extension/manifest.json` and `extension/popup.js`, then reload the extension. |
| *Diagnostics* says the capture receiver couldn't start | Port 8765 is taken. Set `RIVIAN_FINDER_CAPTURE_PORT` (and update the extension as above), or use paste capture. |
| A truck shows twice | One listing lacks a VIN. Open it → *Notes & identity* → add the VIN (they merge), or approve the suggestion in *Sources → Review duplicates*. |
| Wrong battery/motor/tonneau | Click the truck's name → *Quick verify* and pick the right value (motor can also be changed in the row); it overrides every source permanently. The *Battery sources* column and *Overview → Evidence* show who said what. |
| Battery says "Uncertain" | Sources disagree — the truck is still shown. Ask the seller for the Vehicle screen / window sticker or have Rivian confirm by VIN, then pick the pack in the truck's *Quick verify*. *Get a MarketCheck second opinion* (truck details) adds another, listing-derived, opinion. |
| A truck I know about isn't listed | Paste its VIN or listing link into the Inventory search: it's found whatever your filters say, with the exact reason it's hidden. Not in your data? **➕ Add a truck → By VIN**. |
| Seller's page is gone but the truck still shows | Providers can lag. Press **🔗 Check listing links** to find dead pages in bulk, then hide them (✓ → 🚫 Hide these → *Sold / dead link*, or the truck's details). That stays removed even if the provider keeps returning it. |
| Link column says "? check" | The site blocks automated checks (Carvana, CarMax, many dealer sites), its robots.txt disallows them (Carfax), or the link is a search page (Autolist). Open it yourself — the app deliberately doesn't work around those. |
| Distances of ~7,356 mi | Fixed: some providers send 0,0 coordinates; those are now ignored and the listing ZIP is used (a one-time repair cleaned stored ones). |
| Warranty columns are blank | Enter the in-service date, or paste the truck's warranty lines, in the truck's *Quick verify*. |
| The app feels slow | It should redraw in well under a second. Photos are served from `static/photos` so the browser caches them — make sure `.streamlit/config.toml` still has `enableStaticServing = true`. Photo size **S** or **M** makes the table lighter. |
| Excel says the file is locked | Close the workbook in Excel before re-exporting; each export uses a new timestamped filename anyway. |
| No desktop notification | Use *Settings → Alerts → Send a test notification*. If nothing appears, check Windows Focus Assist / Do Not Disturb and *Settings → System → Notifications* (allow Windows PowerShell). |
| Scheduled search never runs | Task Scheduler → Task Scheduler Library → RivianFinder: check *Last Run Result*. Tasks run only while you're logged in. See `data/logs/scheduled.log`; a run is skipped when the month's API calls are low. |
| Phone can't open the app | Phone access must be on *and* the app restarted. Use the address from *Settings → Phone access* on the same Wi-Fi. Allow Python through Windows Firewall on private networks. Guest Wi-Fi networks often block device-to-device traffic. |
| Transport looks wrong | Carvana and CarMax show their exact delivery fee on the listing — type it in the truck's *Transport* (Table view or *Listings & sources*). Otherwise adjust *Settings → Shipping* (their nearby/far fees, local radius, per-mile rates). |
| Database problems after a crash | *Settings → Backup & data → Restore* a backup from `data/backups/` (a safety backup of the current DB is made first). |
| Start completely fresh | Close the app, move/rename the `data` folder, relaunch. |

Logs: `data/logs/rivian_finder.log` (API keys and tokens are redacted). Source errors are also shown on the
Dashboard and in *Sources → Diagnostics*.
