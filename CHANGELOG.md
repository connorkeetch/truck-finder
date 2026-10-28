# Changelog

## [0.2.0 beta 1](https://github.com/connorkeetch/truck-finder/releases/tag/v0.2.0b1) — October 28, 2026

- Rename the public app and capture extension to **MotorSift**, a vehicle-shopping workspace for supported makes and models.
- Reorganize Inventory around browsing: top navigation, sidebar filters, visible filter summaries, and **Refresh listings** / **Add vehicle** actions.
- Move listing-link checks and Excel export to **Sources → Tools**, and price adjustments to Settings.
- Add first-run paths for an offline synthetic-data import, search setup, and importing listings.
- Simplify browsing cards and the details header; keep full evidence and calculations in details tabs, with notes, seller contacts, and inspection tasks under **Notes & checklist**.
- Make JSON export/import retain checklist and seller-contact history alongside the other database tables.
- Add provider-specific API-key instructions, official account links, and local/Railway setup guidance; distinguish app request budgets from provider subscriptions.
- Cover simultaneous car/SUV searches across multiple brands with automated tests, include the next model year for new workspaces, and add mixed-vehicle demo examples.
- Make Dashboard summaries and cards suitable for general vehicles, clarify comparison/finance assumptions, and handle matching listings without prices.
- Keep source equipment claims unverified when Quick verify saves an unrelated field; tonneau verification now requires an explicit choice.
- Stage database restores before replacement, preserve the selected oldest backup and pre-restore safety copy, and use exclusive unique backup filenames to avoid timestamp collisions.
- Purge demo vehicles together with dependent checklist, contact, and other shopping records while preserving real inventory.
- Require Python 3.12 or newer in both the launcher and an existing virtual environment; Python 3.12 is the tested version.
- Interpret negated powered-tonneau descriptions and manual/soft covers correctly while retaining legacy import values.

The Python package, environment variables, database/configuration paths, scheduled-task names, and GitHub repository URL keep their existing names for compatibility. Existing workspaces retain their saved data and preferences.

October 28 validation passed the Windows shopping flow from a clean source folder and new Python 3.12.10 environment, plus 967 tests with no skips, including 13 deployment tests (10 exercised Caddy 2.11.7 authentication). A bounded live smoke returned HTTP 200 from each provider for Toyota Camry listings. See [Release checks](docs/PUBLIC_RELEASE.md) for the exact scope, CI publication gate, and remaining platform limits.
