# Configuration

Most settings live in the app under **More → Settings**. Settings are saved in your local database. A few
startup options are environment variables.

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `AUTODEV_API_KEY` | none | Auto.dev Listings API key |
| `MARKETCHECK_API_KEY` | none | MarketCheck inventory API key |
| `MARKETCHECK_BASE_URL` | `https://api.marketcheck.com` | Point MarketCheck at a different host |
| `RIVIAN_FINDER_DATA_DIR` | `./data` | Folder for the database, backups, exports, logs and photos |
| `RIVIAN_FINDER_DB` | `<data dir>/rivian_finder.db` | Database file, if you want it somewhere else |
| `RIVIAN_FINDER_PORT` | `8501` | Web UI port |
| `RIVIAN_FINDER_CAPTURE_PORT` | `8765` | Port the browser extension sends to |
| `RIVIAN_FINDER_NO_BROWSER` | unset | Set to `1` so the launcher doesn't open a browser tab |

The names start with `RIVIAN_FINDER_` for historical reasons. They apply to every make and model.

The hosted version uses a few more variables (`RIVIAN_FINDER_CLOUD`, `TZ`, `TRUCK_FINDER_USER`,
`TRUCK_FINDER_PASSWORD_HASH`, `TRUCK_FINDER_PROXY_SECRET`). See
[Private Railway deployment](CLOUD_DEPLOYMENT.md).

### Using a `.env` file

Copy `.env.example` to `.env` in the project folder and fill in what you need:

```ini
AUTODEV_API_KEY=your-key-here
RIVIAN_FINDER_DATA_DIR=D:\OneDrive\TruckFinder
```

`.env` is ignored by Git. Never commit it.

> **Known limitation:** the launcher reads only `RIVIAN_FINDER_DATA_DIR` from `.env`. Set `RIVIAN_FINDER_PORT`
> and `RIVIAN_FINDER_NO_BROWSER` in your shell instead (see below). This is tracked in
> [Improvements](IMPROVEMENTS.md).

### Setting a variable for one launch

```powershell
# Windows PowerShell
$env:RIVIAN_FINDER_PORT = "8502"; .\run.bat
```

```bash
# macOS / Linux
RIVIAN_FINDER_PORT=8502 ./run.sh
```

## API keys

You can save keys in either place:

1. **Settings → API credentials** stores them in your OS credential store (Windows Credential Manager, macOS
   Keychain, or the Linux Secret Service) under the service name `rivian-finder`.
2. **Environment / `.env`**: `AUTODEV_API_KEY`, `MARKETCHECK_API_KEY`.

If both are set, the environment wins, and the Settings page tells you which one is in use. Keys are never
stored in the database and are removed from log files.

## Where your data lives

```text
data/                       ← RIVIAN_FINDER_DATA_DIR
├── rivian_finder.db        your inventory, history, notes and settings
├── backups/                daily automatic + manual backups (the newest 30 are kept)
├── exports/                Excel exports
├── logs/
│   ├── rivian_finder.log   app log (keys redacted)
│   └── scheduled.log       scheduled-search log
├── photos/                 one cached thumbnail per vehicle
└── app_access.json         phone-access switch and hashed PIN
static/photos/              copies of thumbnails served to your browser (always in the project folder)
```

### Example: keep your data in a synced folder

```ini
# .env
RIVIAN_FINDER_DATA_DIR=C:\Users\you\OneDrive\TruckFinder
```

Only run the app on one computer at a time when the database lives in a synced folder.

### Example: two separate searches

Each data folder is its own workspace with its own vehicles and settings. Give each one its own port:

```bash
RIVIAN_FINDER_DATA_DIR=~/truck-finder/trucks RIVIAN_FINDER_PORT=8501 ./run.sh
RIVIAN_FINDER_DATA_DIR=~/truck-finder/suvs   RIVIAN_FINDER_PORT=8502 ./run.sh
```

## Settings in the app

| Settings tab | What's there |
|---|---|
| **Vehicle filters** | Your default Inventory view: price, miles, years, distance, brands, trims |
| **Collection scope** | Make/model pairs and limits sent to providers, pages per run, API budget |
| **Location** | Home ZIP and priority states |
| **API credentials** | Save or remove provider keys, and see which key is in use |
| **Loan assumptions** | Terms, APRs, tax rate, fees, trade-in, payoff, seller discounts |
| **Warranty** | Rivian R1T warranty rules (a truck's own dates always win) |
| **Export** | Excel export options |
| **Backup & data** | Back up, restore, JSON export/import, demo data |
| **Shipping** | Local pickup radius, delivery fees, per-mile rates |
| **Alerts** | Scheduled searches and desktop notifications ([Automation](AUTOMATION.md)) |
| **Phone access** | PIN-protected access from your phone on home Wi-Fi |

**Collection scope vs. Vehicle filters.** Collection scope decides what's *fetched*, and each fetch costs API
calls. Vehicle filters decide what's *shown*, for free. Keep the collection scope a bit wider than your filters.
Then tightening a filter never makes trucks look like they disappeared, and you still catch price drops on
trucks just outside your range.

Example: you want trucks under $50,000. Collect up to $55,000 and filter at $50,000. A $52,000 truck that drops
to $49,500 then shows up as a price drop instead of looking brand new.

## Phone access

**Settings → Phone access**: set a 4–12 digit PIN, turn it on, and restart the app. The app then listens on
your local network, and other devices must enter the PIN. Use it only on a home network you trust. Traffic is
plain HTTP. See [SECURITY.md](../SECURITY.md).

## Theme

The charcoal theme is set in `.streamlit/config.toml`. Leave `enableStaticServing = true` there, because
thumbnails depend on it.
