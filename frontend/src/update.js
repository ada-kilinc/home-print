// Reloading open dashboards after Home Print is updated.
//
// Home Assistant loads the card as home-print-card.js?v=<version>. When the
// integration reports a newer version (home_print/printers), this page still
// runs the old card, so it reloads once all cards on the page are idle (no
// upload, job, scan, chosen file or open dialog). Busy cards show a Reload
// bar instead until then. A page reloads at most once per version, so a
// stale cache can't make it loop.

const STORAGE_KEY = "home-print-card:reloaded-for";

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

function reloadedFor() {
  try {
    return globalThis.sessionStorage?.getItem(STORAGE_KEY) ?? null;
  } catch (_err) {
    return null;
  }
}

function markReloaded(version) {
  try {
    globalThis.sessionStorage?.setItem(STORAGE_KEY, version);
  } catch (_err) {
    // Without storage the page may ask again; never loops on its own, as
    // the reloaded page runs the new card.
  }
}

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

// Reload now if a newer version is waiting and nothing on the page is busy.
export function maybeReload() {
  const version = state.pending;
  if (!version || reloadedFor() === version) return false;
  for (const card of state.cards) if (card._isBusy()) return false;
  markReloaded(version);
  state.reload();
  return true;
}

// The Reload button: reload even if something is open.
export function reloadNow() {
  if (state.pending) markReloaded(state.pending);
  state.reload();
}

// For tests: start over, and replace the page reload.
export const updateState = {
  reset({ running = null, reload } = {}) {
    state.running = running;
    state.pending = null;
    if (reload) state.reload = reload;
    try {
      globalThis.sessionStorage?.removeItem(STORAGE_KEY);
    } catch (_err) {
      // ignore
    }
  },
};
