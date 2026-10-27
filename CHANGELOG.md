# Changelog

## 0.2.0 beta 1 — unreleased

- Rename the public app and capture extension to **MotorSift**, a vehicle-shopping workspace for supported makes and models.
- Reorganize Inventory around browsing: top navigation, sidebar filters, visible filter summaries, and **Refresh listings** / **Add vehicle** actions.
- Move listing-link checks and Excel export to **Sources → Tools**, and price adjustments to Settings.
- Add first-run paths for an offline synthetic-data import, search setup, and importing listings.
- Simplify browsing cards and the details header; keep full evidence and calculations in details tabs, with notes, seller contacts, and inspection tasks under **Notes & checklist**.
- Make JSON export/import retain checklist and seller-contact history alongside the other database tables.
- Add provider-specific API-key instructions, official account links, and local/Railway setup guidance; distinguish app request budgets from provider subscriptions.
- Verify simultaneous car/SUV searches across multiple brands, include the next model year for new workspaces, and add mixed-vehicle demo examples.
- Make Dashboard summaries and cards suitable for general vehicles, clarify comparison/finance assumptions, and handle matching listings without prices.
- Keep source equipment claims unverified when Quick verify saves an unrelated field; tonneau verification now requires an explicit choice.

The Python package, environment variables, database/configuration paths, scheduled-task names, and GitHub repository URL keep their existing names for compatibility. Existing workspaces retain their saved data and preferences.

This is a beta preparation entry. Fresh-install and cross-platform release checks remain before publishing a release.
