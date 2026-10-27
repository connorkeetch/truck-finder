# MotorSift beta usability plan

The next release should make the existing vehicle-shopping workflow easy to discover and scan.

## Implementation order

1. **Inventory and navigation:** top navigation, a dedicated filter sidebar/mobile drawer, a compact results header, one Refresh listings action, and Add vehicle in a dialog. Move export and link maintenance to Sources → Tools. Move feature-value configuration to Settings.
2. **Visible filter state:** put make/model, budget, mileage, years, and distance first; group specialist options. Show removable active-filter summaries, a clear reset, and preserve view state through detail and comparison actions.
3. **Cards:** emphasize vehicle, price, mileage, location, configuration, changes, and critical warnings. Keep calculations and evidence in Details. Preserve accessible controls, keyboard focus, and phone layouts.
4. **First run:** offer Try demo, Set up my search, and Import listings without requiring provider credentials. Browsing and changing filters must never start provider calls.
5. **Release confidence:** fix complete JSON export, apply MotorSift branding to public text, add a beta version/changelog, and update the guides. Verify isolated regressions and browser layouts before promotion.

## Compatibility and scope

- Keep the existing `rivian_finder` package, environment variables, database/configuration paths, and GitHub repository URL. Existing workspaces must open without migration or reset.
- Preserve source confidence, verified overrides, title/accident warnings, and unknown equipment values.
- Do not change provider integrations, scoring, financial calculations, or collected inventory as part of the layout work.
- No framework rewrite or new runtime dependency is needed.

## Acceptance checks

- A new user can try demo data, find a vehicle, filter results, favorite candidates, compare them, and open Details.
- Inventory results begin below a compact search/toolbar area; expanding filters does not push results down.
- Active filters explain exclusions and can be removed individually or reset without changing saved defaults.
- Filter/sort/view selections survive card and dialog interactions. Exact VIN/link lookup still finds vehicles outside display filters.
- Desktop and narrow phone layouts have no clipped controls or horizontal page overflow; important actions work by keyboard.
- JSON round trips preserve checklist/contact records, and older exports remain accepted.
- Tests use synthetic data in isolated directories and never query listing providers. Remaining blocked checks are reported explicitly.

## Implemented and verified on October 27, 2026

- The five implementation passes above are in place, including MotorSift beta branding and complete JSON export.
- Isolated tests cover chip removal/reset, favorites and sorting, view-state restoration after page navigation, offline onboarding, backup round trips, accessible card events, and Details editing.
- Browser checks exercised demo onboarding, favorite and selection actions, comparison, and Details. Inventory and its filter drawer were inspected at 1440px desktop and 390px phone widths, with no horizontal page overflow. Screenshots use synthetic data.
- Fresh installations on the advertised operating systems, physical-phone testing, and Caddy authentication integration checks remain release follow-ups. The Caddy checks require a local Caddy binary.
- This work is local beta preparation. The GitHub repository and deployed app have not been renamed or updated by this change.

## Follow-up page and provider setup pass

- Sources and Settings share official provider signup/key links and explain local credential-store versus Railway-variable setup. Local monthly safety budgets remain distinct from provider entitlements and account-wide usage; [API key setup](API_KEYS.md) records the provider guidance checked for this pass.
- Try demo imports a mixed set of synthetic cars, SUVs, and Rivian pickups offline, without provider calls or changes to saved searches/defaults. The optional Demo connector retains its separate Rivian timeline.
- Automated provider-path checks use synthetic multi-make results and verify configured make/model request filters. General cards, Dashboard summaries, and Financing identify vehicles by their actual make/model and keep Rivian-only assumptions scoped.
- Fresh year limits and provider fallbacks include the current calendar year plus one. Existing workspaces retain explicit saved year limits.
- Financing skips unknown/zero-price vehicles and explains an empty comparison, while leaving the standalone calculator available.
- Remaining release checks: live credential/provider requests with the user's own account, and clean installation on each advertised platform. No live-provider or clean-install result is claimed by this pass.
