// The card's visual editor (home-print-card-editor).

import { EDITOR_RETRY_MS } from "./constants.js";
import { pickLanguage, t } from "./i18n.js";

export const EDITOR_STYLE = `
  :host { display: block; }
  .field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
  label { color: var(--secondary-text-color); font-size: 0.9em; }
  select, input[type="text"] {
    min-height: 44px;
    box-sizing: border-box;
    padding: 0 12px;
    font: inherit;
    color: var(--primary-text-color);
    background: var(--card-background-color, transparent);
    border: 1px solid var(--divider-color);
    border-radius: 8px;
  }
  .check { flex-direction: row; align-items: center; gap: 12px; min-height: 44px; }
  .check label { color: var(--primary-text-color); font-size: 1em; flex: 1; }
  input[type="checkbox"] { width: 24px; height: 24px; accent-color: var(--primary-color); }
`;

export const EDITOR_TEMPLATE = `
  <style>${EDITOR_STYLE}</style>
  <div class="field">
    <label for="printer" data-role="printer-label"></label>
    <select id="printer" data-role="printer"></select>
  </div>
  <div class="field">
    <label for="title" data-role="title-label"></label>
    <input id="title" type="text" data-role="title" />
  </div>
  <div class="field check">
    <label for="show_ink" data-role="show-ink-label"></label>
    <input id="show_ink" type="checkbox" data-role="show_ink" />
  </div>
`;

export class HomePrintCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._printers = null;
    this._loading = false;
    this._failedAt = null;
    this._optionsKey = "";
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = EDITOR_TEMPLATE;
    this._role("printer").addEventListener("change", () => this._onPrinter());
    for (const ev of ["input", "change"]) {
      this._role("title").addEventListener(ev, () => this._onTitle());
    }
    this._role("show_ink").addEventListener("change", () => this._onShowInk());
  }

  _role(name) {
    return this.shadowRoot.querySelector(`[data-role="${name}"]`);
  }

  setConfig(config) {
    this._config = { ...(config ?? {}) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
    // Load once; after a failure, try again on a later hass at most every 30 s.
    const due = this._failedAt === null || Date.now() - this._failedAt >= EDITOR_RETRY_MS;
    if (this._printers === null && !this._loading && due && hass?.callWS) this._loadPrinters();
  }

  async _loadPrinters() {
    this._loading = true;
    try {
      const result = await this._hass.callWS({ type: "home_print/printers" });
      this._printers = Array.isArray(result?.printers) ? result.printers : [];
      this._failedAt = null;
    } catch {
      this._failedAt = Date.now();
    } finally {
      this._loading = false;
    }
    this._render();
  }

  _render() {
    const lang = pickLanguage(this._hass);
    this._role("printer-label").textContent = t(lang, "editor_printer");
    this._role("title-label").textContent = t(lang, "editor_title");
    this._role("show-ink-label").textContent = t(lang, "editor_show_ink");

    const select = this._role("printer");
    const wanted = this._config.entry_id ?? "";
    const printers = this._printers ?? [];
    const options = [{ value: "", label: t(lang, "editor_auto") }];
    for (const printer of printers) {
      options.push({ value: printer.entry_id, label: printer.title || printer.entry_id });
    }
    if (wanted && !printers.some((p) => p.entry_id === wanted)) {
      options.push({ value: wanted, label: t(lang, "editor_not_found", { id: wanted }) });
    }
    // Rebuild only when the list changes, so an open dropdown survives the
    // frequent hass updates.
    const key = JSON.stringify(options.map(({ value, label }) => [value, label]));
    if (key !== this._optionsKey) {
      select.replaceChildren(
        ...options.map(({ value, label }) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          return option;
        }),
      );
      this._optionsKey = key;
    }
    if (select.value !== wanted) select.value = wanted;

    const title = this._role("title");
    const wantedTitle = typeof this._config.title === "string" ? this._config.title : "";
    if (title.value !== wantedTitle) title.value = wantedTitle;
    this._role("show_ink").checked = this._config.show_ink !== false;
  }

  _emit(config) {
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", { bubbles: true, composed: true, detail: { config } }),
    );
  }

  _onPrinter() {
    const config = { ...this._config };
    const value = this._role("printer").value;
    if (value) config.entry_id = value;
    else delete config.entry_id;
    this._emit(config);
  }

  _onTitle() {
    const value = this._role("title").value;
    if (value === (this._config.title ?? "")) return;
    const config = { ...this._config };
    if (value) config.title = value;
    else delete config.title;
    this._emit(config);
  }

  _onShowInk() {
    const config = { ...this._config };
    if (this._role("show_ink").checked) delete config.show_ink;
    else config.show_ink = false;
    this._emit(config);
  }
}
