// Telling open dashboards that Home Print was updated.
//
// Home Assistant loads the card as home-print-card.js?v=<version>. When the
// integration reports a newer version (home_print/printers), this page still
// runs the old card. Every card then shows an update bar with a Reload
// button; the page is never reloaded without the user asking for it.

function ownVersion() {
  try {
    return new URL(import.meta.url).searchParams.get("v");
  } catch (_err) {
    return null;
  }
}

const state = {
  // The version this page runs: from the card's URL, else the first one the
  // integration reports (a card added by hand without ?v=).
  running: ownVersion(),
  // A newer version the integration reported, or null.
  pending: null,
  cards: new Set(),
  reload: () => globalThis.location.reload(),
};

export function registerCard(card) {
  state.cards.add(card);
}

export function unregisterCard(card) {
  state.cards.delete(card);
}

// Called with the version from each printers answer.
export function noteServerVersion(version) {
  if (typeof version !== "string" || !version) return;
  if (state.running === null) {
    state.running = version;
    return;
  }
  if (version === state.running || version === state.pending) return;
  state.pending = version;
  for (const card of state.cards) card._update();
}

export function pendingVersion() {
  return state.pending;
}

// The Reload button in the update bar.
export function reloadNow() {
  state.reload();
}

// For tests: start over, and replace the page reload.
export const updateState = {
  reset({ running = null, reload } = {}) {
    state.running = running;
    state.pending = null;
    if (reload) state.reload = reload;
  },
};
