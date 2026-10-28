# Release checks

Public source repository: [connorkeetch/truck-finder](https://github.com/connorkeetch/truck-finder).
The project uses the [MIT license](../LICENSE). These checks apply to future releases as well as the first one.
[MotorSift 0.2.0 beta 1](https://github.com/connorkeetch/truck-finder/releases/tag/v0.2.0b1) is dated October 28, 2026; see [CHANGELOG.md](../CHANGELOG.md).

## 0.2.0 beta 1 verification record — October 28, 2026

Python 3.12 or newer is required. Only Python 3.12 has been tested; a higher version meeting the minimum is
not a claim of verified compatibility.

| Check | Result and scope |
|---|---|
| GitHub Actions | The prior commit, `2e6b11c`, passed the Python 3.12 suite on Windows and Linux. Publication requires the release commit to pass both jobs in [Actions](https://github.com/connorkeetch/truck-finder/actions/workflows/tests.yml). |
| Provider credentials | Native Windows keyring reads succeeded for both providers. |
| Live provider smoke | Exactly one HTTP 200 request per provider for **Toyota Camry** returned 20 Auto.dev listings and 50 MarketCheck listings. Each run was deliberately capped at one request and marked **partial**, using an isolated database with photos and enrichment disabled. This does not verify full pagination, complete scans, or live multi-brand searches. |
| General vehicle support | Automated tests use synthetic multi-make results and check configured make/model request filters. The live smoke above covers one make/model only. |
| Local hosted authentication | All 13 deployment tests passed, including 10 Caddy 2.11.7 integration cases covering authentication and WebSocket access. The binary was checked against the official SHA-512 checksum. This is not verification of the deployed Railway revision. |
| Clean Windows setup | A clean source folder and new Python 3.12.10 virtual environment installed `requirements.txt` (Streamlit 1.66.1, pandas 3.1.0) and started through `run.bat`. This used the existing Windows installation, not a fresh OS. |
| Offline shopping flow | Empty onboarding, opening/canceling Refresh, importing 29 synthetic demo vehicles, favoriting Camry, comparing Camry/Honda, opening/closing Details with selection retained, saving a three-make preset, and making a valid UI backup passed. Database checks confirmed **zero provider calls** from these UI actions. |
| Data round trip | JSON export/import from a consistent in-memory database copy retained checklist/contact records. Purging a separate copy removed all 29 demo vehicles and their dependencies. |
| Fresh-environment suite | **967 passed in 89.14 seconds, no skips**, including all 13 deployment tests. |
| Data and import fixes | Regression tests cover oldest-backup restore protection, dependent-record demo purge, Python minimum enforcement, and negated powered-tonneau parsing. Exclusive unique backup filenames preserve the selected source and safety copy when timestamps collide; frozen-time cases passed. |
| Private security reports | GitHub private vulnerability reporting is enabled, matching [SECURITY.md](../SECURITY.md). |

Require passing Windows/Linux CI for the release commit before publication. Native macOS/Linux launchers,
a physical phone, and the deployed revision remain unverified. The existing policy that counts manual
backups toward the 30-file retention limit remains unchanged
([B5](IMPROVEMENTS.md#b5-old-manual-backups-get-pruned)).

## Checklist for each release

- Start from a clean source checkout. Exclude `.env`, credentials, `data/`, downloaded `static/photos/`, local
  development settings, exports, logs, backups, and actual shopping inventory. Review the staged files before
  the first push; `.gitignore` does not remove files already tracked by Git.
- Keep examples and screenshots synthetic. Review older research notes and documentation for personal
  shopping history and stale provider claims before including them in a release.
- Verify a fresh install on the advertised Python version without existing settings or credentials. Confirm
  manual/demo use, make/model configuration, and that opening/canceling Refresh listings uses no inventory calls.
- Check the main shopping flow on desktop and phone: demo/setup/import empty states, sidebar filters,
  active-filter removal and clearing, favorites, comparison, details, and returning to the same results.
- Round-trip JSON export/import with checklist and seller-contact records in an isolated workspace. Older
  exports made before those tables were included cannot restore records that were never exported.
- Check restoring the oldest retained backup and removing demo data with checklist/contact records. Preserve
  the selected backup, the pre-restore safety copy, and real inventory through successful and failed operations.
- Run `python -m pytest`. Review the Windows/Linux [GitHub Actions workflow](../.github/workflows/tests.yml)
  for the release commit; check platform launchers on each platform claimed as tested.
- Confirm the bundled `rivian_finder/data/epa_r1t.json` catalog is tracked. Only the root `/data/` directory is
  private runtime data.
- Document provider-account requirements and keep specialist Rivian rules clearly labeled. API availability,
  coverage, pricing, and quotas are controlled by the provider. Report live call counts and search scope
  separately from automated tests.

Existing users' databases and saved preferences stay local. Publishing the source should not reset or upload
their workspaces.
