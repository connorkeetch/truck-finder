# Release checks

Public source repository: [connorkeetch/truck-finder](https://github.com/connorkeetch/truck-finder).
The project uses the [MIT license](../LICENSE). These checks apply to future releases as well as the first one.
The current **MotorSift 0.2.0 beta 1** entry is unreleased; see [CHANGELOG.md](../CHANGELOG.md).

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
- Run `python -m pytest`. A GitHub Actions workflow checks Windows and Linux after publication; check platform
  launchers on each platform claimed as tested.
- Confirm the bundled `rivian_finder/data/epa_r1t.json` catalog is tracked. Only the root `/data/` directory is
  private runtime data.
- Document provider-account requirements and keep specialist Rivian rules clearly labeled. API availability,
  coverage, pricing, and quotas are controlled by the provider.

Existing users' databases and saved preferences stay local. Publishing the source should not reset or upload
their workspaces.
