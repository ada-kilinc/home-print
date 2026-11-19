# Home Print

A Home Assistant custom integration (`custom_components/home_print`) with a dashboard card, for IPP printers and eSCL scanners. Installed from a release zip through HACS (the Marketplace).

## Working here

- **The card's source is `frontend/src/`.** `npm run build` bundles it into `custom_components/home_print/frontend/home-print-card.js`, which is committed. Never edit the bundle by hand. CI runs `npm run build:check` and fails if the two differ ([ADR 1](docs/adr/0001-card-modules.md)).
- **Checks before saying something is done:** `ruff check` and `ruff format --check` (custom_components, tests, scripts), `pytest -q`, `npm run format:check`, `npm run build:check`, `npm test`. For UI changes, render the card in a real browser (`python scripts/screenshots.py`) and look at it.
- **Screenshots:** `python scripts/screenshots.py` redraws `docs/images/` from the real card. Redraw them when the UI changes.
- **Real device data:** eSCL fixtures come from a real HP DeskJet 4670, redacted with `scripts/redact_escl.py`. Only the duplex/black-and-white fixture is synthetic.

## Releases and GitHub

- Everything on GitHub is in English: README, release notes, issues, PRs, commit messages.
- A feature commit, then a separate `chore: release X.Y.Z` commit that bumps `manifest.json` and the `?v=` in `tests/test_frontend.py`.
- Issue-closing references (`Closes #n`) go in commit messages only, never in release notes.
- Commit author: Ada Kılınç <adakilinc23@gmail.com>. Never add a `Claude-Session:` line to commits or PRs.

## Home Assistant lessons (learned the hard way)

1. **An update isn't live until Home Assistant restarts.** HACS writes the new files at once, but HA keeps running the version it loaded at start-up. Users then see "nothing changed". `update_check.py` compares `manifest.json` on disk with the loaded version every few minutes. While they differ, it raises a Repairs issue, and the card shows a restart notice (with a two-tap Restart button for admins).
2. **Open dashboards keep running the old card.** The integration loads the card with `add_extra_js_url(...?v=<version>)`, but a page that's already open keeps the old JavaScript. `home_print/printers` reports the integration version. The card (`frontend/src/update.js`) compares it with its own `?v=` and reloads the page once, when nothing on the page is busy. It reloads at most once per version, so a stale cache can't loop.
3. **A custom element can only be defined once per page.** If an old copy of the card loads first (for example, a hand-added Lovelace resource), the new one can't replace it. Users must not add the card as a resource. The integration loads it.
4. **Check what actually ships.** Unpack the release zip and confirm that the change is in it, before blaming the user's setup.
5. **Diagnose with facts from the user's browser, not guesses.** Ask for the loaded card URL first (`performance.getEntriesByType("resource")` filtered on `home-print`). The `?v=` in it shows which version Home Assistant is really running.
6. **The card is an ES module** (HA loads it with `type="module"`). It may use `import.meta`. Any test harness must load it as a module too.
