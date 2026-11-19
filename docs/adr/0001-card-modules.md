# 1. Split the card into modules with a build step

Status: done (2026-11-19, version 0.3.12).

## Context

`custom_components/home_print/frontend/home-print-card.js` was one hand-written file of about 3,300 lines. It held the strings, icons, styles, template, the card class (about 1,900 lines) and the editor. Each feature made it harder to review and easier to break something unrelated.

These constraints stay:

- Home Assistant loads one file from the integration's static path, with `?v=<version>` for caching.
- HACS installs the release zip as it is, with no build step on the user's side.
- The vitest suite tests the file that ships.

## Decision

- The source is ES modules in `frontend/src/`, outside the integration folder, so it isn't served or shipped.
- esbuild (pinned) bundles them into the same `home-print-card.js`: one file, no imports. That file is committed, so the release zip and HACS need no build.
- `npm run build` writes the bundle. `npm run build:check` fails when the committed bundle differs from the sources, and CI runs it. Prettier checks `frontend/`.
- The tests stay on the bundle.
- Modules:

  | File | What's in it |
  | --- | --- |
  | `constants.js` | timings, limits, fixed lists |
  | `icons.js` | icon paths and helpers |
  | `i18n.js` | strings and `t()` |
  | `helpers.js` | pure helpers: file checks, labels, paths, storage |
  | `styles.js`, `template.js` | CSS and HTML |
  | `card.js` | the element, state, data loading, render loop |
  | `print.js` | Print tab |
  | `scan.js` | Scan tab |
  | `history.js` | history and preview dialogs |
  | `switcher.js` | printer switcher |
  | `editor.js` | visual editor |
  | `index.js` | registers both elements |

- `print.js`, `scan.js`, `history.js` and `switcher.js` each export a plain class whose methods `card.js` copies onto the card's prototype. The method bodies moved unchanged and `this` is still the card. This kept the split a pure move with no behaviour change. It replaces the "functions that take the card" idea from the first draft of this record, which would have meant rewriting every method.
- The move was one change with no behaviour change: the 177 card tests passed unchanged, and the README screenshots rendered pixel for pixel the same.

## Alternatives

- **Keep one file.** Nothing new to learn, but the file keeps growing.
- **Ship several files and let the browser import them.** No build is needed, but every file needs the version query and the right load order. A half-updated cache would break the card.
- **Lit or another framework.** It would mean rewriting the card's rendering, too big a change for the gain.

## Consequences

- Contributors need Node to change the card. They need it already for the tests.
- Diffs of the committed bundle are noisy. Reviewers read `frontend/src/`.
- The parts share the card's state through `this`, so a part can still reach anything. Moving state into the parts is possible later, one part at a time.
