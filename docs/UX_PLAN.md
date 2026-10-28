# MotorSift beta usability plan

The 0.2.0 beta release makes the existing vehicle-shopping workflow easier to discover and scan.

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
- At the end of this UI pass, fresh installations, physical-phone testing, and Caddy authentication integration checks remained follow-ups. Later results are recorded below.
- The public app name is MotorSift; the GitHub repository and internal identifiers retain their existing names. Deployment verification is separate from the UI changes.

## Follow-up page and provider setup pass

- Sources and Settings share official provider signup/key links and explain local credential-store versus Railway-variable setup. Local monthly safety budgets remain distinct from provider entitlements and account-wide usage; [API key setup](API_KEYS.md) records the provider guidance checked for this pass.
- Try demo imports a mixed set of synthetic cars, SUVs, and Rivian pickups offline, without provider calls or changes to saved searches/defaults. The optional Demo connector retains its separate Rivian timeline.
- Automated provider-path checks use synthetic multi-make results and verify configured make/model request filters. General cards, Dashboard summaries, and Financing identify vehicles by their actual make/model and keep Rivian-only assumptions scoped.
- Fresh year limits and provider fallbacks include the current calendar year plus one. Existing workspaces retain explicit saved year limits.
- Financing skips unknown/zero-price vehicles and explains an empty comparison, while leaving the standalone calculator available.
- Later live-provider and installation results are recorded below. The multi-brand checks in this pass use synthetic data.

## Release validation follow-up — October 28, 2026

- Native Windows keyring reads worked for both providers. One HTTP 200 request each for Toyota Camry returned 20 Auto.dev and 50 MarketCheck listings in an isolated database. Both runs were deliberately capped at one request and marked partial; photos and enrichment were disabled. Live multi-brand collection and complete pagination were not exercised.
- The prior commit passed Python 3.12 CI on Windows and Linux. Publication requires both jobs to pass for the release commit in [Actions](https://github.com/connorkeetch/truck-finder/actions/workflows/tests.yml). All 13 deployment tests passed, including 10 Caddy 2.11.7 integration cases covering authentication and WebSockets, using a binary verified against the official SHA-512 checksum.
- The launcher requires Python 3.12+ for both its host interpreter and an existing virtual environment; only Python 3.12 is tested. Restore protects the selected oldest backup and safety copy, including timestamp collisions through exclusive unique filenames. Demo purge removes dependent checklist/contact records, and manual imports handle negated powered-tonneau text. Frozen-time regression cases passed; general manual-backup retention is unchanged.
- A clean source folder and new Python 3.12.10 environment on the existing Windows installation passed dependency installation, `run.bat` startup, offline onboarding, Refresh cancellation, 29-vehicle demo import, favorite/comparison/Details actions, selection retention, a saved three-make preset, and a valid UI backup. Database checks confirmed zero provider calls from the UI.
- A consistent in-memory copy round-tripped JSON with checklist/contact records; a separate purge copy removed all 29 demo vehicles and dependents. The fresh-environment suite passed **967 tests in 89.14 seconds with no skips**, including Caddy. Native macOS/Linux launchers, physical-phone use, and the deployed revision remain unverified. [Release checks](PUBLIC_RELEASE.md) records the scope.
