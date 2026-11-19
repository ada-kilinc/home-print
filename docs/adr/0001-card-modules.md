# 1. Split the card into modules with a build step

Status: accepted (2026-11-19). Not done yet; it comes before the next card feature.

## Context

`custom_components/home_print/frontend/home-print-card.js` is one hand-written file of about 3,300 lines. It holds the strings, icons, styles, template, the card class (about 1,950 lines) and the editor. Each feature makes it harder to review and easier to break something unrelated.

These constraints stay:

- Home Assistant loads one file from the integration's static path, with `?v=<version>` for caching.
- HACS installs the release zip as it is, with no build step on the user's side.
- The vitest suite tests the file that ships.

## Decision

- Write the card as ES modules in `custom_components/home_print/frontend/src/`.
- Bundle them with esbuild into the same `home-print-card.js`, a single file with no imports. Commit that file, so the release zip and HACS need no build.
- Add `npm run build`. CI rebuilds and fails when the committed bundle differs from the output.
- Keep the tests on the bundle. Pure helpers (strings, formatting, page ranges) can get their own unit tests.
- Module boundaries:
  - `i18n.js` for strings and `t()`
  - `icons.js`
  - `styles.js` and `template.js`
  - `api.js` for WebSocket calls and uploads
  - `print.js` for the file, options and job
  - `history.js` for history and preview
  - `scan.js`
  - `switcher.js`
  - `editor.js`
  - `card.js` for the element, state and render loop
- Split the class with plain functions that take the card. Don't use mixins or a framework.
- Make the move one refactor PR with no change in behaviour. The tests must pass unchanged.

## Alternatives

- **Keep one file.** Nothing new to learn, but the file keeps growing.
- **Ship several files and let the browser import them.** No build is needed, but every file needs the version query and the right load order. A half-updated cache would break the card.
- **Lit or another framework.** It would mean rewriting the card's rendering, too big a change for the gain.

## Consequences

- Contributors need Node to change the card. They need it already for the tests.
- Diffs of the committed bundle are noisy. Reviewers read `src/`.
