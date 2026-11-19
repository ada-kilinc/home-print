// Scan tab: options, start, polling, result, rename, download, delete.

import {
  DOWNLOAD_SIGN_SECONDS,
  FATAL_SCAN_ERRORS,
  SCAN_POLL_LIMIT_MS,
  SCAN_POLL_MS,
  SCAN_SELECTS,
} from "./constants.js";
import {
  scanColorChoices,
  scanColorLabel,
  scanErrorText,
  scanFilePath,
  scanOptionLabel,
  scanPagePath,
} from "./helpers.js";
import { pickLanguage, t } from "./i18n.js";

export class ScanPart {
  _scanBusy() {
    return this._scan !== null;
  }

  _bodyTabs() {
    return [...this._role("body-tabs").querySelectorAll('[role="tab"]')];
  }

  _selectTab(tab) {
    if (tab === "scan" && this._role("body-tab-scan").disabled) return;
    if (tab === this._tab) return;
    this._tab = tab;
    this._update();
  }

  _onBodyTabKey(ev) {
    const tabs = this._bodyTabs().filter((tab) => !tab.disabled);
    const index = tabs.findIndex((tab) => tab.dataset.bodyTab === this._tab);
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 };
    if (!(ev.key in moves) || tabs.length === 0) return;
    ev.preventDefault();
    const next = tabs[(moves[ev.key] + tabs.length) % tabs.length];
    this._selectTab(next.dataset.bodyTab);
    next.focus();
  }

  _onScanStart() {
    const printer = this._printer();
    if (!printer?.scanner || this._scanBusy() || printer.can_print === false) return;
    this._startScan(printer.entry_id, {
      source: this._role("scan-source").value,
      color_mode: this._role("scan-color").value,
      resolution: Number(this._role("scan-resolution").value),
      format: this._role("scan-format").value,
    });
  }

  // Another page from the glass, added to the PDF shown, with its settings.
  _onScanAdd() {
    const result = this._scanResult;
    if (!result || this._scanBusy()) return;
    const record = result.record;
    this._startScan(
      result.entryId,
      {
        source: record.source,
        color_mode: record.color_mode,
        resolution: Number(record.resolution),
        format: "pdf",
        append_to: record.id,
      },
      Number(record.pages) || 0,
    );
  }

  async _startScan(entryId, request, appendPages = null) {
    const lang = pickLanguage(this._hass);
    const now = Date.now();
    const scan = { entryId, scanId: null, started: now, progressAt: now, appendPages };
    this._scan = scan;
    this._disarmAll();
    // A new document replaces the result shown; an added page keeps it.
    if (appendPages === null) this._clearScanResult();
    this._scanMessage = { text: t(lang, "scan_scanning"), kind: "info" };
    this._update();
    let state;
    try {
      state = (
        await this._hass.callWS({ type: "home_print/scan/start", entry_id: entryId, ...request })
      )?.scan;
    } catch (err) {
      if (this._scan !== scan) return;
      this._endScan(scanErrorText(lang, err?.code), "error");
      return;
    }
    if (this._scan !== scan) return;
    scan.scanId = state?.scan_id ?? null;
    if (!scan.scanId) {
      // Nothing to follow; never leave the button held.
      this._endScan(scanErrorText(lang, "scan_failed"), "error");
      return;
    }
    this._scanSeen.add(scan.scanId);
    this._onScanState(scan, state);
  }

  // A scan the server is running that this card isn't following yet: after
  // a reload, or one started on another screen. A finished last_scan alone
  // is not shown, so a card opened later doesn't pop open on old news.
  _resumeScan(printer) {
    const id = printer.scanner?.active_scan_id;
    if (!id || this._scan || this._scanSeen.has(id) || printer.can_print === false) return;
    this._scanSeen.add(id);
    // Whether it adds pages to an earlier PDF is unknown here, so its result
    // opens on the last page: the newest one either way.
    this._scan = {
      entryId: printer.entry_id,
      scanId: id,
      started: Date.now(),
      progressAt: Date.now(),
      appendPages: null,
      resumed: true,
    };
    this._clearScanResult();
    this._tab = "scan";
    this._scanMessage = { text: t(pickLanguage(this._hass), "scan_scanning"), kind: "info" };
    if (this.isConnected) this._scheduleScanPoll();
  }

  _scheduleScanPoll() {
    clearTimeout(this._scanTimer);
    this._scanTimer = setTimeout(() => {
      this._scanTimer = null;
      this._pollScan();
    }, SCAN_POLL_MS);
  }

  async _pollScan() {
    const scan = this._scan;
    if (!scan?.scanId || !this._hass) return;
    const lang = pickLanguage(this._hass);
    // Limit the time without progress, not the whole scan: a long ADF batch
    // keeps changing its page count.
    if (Date.now() - scan.progressAt >= SCAN_POLL_LIMIT_MS) {
      this._endScan(t(lang, "scan_timeout"), "error");
      return;
    }
    let state;
    try {
      state = (
        await this._hass.callWS({
          type: "home_print/scan/state",
          entry_id: scan.entryId,
          scan_id: scan.scanId,
        })
      )?.scan;
    } catch (err) {
      if (this._scan !== scan) return;
      if (FATAL_SCAN_ERRORS.includes(err?.code)) {
        this._endScan(t(lang, "scan_lost"), "error");
        return;
      }
      // A dropped connection: keep asking until the time limit.
      if (this.isConnected) this._scheduleScanPoll();
      return;
    }
    if (this._scan !== scan) return;
    this._onScanState(scan, state);
  }

  _onScanState(scan, state) {
    const lang = pickLanguage(this._hass);
    const progress = `${state?.state}:${state?.pages}`;
    if (progress !== scan.progressKey) {
      scan.progressKey = progress;
      scan.progressAt = Date.now();
    }
    switch (state?.state) {
      case "done": {
        const record = state.record;
        if (record) {
          // After an added page, show the first new one.
          let page = 1;
          if (scan.appendPages !== null) page = scan.appendPages + 1;
          else if (scan.resumed) page = Number(record.pages) || 1;
          this._showScanResult(scan.entryId, record, page);
          this._endScan(t(lang, "scan_done"), "success");
        } else {
          this._endScan(t(lang, "scan_saved"), "info");
        }
        this._reloadScans(scan.entryId);
        return;
      }
      case "error":
        this._endScan(
          scanErrorText(lang, state.error),
          state.error === "canceled" ? "info" : "error",
        );
        return;
      case "saving":
        this._scanMessage = { text: t(lang, "scan_saving"), kind: "info" };
        break;
      default: {
        const pages = Number(state?.pages) || 0;
        const text =
          pages > 0 ? t(lang, "scan_scanning_page", { n: pages + 1 }) : t(lang, "scan_scanning");
        this._scanMessage = { text, kind: "info" };
      }
    }
    this._update();
    if (this.isConnected) this._scheduleScanPoll();
  }

  // Stop the running scan; the server closes the scanner's job.
  async _onScanCancel() {
    const scan = this._scan;
    if (!scan?.scanId || scan.canceling || !this._hass) return;
    scan.canceling = true;
    this._update();
    let state;
    try {
      state = (
        await this._hass.callWS({
          type: "home_print/scan/cancel",
          entry_id: scan.entryId,
          scan_id: scan.scanId,
        })
      )?.scan;
    } catch (err) {
      if (this._scan !== scan) return;
      if (FATAL_SCAN_ERRORS.includes(err?.code)) {
        this._endScan(t(pickLanguage(this._hass), "scan_lost"), "error");
        return;
      }
      // Polling carries on and reports how the scan ends.
      scan.canceling = false;
      this._update();
      return;
    }
    if (this._scan !== scan) return;
    scan.canceling = false;
    this._onScanState(scan, state);
  }

  _endScan(text, kind) {
    clearTimeout(this._scanTimer);
    this._scanTimer = null;
    this._scan = null;
    this._scanMessage = { text, kind };
    this._update();
  }

  // Forget everything about scanning on this card (the printer changed).
  // A scan still running is left to the server; switching back resumes it.
  _resetScan() {
    clearTimeout(this._scanTimer);
    this._scanTimer = null;
    if (this._scan?.scanId) this._scanSeen.delete(this._scan.scanId);
    this._scan = null;
    this._scanMessage = null;
    this._tab = "print";
    this._clearScanResult();
  }

  _reloadScans(entryId) {
    if (this._historyEntryId === entryId && this._historyTab === "scans") this._loadHistory();
  }

  _showScanResult(entryId, record, page = 1) {
    const total = Math.max(1, Number(record.pages) || 1);
    this._scanResult = {
      entryId,
      record,
      page: Math.min(Math.max(1, page), total),
      pendingName: null,
      renameSeq: 0,
      deleting: false,
    };
    this._role("scan-name").value = String(record.name ?? "");
    this._loadScanImage();
  }

  _clearScanResult() {
    this._disarmAll();
    this._scanResult = null;
    this._scanImgToken += 1;
    this._role("scan-page").replaceChildren();
  }

  _onScanPage(step) {
    const result = this._scanResult;
    if (!result) return;
    const total = Math.max(1, Number(result.record.pages) || 1);
    const page = Math.min(Math.max(1, result.page + step), total);
    if (page === result.page) return;
    result.page = page;
    this._update();
    this._loadScanImage();
  }

  // The page shown is signed just before it loads, like the preview's pages.
  async _loadScanImage() {
    const result = this._scanResult;
    if (!result) return;
    const token = ++this._scanImgToken;
    const lang = pickLanguage(this._hass);
    const box = this._role("scan-page");
    const failed = () => {
      if (token !== this._scanImgToken) return;
      box.replaceChildren(this._previewNote(null, t(lang, "preview_failed")));
    };
    let path;
    try {
      path = await this._signPath(scanPagePath(result.entryId, result.record.id, result.page));
    } catch (_err) {
      failed();
      return;
    }
    if (token !== this._scanImgToken) return;
    // A fresh image per page, so a late error of the previous one is ignored.
    const img = document.createElement("img");
    img.dataset.role = "scan-img";
    img.alt = t(lang, "preview_page", { n: result.page });
    img.addEventListener("error", failed);
    img.src = path;
    box.replaceChildren(img);
  }

  _onScanNameKey(ev) {
    const result = this._scanResult;
    if (!result) return;
    if (ev.key === "Enter") {
      ev.preventDefault();
      this._renameScan();
    } else if (ev.key === "Escape") {
      ev.stopPropagation();
      this._role("scan-name").value = String(result.record.name ?? "");
    }
  }

  async _renameScan() {
    const result = this._scanResult;
    if (!result || this._printer()?.can_print === false) return;
    const lang = pickLanguage(this._hass);
    const input = this._role("scan-name");
    const name = input.value.trim();
    if (!name) {
      input.value = String(result.record.name ?? "");
      return;
    }
    // Enter and the blur after it would otherwise send the same name twice.
    if (name === (result.pendingName ?? result.record.name)) return;
    result.pendingName = name;
    // Only the newest request settles the field; an older reply is stale.
    const seq = ++result.renameSeq;
    let entry;
    try {
      entry = (
        await this._hass.callWS({
          type: "home_print/scans/rename",
          entry_id: result.entryId,
          scan_record_id: result.record.id,
          name,
        })
      )?.entry;
    } catch (err) {
      if (this._scanResult !== result) return;
      if (seq !== result.renameSeq) return;
      result.pendingName = null;
      input.value = String(result.record.name ?? "");
      const key = err?.code === "unauthorized" ? "edit_not_allowed" : "rename_failed";
      this._scanMessage = { text: t(lang, key), kind: "error" };
      this._update();
      return;
    }
    if (this._scanResult !== result || seq !== result.renameSeq) return;
    result.pendingName = null;
    if (!entry) {
      // Deleted elsewhere meanwhile.
      this._clearScanResult();
      this._scanMessage = { text: t(lang, "scan_error_not_found"), kind: "error" };
    } else {
      result.record = entry;
      // The server may have tidied the name or added " (2)"; show its name
      // unless the field was edited again while the rename was on its way.
      if (input.value.trim() === name) input.value = String(entry.name ?? "");
    }
    this._update();
    this._reloadScans(result.entryId);
  }

  async _onScanDownload() {
    const result = this._scanResult;
    if (!result) return;
    if (await this._downloadScan(result.entryId, result.record)) return;
    if (this._scanResult !== result) return;
    this._scanMessage = { text: t(pickLanguage(this._hass), "download_failed"), kind: "error" };
    this._update();
  }

  // The file route needs auth, so a short-lived signed link is clicked; the
  // server's Content-Disposition names the file.
  async _downloadScan(entryId, record) {
    let path;
    try {
      path = await this._signPath(scanFilePath(entryId, record.id), DOWNLOAD_SIGN_SECONDS);
    } catch (_err) {
      return false;
    }
    if (!path) return false;
    const link = document.createElement("a");
    link.href = path;
    link.setAttribute("download", "");
    link.hidden = true;
    this.shadowRoot.append(link);
    link.click();
    link.remove();
    return true;
  }

  async _deleteScanResult() {
    const result = this._scanResult;
    if (!result || result.deleting || this._scanBusy()) return;
    const lang = pickLanguage(this._hass);
    result.deleting = true;
    this._update();
    try {
      await this._hass.callWS({
        type: "home_print/scans/delete",
        entry_id: result.entryId,
        scan_record_id: result.record.id,
      });
    } catch (err) {
      if (this._scanResult !== result) return;
      result.deleting = false;
      const key = err?.code === "unauthorized" ? "delete_not_allowed" : "delete_failed";
      this._scanMessage = { text: t(lang, key), kind: "error" };
      this._update();
      return;
    }
    if (this._scanResult === result) {
      this._clearScanResult();
      this._scanMessage = { text: t(lang, "scan_deleted"), kind: "info" };
    }
    this._update();
    this._reloadScans(result.entryId);
  }

  // Options come from the chosen source's capabilities; a value no longer
  // offered falls back to the scanner's default, else the first one.
  _fillScanSelects(lang, scanner, reset) {
    const defaults = scanner.defaults ?? {};
    const pick = (values, current, fallback) => {
      const strings = values.map(String);
      if (!reset && strings.includes(String(current))) return current;
      return strings.includes(String(fallback)) ? fallback : values[0];
    };
    const sources = Object.keys(scanner.sources ?? {});
    const source = pick(sources, this._role("scan-source").value, defaults.source);
    const caps = scanner.sources?.[source] ?? {};
    const colors = scanColorChoices(caps.color_modes ?? []);
    const resolutions = caps.resolutions ?? [];
    const formats = scanner.formats ?? ["pdf"];
    const field = (name) => this.shadowRoot.querySelector(`[data-scan="${name}"]`);
    this._setOptions(
      this._role("scan-source"),
      sources,
      (v) => scanOptionLabel(lang, "source", v),
      source,
    );
    field("source").hidden = sources.length < 2;
    this._setOptions(
      this._role("scan-color"),
      colors,
      (v) => scanColorLabel(lang, v, colors),
      pick(colors, this._role("scan-color").value, defaults.color_mode),
    );
    this._setOptions(
      this._role("scan-resolution"),
      resolutions,
      (v) => scanOptionLabel(lang, "resolution", v),
      pick(resolutions, this._role("scan-resolution").value, defaults.resolution),
    );
    this._setOptions(
      this._role("scan-format"),
      formats,
      (v) => scanOptionLabel(lang, "format", v),
      pick(formats, this._role("scan-format").value, defaults.format),
    );
  }

  _renderScan(lang, printer) {
    const scanner = printer?.scanner ?? null;
    const id = scanner ? printer.entry_id : null;
    if (id !== this._scanAppliedId) {
      this._resetScan();
      this._scanAppliedId = id;
      if (scanner) this._fillScanSelects(lang, scanner, true);
    } else if (scanner) {
      this._fillScanSelects(lang, scanner, false);
    }
    const editable = printer?.can_print !== false;
    if (scanner) this._resumeScan(printer);
    // No scanner: no tabs, only the print content.
    if (!scanner || !editable) this._tab = "print";
    const open = this._tab === "scan";
    this._role("body-tabs").hidden = !scanner;
    const scanTab = this._role("body-tab-scan");
    scanTab.disabled = !editable;
    for (const tab of this._bodyTabs()) {
      const selected = tab.dataset.bodyTab === this._tab;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
    const printPanel = this._role("print-panel");
    const scanPanel = this._role("scan-panel");
    printPanel.hidden = open;
    scanPanel.hidden = !open;
    for (const [panel, tab] of [
      [printPanel, "body-tab-print"],
      [scanPanel, "body-tab-scan"],
    ]) {
      if (scanner) {
        panel.setAttribute("role", "tabpanel");
        panel.setAttribute("aria-labelledby", tab);
      } else {
        panel.removeAttribute("role");
        panel.removeAttribute("aria-labelledby");
      }
    }
    if (!scanner) return;

    const busy = this._scanBusy();
    const offline = scanner.available === false;
    this._role("scan-start").disabled = busy || !editable || offline;
    const cancel = this._role("scan-cancel");
    cancel.hidden = !busy || !editable;
    cancel.disabled = !this._scan?.scanId || Boolean(this._scan?.canceling);
    for (const name of SCAN_SELECTS) this._role(name).disabled = busy;
    const message = this._role("scan-message");
    let shown = this._scanMessage;
    if (!shown && offline) {
      shown = { text: scanErrorText(lang, "scanner_unavailable"), kind: "error" };
    }
    message.textContent = shown?.text ?? "";
    message.className = `message ${shown?.kind ?? ""}`.trim();

    const result = this._scanResult;
    this._role("scan-result").hidden = !result;
    if (!result) return;
    const record = result.record;
    const total = Math.max(1, Number(record.pages) || 1);
    this._role("scan-nav").hidden = total <= 1;
    this._role("scan-page-label").textContent = t(lang, "scan_page_of", { n: result.page, total });
    this._role("scan-prev").disabled = result.page <= 1;
    this._role("scan-next").disabled = result.page >= total;
    this._role("scan-name").disabled = busy || !editable;
    const add = this._role("scan-add");
    add.hidden = !editable || record.mime !== "application/pdf" || record.source !== "platen";
    add.disabled = busy;
    const remove = this._role("scan-delete");
    remove.hidden = !editable;
    remove.disabled = busy || result.deleting;
  }
}
