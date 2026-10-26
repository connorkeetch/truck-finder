# Contributing

Thanks for helping. Bug reports, docs fixes, new import formats and model-specific knowledge are all welcome.

## Set up

You need Python 3.12.

```bash
git clone https://github.com/connorkeetch/truck-finder.git
cd truck-finder
python -m venv .venv
```

```bash
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
```

```powershell
# Windows
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest
```

Start the app with `run.bat` / `./run.sh`, or directly:

```bash
.venv/bin/python -m streamlit run app.py
```

You don't need API keys. Tests use stubbed providers, and the app has a synthetic demo connector
(see [Quickstart](docs/QUICKSTART.md)).

**Use a throwaway data folder while developing** so you never change your real shopping data:

```bash
RIVIAN_FINDER_DATA_DIR=/tmp/tf-dev RIVIAN_FINDER_PORT=8601 ./run.sh
```

Streamlit doesn't reload changes to the `rivian_finder` package on its own. Restart the app after editing it.

## Find your way around

[How Truck Finder works](docs/ARCHITECTURE.md) explains the data flow, the core ideas (vehicles vs. listings,
claims and confidence, complete scans), and how to add a source or migration.
[Improvements](docs/IMPROVEMENTS.md) lists known issues and good first tasks.

## Ground rules

These protect users' API budgets, their data, and the sites listings come from.

- **API calls are bounded and user-initiated.** Nothing calls a provider unless the user pressed a button or
  turned on scheduling. Respect the page caps and monthly budgets in `sources/base.py`.
- **A partial scan changes nothing it didn't see.** Only `FetchResult(complete=True)` with an unchanged scope
  can mark listings missing.
- **Unknown stays unknown.** Don't fill a gap with a typical value. Record what a source claimed, with its
  confidence and evidence.
- **Keep model-specific rules scoped.** Rivian R1T logic must not apply to other vehicles.
- **Preserve users' saved settings.** Add new settings to `config.DEFAULT_SETTINGS`. Never rename or reset
  existing keys without migrating them.
- **No scraping, no evasion.** Use authorized APIs, user-supplied imports, or user-initiated capture. Don't
  spoof browser identities or work around bot checks, `robots.txt`, or sign-in walls.
- **Synthetic data only.** Tests, examples, screenshots and bug reports use fake listings (`example.com` URLs,
  `vin()` from `tests/conftest.py`). Never submit API keys, real databases, contact notes, exports, or
  downloaded dealer photos.

## Making a change

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep pull requests focused: one fix or feature each.
3. Add or update tests. Bug fixes should include a test that fails without the fix.
4. Run `python -m pytest` and make sure everything passes.
5. If you changed what users see or do, update the matching doc in `docs/`.
6. Describe what changed and how you checked it in the pull request.

### Style

- Match the surrounding code: type hints, short docstrings that say *why*, `from __future__ import annotations`.
- User-facing text is plain and specific. Say what happened and what to do next.
- In Streamlit text, escape `$` amounts with `ui.common.md()`. Otherwise Streamlit renders them as math.
- Never call `st.toast` or draw widgets inside a widget callback in a dialog. It crashes the page.

## Reporting a bug

Use the bug report template. Include your OS, Python version, what you did, what you expected, and the
relevant lines from `data/logs/rivian_finder.log` (keys are removed automatically, but check for anything
personal before posting).

Security issues: please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
