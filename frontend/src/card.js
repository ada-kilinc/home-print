// The card element: state, data loading and the render loop.

import {
  CONFIRM_MS,
  EDITOR_TYPE,
  FILE_INPUTS,
  KNOWN_STATES,
  REFRESH_MS,
  SCANNER_STATES,
} from "./constants.js";
import { CropPart } from "./crop.js";
import { readStored, storageKey, usesPickMenu } from "./helpers.js";
import { HistoryPart } from "./history.js";
import { pickLanguage, t } from "./i18n.js";
import { PrintPart } from "./print.js";
import { ScanPart } from "./scan.js";
import { SwitcherPart } from "./switcher.js";
import { TEMPLATE } from "./template.js";
import {
  maybeReload,
  noteServerVersion,
  pendingVersion,
  registerCard,
  reloadNow,
  unregisterCard,
} from "./update.js";

export class HomePrintCard extends HTMLElement {
  constructor() {
    super();
    this._config = { show_ink: true };
    this._hass = null;
    this._printers = null;
    this._loadFailed = false;
    this._loading = false;
    this._pickedId = null;
    this._appliedId = null;
    this._storageKey = null;
    this._listKey = "";
    this._uploadEntryId = null;
    this._file = null;
    this._uploading = false;
    this._message = null;
    this._job = null;
    this._refreshTimer = null;
    this._pollTimer = null;
    // The printer whose history is open; null while the popup is closed.
    this._historyEntryId = null;
    this._historyEntries = [];
    this._historyToken = 0;
    this._previewToken = 0;
    this._preview = null;
    this._crop = null;
    this._cropToken = 0;
    this._restartRequired = null;
    this._deletedIds = new Set();
    // "prints" or "scans": the history tab shown.
    this._historyTab = "prints";
    this._savedOverflow = null;
    // Scanning. _scan is the scan being followed ({entryId, scanId, started,
    // appendPages}); _scanResult the finished document shown in the panel.
    // "print" or "scan": the card body's tab.
    this._tab = "print";
    this._scan = null;
    this._scanTimer = null;
    this._scanResult = null;
    this._scanMessage = null;
    this._scanAppliedId = null;
    this._scanImgToken = 0;
    // Scan ids already followed, so a printers list that still names a
    // finished scan never resumes it.
    this._scanSeen = new Set();
    // Buttons waiting for their second tap: button -> {timer, children, label}.
    this._armed = new Map();
    this._onDocumentClick = (ev) => this._closeMenuOutside(ev);
    this._onDocumentClickList = (ev) => this._closeListOutside(ev);
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = TEMPLATE;
    for (const name of FILE_INPUTS) {
      this._role(name).addEventListener("change", (ev) => this._onFile(ev));
    }
    this._role("pick").addEventListener("click", () => this._onPickButton());
    for (const option of this.shadowRoot.querySelectorAll("[data-option]")) {
      option.addEventListener("click", () => this._onPickOption(option.dataset.option));
    }
    this._role("pick-menu").addEventListener("keydown", (ev) => this._onMenuKey(ev));
    for (const name of ["pick", "pick-menu"]) {
      this._role(name).addEventListener("focusout", (ev) => this._onMenuFocusOut(ev));
    }
    this._role("print").addEventListener("click", () => this._onPrint());
    this._role("switcher").addEventListener("click", () => this._onSwitcher());
    this._role("switcher").addEventListener("keydown", (ev) => this._onSwitcherKey(ev));
    const list = this._role("printer-list");
    list.addEventListener("keydown", (ev) => this._onListKey(ev));
    list.addEventListener("click", (ev) => this._onListClick(ev));
    for (const name of ["switcher", "printer-list"]) {
      this._role(name).addEventListener("focusout", (ev) => this._onListFocusOut(ev));
    }
    this._role("history-button").addEventListener("click", () => this._openHistory());
    this._role("history-close").addEventListener("click", () => this._closeHistory());
    this._role("preview-close").addEventListener("click", () => this._closePreview());
    this._wireDialog(this._role("history-dialog"), () => this._closeHistory());
    this._wireDialog(this._role("preview-dialog"), () => this._closePreview());
    this._wireDialog(this._role("crop-dialog"), () => {
      if (!this._crop?.saving) this._closeCrop();
    });
    this._role("crop-close").addEventListener("click", () => {
      if (!this._crop?.saving) this._closeCrop();
    });
    this._role("crop-cancel").addEventListener("click", () => this._closeCrop());
    this._role("crop-full").addEventListener("click", () => this._onCropFull());
    this._role("crop-save").addEventListener("click", () => this._onCropSave());
    this._role("crop-prev").addEventListener("click", () => this._onCropPage(-1));
    this._role("crop-next").addEventListener("click", () => this._onCropPage(1));
    const stage = this._role("crop-stage");
    stage.addEventListener("pointerdown", (ev) => this._onCropPointerDown(ev));
    stage.addEventListener("pointermove", (ev) => this._onCropPointerMove(ev));
    stage.addEventListener("pointerup", (ev) => this._onCropPointerUp(ev));
    stage.addEventListener("pointercancel", (ev) => this._onCropPointerUp(ev));
    stage.addEventListener("keydown", (ev) => this._onCropKey(ev));
    this._role("scan-crop").addEventListener("click", () => this._onScanCrop());
    this._role("update-reload").addEventListener("click", () => reloadNow());
    const restart = this._role("update-restart");
    restart.addEventListener("click", () =>
      this._confirmTap(restart, () => this._restartHomeAssistant(), "update_restart_confirm"),
    );
    // Back on the tab (or the app in front again): look for news at once.
    this._onVisible = () => {
      if (document.visibilityState === "visible" && this._hass) this._loadPrinters();
    };
    for (const tab of this._bodyTabs()) {
      tab.addEventListener("click", () => this._selectTab(tab.dataset.bodyTab));
    }
    this._role("body-tabs").addEventListener("keydown", (ev) => this._onBodyTabKey(ev));
    this._role("scan-source").addEventListener("change", () => this._update());
    this._role("scan-start").addEventListener("click", () => this._onScanStart());
    this._role("scan-cancel").addEventListener("click", () => this._onScanCancel());
    this._role("scan-add").addEventListener("click", () => this._onScanAdd());
    this._role("scan-download").addEventListener("click", () => this._onScanDownload());
    const scanDelete = this._role("scan-delete");
    scanDelete.addEventListener("click", () =>
      this._confirmTap(scanDelete, () => this._deleteScanResult()),
    );
    this._role("scan-prev").addEventListener("click", () => this._onScanPage(-1));
    this._role("scan-next").addEventListener("click", () => this._onScanPage(1));
    const name = this._role("scan-name");
    name.addEventListener("keydown", (ev) => this._onScanNameKey(ev));
    name.addEventListener("blur", () => this._renameScan());
    for (const tab of this._role("history-tabs").querySelectorAll('[role="tab"]')) {
      tab.addEventListener("click", () => this._switchHistoryTab(tab.dataset.tab));
    }
    this._role("history-tabs").addEventListener("keydown", (ev) => this._onTabKey(ev));
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TYPE);
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    const next = {
      entry_id:
        typeof config.entry_id === "string" && config.entry_id ? config.entry_id : undefined,
      title: typeof config.title === "string" && config.title ? config.title : undefined,
      show_ink: config.show_ink !== false,
    };
    const key = storageKey(next.entry_id);
    if (key !== this._storageKey) {
      this._storageKey = key;
      this._pickedId = readStored(key);
    }
    this._config = next;
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected) this._startRefresh();
    this._update();
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 5;
  }

  connectedCallback() {
    registerCard(this);
    document.addEventListener("visibilitychange", this._onVisible);
    if (this._hass) this._startRefresh();
    if (this._job && !this._pollTimer) this._schedulePoll();
    if (this._scan?.scanId && !this._scanTimer) this._scheduleScanPoll();
  }

  disconnectedCallback() {
    unregisterCard(this);
    document.removeEventListener("visibilitychange", this._onVisible);
    this._closeHistory();
    this._closeMenu();
    this._closeList();
    clearInterval(this._refreshTimer);
    clearTimeout(this._pollTimer);
    clearTimeout(this._scanTimer);
    this._disarmAll();
    this._refreshTimer = null;
    this._pollTimer = null;
    this._scanTimer = null;
  }

  _startRefresh() {
    if (this._refreshTimer) return;
    this._refreshTimer = setInterval(() => this._loadPrinters(), REFRESH_MS);
    this._loadPrinters();
  }

  async _loadPrinters() {
    if (this._loading || !this._hass) return;
    this._loading = true;
    try {
      const result = await this._hass.callWS({ type: "home_print/printers" });
      this._printers = Array.isArray(result?.printers) ? result.printers : [];
      noteServerVersion(result?.version);
      this._restartRequired =
        typeof result?.restart_required === "string" ? result.restart_required : null;
      this._loadFailed = false;
    } catch (_err) {
      // Keep the last good list; only complain when there never was one.
      if (this._printers === null) this._loadFailed = true;
    } finally {
      this._loading = false;
    }
    this._update();
  }

  // The printer picked in this browser while it is still listed, then the
  // card's entry_id, then (null) the first printer.
  _wantedId() {
    const picked = this._pickedId;
    if (picked && (this._printers === null || this._printers.some((p) => p.entry_id === picked))) {
      return picked;
    }
    return this._config.entry_id ?? null;
  }

  _printer() {
    const printers = this._printers ?? [];
    const wanted = this._wantedId();
    if (wanted) return printers.find((p) => p.entry_id === wanted) ?? null;
    return printers[0] ?? null;
  }

  _reachable(printer) {
    if (!printer || !printer.available) return false;
    const entities = printer.entities ?? {};
    const own = printer.kind === "scanner" ? entities.scanner_status : entities.status;
    return this._entityState(own)?.state !== "unavailable";
  }

  _entityState(entityId) {
    return entityId ? this._hass?.states?.[entityId] : undefined;
  }

  // First tap arms the button ("Sure?"), the second within CONFIRM_MS runs
  // `action`; otherwise it goes back to how it was.
  _confirmTap(button, action, key = "confirm_delete") {
    if (this._armed.has(button)) {
      this._disarm(button);
      action();
      return;
    }
    const lang = pickLanguage(this._hass);
    const label = document.createElement("span");
    label.textContent = t(lang, key);
    this._armed.set(button, {
      children: [...button.childNodes],
      label: button.getAttribute("aria-label"),
      timer: setTimeout(() => this._disarm(button), CONFIRM_MS),
    });
    button.classList.add("armed");
    button.setAttribute("aria-label", label.textContent);
    button.replaceChildren(label);
  }

  _disarm(button) {
    const armed = this._armed.get(button);
    if (!armed) return;
    this._armed.delete(button);
    clearTimeout(armed.timer);
    button.classList.remove("armed");
    if (armed.label === null) button.removeAttribute("aria-label");
    else button.setAttribute("aria-label", armed.label);
    button.replaceChildren(...armed.children);
  }

  _disarmAll() {
    for (const button of [...this._armed.keys()]) this._disarm(button);
  }

  // Fill a select only when its options change, so an open dropdown survives
  // the frequent hass updates.
  _setOptions(select, values, label, wanted) {
    const items = values.map((value) => [String(value), label(value)]);
    const key = JSON.stringify(items);
    if (select.dataset.key !== key) {
      select.replaceChildren(
        ...items.map(([value, text]) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = text;
          return option;
        }),
      );
      select.dataset.key = key;
    }
    const strings = items.map(([value]) => value);
    select.value = strings.includes(String(wanted)) ? String(wanted) : (strings[0] ?? "");
  }

  _role(name) {
    return this.shadowRoot.querySelector(`[data-role="${name}"]`);
  }

  _row(name) {
    return this.shadowRoot.querySelector(`[data-opt="${name}"]`);
  }

  _optionShown(name) {
    return !this._row(name).hidden;
  }

  _update() {
    const lang = pickLanguage(this._hass);
    const root = this.shadowRoot;
    for (const el of root.querySelectorAll("[data-t]")) {
      el.textContent = t(lang, el.dataset.t);
    }
    for (const el of root.querySelectorAll("[data-aria]")) {
      el.setAttribute("aria-label", t(lang, el.dataset.aria));
      el.title = t(lang, el.dataset.aria);
    }
    this._role("pages").placeholder = t(lang, "pages_placeholder");

    const printers = this._printers ?? [];
    const printer = this._printer();
    const wanted = this._wantedId();
    const unknown = Boolean(wanted) && this._printers !== null && !printer;

    this._renderNotice(lang, printer, unknown, wanted);
    this._renderUpdate(lang);
    // With a choice of printers the header names the one shown; the card's
    // own title is for a single printer.
    const multi = printers.length > 1;
    const name = printer ? printer.title || printer.entry_id : "";
    this._role("title").textContent =
      (multi ? name : this._config.title || name) || this._config.title || "Home Print";
    this._role("state").textContent = printer ? this._statusText(lang, printer) : "";
    this._renderSwitcher(lang, printers, printer, unknown);
    this._applyPrinter(printer);
    this._renderInk(lang, printer);
    this._renderOptions(printer);
    this._renderFile(lang, printer);
    this._role("print").disabled = !this._canSubmit(printer);
    this._renderScan(lang, printer);
    this._role("history-button").hidden = !printer;
    const pick = this._role("pick");
    if (!usesPickMenu(globalThis.navigator, globalThis)) {
      pick.removeAttribute("aria-haspopup");
      pick.removeAttribute("aria-expanded");
    } else {
      pick.setAttribute("aria-haspopup", "menu");
      pick.setAttribute("aria-expanded", String(!this._role("pick-menu").hidden));
    }
    // The open history belongs to one printer; another one closes it.
    if (this._historyEntryId && this._historyEntryId !== printer?.entry_id) this._closeHistory();
  }

  // Something that a reload after an update would interrupt.
  _isBusy() {
    return (
      Boolean(this._uploading || this._job || this._scan || this._crop || this._file) ||
      this._anyDialogOpen() ||
      !this._role("pick-menu").hidden
    );
  }

  // A newer Home Print: reload when idle, else offer the button. Installed
  // but not running yet: Home Assistant needs a restart (admins get a button).
  _renderUpdate(lang) {
    const version = pendingVersion();
    const installed = version ? null : this._restartRequired;
    const bar = this._role("update");
    bar.hidden = !version && !installed;
    this._role("update-reload").hidden = !version;
    const restart = this._role("update-restart");
    restart.hidden = !installed || !this._hass?.user?.is_admin;
    if (version) {
      this._role("update-text").textContent = t(lang, "update_available", { version });
      maybeReload();
    } else if (installed) {
      this._role("update-text").textContent = t(lang, "update_restart_needed", {
        version: installed,
      });
    }
  }

  async _restartHomeAssistant() {
    const lang = pickLanguage(this._hass);
    try {
      await this._hass.callService("homeassistant", "restart", {});
    } catch (_err) {
      // The connection drops while Home Assistant goes down; that is fine.
      return;
    }
    this._role("update-text").textContent = t(lang, "update_restarting");
    this._role("update-restart").hidden = true;
  }

  _renderNotice(lang, printer, unknown, wanted) {
    let key = null;
    if (this._loadFailed) key = "load_failed";
    else if (this._printers === null) key = this._hass ? "loading" : null;
    else if (this._printers.length === 0) key = "no_printers";
    else if (unknown) key = "unknown_printer";
    else if (printer && printer.can_print === false) key = "not_allowed";
    const notice = this._role("notice");
    notice.hidden = key === null;
    notice.textContent = key ? t(lang, key, { id: wanted }) : "";
    notice.classList.toggle("info", key === "loading");
  }

  _statusText(lang, printer) {
    if (!this._reachable(printer)) return t(lang, "state_unreachable");
    if (printer.kind === "scanner") {
      const state = this._entityState(printer.entities?.scanner_status)?.state;
      return SCANNER_STATES.includes(state)
        ? t(lang, `scanner_state_${state}`)
        : t(lang, "state_unknown");
    }
    const entity = this._entityState(printer.entities?.status)?.state;
    const state = KNOWN_STATES.includes(entity) ? entity : printer.state;
    let text = KNOWN_STATES.includes(state) ? t(lang, `state_${state}`) : t(lang, "state_unknown");
    if (this._entityState(printer.entities?.problem)?.state === "on") {
      text += ` · ${t(lang, "problem")}`;
    }
    return text;
  }
}

// The parts are plain classes whose methods are copied onto the card,
// so `this` is the card in every one of them.
for (const Part of [PrintPart, HistoryPart, ScanPart, SwitcherPart, CropPart]) {
  for (const key of Object.getOwnPropertyNames(Part.prototype)) {
    if (key === "constructor") continue;
    Object.defineProperty(
      HomePrintCard.prototype,
      key,
      Object.getOwnPropertyDescriptor(Part.prototype, key),
    );
  }
}
