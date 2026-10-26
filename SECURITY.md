# Security

## Reporting a problem

Please don't open a public issue for a security problem. Use GitHub's private reporting instead: go to the
repository's **Security** tab and choose **Report a vulnerability**. Include steps to reproduce and what an
attacker could do.

Only the latest code on `main` is supported. Fixes are not backported.

## How Truck Finder is meant to be run

Truck Finder is a single-user app. Each install is one person's shopping workspace. There are two supported
ways to run it, and they're protected differently.

### On your computer (the default)

**Listens on localhost only.** The web UI binds to `127.0.0.1:8501`, and the browser-extension receiver binds
to `127.0.0.1:8765`. Other devices can't reach either one.

**Phone access is opt-in.** When you turn it on, the app listens on your local network, and other devices must
enter a PIN. The PIN is stored as a salted PBKDF2 hash in `data/app_access.json`. Keep in mind:

- Traffic is plain HTTP. Use phone access only on a home network you trust, never on public Wi-Fi.
- Requests that appear to come from this computer skip the PIN. **Don't put the desktop app behind your own
  reverse proxy, tunnel or port forward** (for example ngrok or Cloudflare Tunnel). Those make remote visitors
  look local. To reach the app from anywhere, use the private cloud deployment below instead.
- Use a 6+ digit PIN. Wrong guesses are slowed down per browser session, but there's no global lockout yet.
- Thumbnails under `/app/static/photos/` are served without the PIN.

### Private cloud deployment (Railway)

[docs/CLOUD_DEPLOYMENT.md](docs/CLOUD_DEPLOYMENT.md) runs the included Docker image. In that setup:

- Railway provides HTTPS.
- Caddy asks for your username and password before every page, photo, media file and WebSocket. Only
  `GET`/`HEAD /_stcore/health` is public.
- The password is stored only as a bcrypt hash (`TRUCK_FINDER_PASSWORD_HASH`). Use a long random password from
  a password manager, because the login prompt doesn't lock out repeated guesses.
- Streamlit listens on loopback only and rejects any request without the private proxy token
  (`TRUCK_FINDER_PROXY_SECRET`). The container won't start if either secret is missing.
- API keys and login secrets live in Railway's service variables, not in the repository or the image.
- Your database lives on the service's persistent volume. Anyone with access to your Railway project can read
  it, so protect that account with two-factor authentication.

### Both ways

**API keys stay out of the database.** Keys come from environment variables / `.env`, or from your OS credential
store (service name `rivian-finder`). They're removed from log files and error messages.

**The extension receiver rejects websites.** It accepts captures only from browser extensions or local tools
with no `Origin` header. Captures go to a review queue and are never saved automatically.

**Your data isn't encrypted by the app.** Your inventory, notes, contact log and settings are in a plain SQLite
file: in `data/` on your computer, or on the `/data` volume in the cloud. Backups, Excel exports and JSON
exports contain the same information. Treat them as private, and don't attach them to issues.

## Outbound connections

The app only contacts:

- the listing APIs you configured (Auto.dev, MarketCheck);
- NHTSA (vPIC VIN decoding, recalls), which is free and needs no key;
- image URLs supplied by listings, to cache one thumbnail per vehicle;
- listing pages, only when you press **Check listing links**. That's one request per link, it respects
  `robots.txt`, and it stops at bot challenges.

Maintainers can also regenerate the bundled EPA data from fueleconomy.gov with `epa.refresh()`. The app never
calls it on its own.

It doesn't send analytics. Streamlit usage stats are turned off in `.streamlit/config.toml`.
