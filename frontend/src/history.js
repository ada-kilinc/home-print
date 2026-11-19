// History and preview dialogs (prints and scans).

import {
  HISTORY_STATES,
  PREVIEW_MARGIN,
  PREVIEW_RESIGN_MS,
  PREVIEW_SIGN_SECONDS,
} from "./constants.js";
import { formatHistoryTime, historyStateIcon, previewPath, scanPagePath } from "./helpers.js";
import { pickLanguage, t } from "./i18n.js";
import { svgIcon } from "./icons.js";

export class HistoryPart {
  _wireDialog(dialog, close) {
    // A tap on the dialog itself (not its sheet) is a tap on the backdrop.
    dialog.addEventListener("click", (ev) => {
      if (ev.target === dialog) close();
    });
    dialog.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      ev.preventDefault();
      ev.stopPropagation();
      close();
    });
    // The browser's own Escape handling; keep our state in step with it.
    dialog.addEventListener("cancel", (ev) => {
      ev.preventDefault();
      close();
    });
  }

  _anyDialogOpen() {
    return ["history-dialog", "preview-dialog", "crop-dialog"].some(
      (name) => this._role(name).open,
    );
  }

  _showDialog(dialog) {
    if (dialog.open) return;
    // The page behind stays put while a dialog is open.
    if (this._savedOverflow === null) {
      const root = document.documentElement;
      this._savedOverflow = root.style.overflow;
      root.style.overflow = "hidden";
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  _hideDialog(dialog) {
    if (dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
    if (this._savedOverflow !== null && !this._anyDialogOpen()) {
      document.documentElement.style.overflow = this._savedOverflow;
      this._savedOverflow = null;
    }
  }

  _openHistory() {
    const printer = this._printer();
    if (!printer) return;
    this._historyEntryId = printer.entry_id;
    // A scanner without a printer has only scans; without a scanner there
    // are only prints. Either way: no tabs, and the list is no tab panel.
    const scannerOnly = printer.kind === "scanner";
    this._historyTab = scannerOnly ? "scans" : "prints";
    const tabbed = Boolean(printer.scanner) && !scannerOnly;
    this._role("history-tabs").hidden = !tabbed;
    const panel = this._role("history-panel");
    if (tabbed) panel.setAttribute("role", "tabpanel");
    else panel.removeAttribute("role");
    this._historyEntries = [];
    this._deletedIds = new Set();
    this._renderHistory({ key: "history_loading" });
    this._showDialog(this._role("history-dialog"));
    this._loadHistory();
  }

  _closeHistory() {
    this._closeCrop();
    this._closePreview();
    this._historyEntryId = null;
    this._historyToken += 1;
    this._hideDialog(this._role("history-dialog"));
  }

  _switchHistoryTab(tab) {
    if (!this._historyEntryId || tab === this._historyTab) return;
    this._closePreview();
    this._historyTab = tab;
    this._historyEntries = [];
    this._deletedIds = new Set();
    this._renderHistory({ key: "history_loading" });
    this._loadHistory();
  }

  _onTabKey(ev) {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[ev.key];
    if (!step) return;
    ev.preventDefault();
    const tabs = [...this._role("history-tabs").querySelectorAll('[role="tab"]')];
    const index = tabs.findIndex((tab) => tab.dataset.tab === this._historyTab);
    const next = tabs[(index + step + tabs.length) % tabs.length];
    this._switchHistoryTab(next.dataset.tab);
    next.focus();
  }

  async _loadHistory() {
    const entryId = this._historyEntryId;
    if (!entryId || !this._hass) return;
    const token = ++this._historyToken;
    const type = this._historyTab === "scans" ? "home_print/scans" : "home_print/history";
    let result;
    try {
      result = await this._hass.callWS({ type, entry_id: entryId });
    } catch (_err) {
      if (token !== this._historyToken) return;
      // Keep rows already shown; a reload that fails only says so.
      this._renderHistory({ key: "history_failed", error: true });
      return;
    }
    if (token !== this._historyToken) return;
    const entries = Array.isArray(result?.entries) ? result.entries : [];
    // A reload sent before a delete finished may still list the record.
    this._historyEntries = entries.filter((e) => !this._deletedIds.has(e.id));
    this._renderHistory();
  }

  async _deleteHistory(record, button) {
    const entryId = this._historyEntryId;
    if (!entryId) return;
    const scans = this._historyTab === "scans";
    button.disabled = true;
    try {
      await this._hass.callWS(
        scans
          ? { type: "home_print/scans/delete", entry_id: entryId, scan_record_id: record.id }
          : { type: "home_print/history/delete", entry_id: entryId, history_id: record.id },
      );
    } catch (err) {
      button.disabled = false;
      if (this._historyEntryId !== entryId || this._historyTab !== (scans ? "scans" : "prints")) {
        return;
      }
      const key = err?.code === "unauthorized" ? "delete_not_allowed" : "delete_failed";
      this._renderHistory({ key, error: true });
      return;
    }
    if (scans && this._scanResult?.record.id === record.id) {
      this._clearScanResult();
      this._update();
    }
    if (this._historyEntryId !== entryId) return;
    // The tab changed meanwhile: its rows are another list.
    if (this._historyTab !== (scans ? "scans" : "prints")) return;
    // {"deleted": false} means it was already gone; either way the row goes.
    this._deletedIds.add(record.id);
    const index = this._historyEntries.findIndex((e) => e.id === record.id);
    this._historyEntries = this._historyEntries.filter((e) => e.id !== record.id);
    this._renderHistory();
    // Focus moves on to the row that took its place, else to the close button.
    const rows = this._role("history-list").querySelectorAll(
      '[data-role="history-delete"], [data-role="scan-row-delete"]',
    );
    (rows[Math.max(index, 0)] ?? this._role("history-close")).focus();
  }

  _renderHistory(status = null) {
    const lang = pickLanguage(this._hass);
    const entries = this._historyEntries;
    const scans = this._historyTab === "scans";
    for (const tab of this.shadowRoot.querySelectorAll('[role="tab"]')) {
      const selected = tab.dataset.tab === this._historyTab;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected) this._role("history-panel").setAttribute("aria-labelledby", tab.id);
    }
    const empty = scans ? "scans_empty" : "history_empty";
    const shown = status ?? (entries.length === 0 ? { key: empty } : null);
    const statusEl = this._role("history-status");
    statusEl.textContent = shown ? t(lang, shown.key) : "";
    statusEl.hidden = !shown;
    statusEl.classList.toggle("error", Boolean(shown?.error));
    const canDelete = this._printer()?.can_print !== false;
    this._role("history-list").replaceChildren(
      ...entries.map((record) =>
        scans ? this._scanRow(lang, record, canDelete) : this._historyRow(lang, record, canDelete),
      ),
    );
  }

  _historyRow(lang, record, canDelete) {
    const row = document.createElement("li");
    row.className = "history-item";
    row.dataset.role = "history-item";

    // A record without a MIME type never had a file (a failed job, or files
    // not kept at all): nothing to preview, so the row is not a button.
    const hadFile = Boolean(record.mime);
    const open = document.createElement(hadFile ? "button" : "div");
    open.className = hadFile ? "history-open" : "history-open static";
    open.dataset.role = "history-open";
    if (hadFile) {
      open.type = "button";
      open.addEventListener("click", () => {
        const entryId = this._historyEntryId;
        this._openPreview({
          title: record.file_name,
          gone: record.file === false,
          isImage: String(record.mime ?? "").startsWith("image/"),
          pages: record.pages,
          pagePath: (page) => previewPath(entryId, record.id, page),
        });
      });
    }

    const state = HISTORY_STATES.includes(record.state) ? record.state : "sent";
    const icon = historyStateIcon(state);
    const mark = document.createElement("span");
    mark.className = `history-mark ${icon === "✓" ? "ok" : icon === "✗" ? "bad" : "busy"}`;
    mark.textContent = icon;
    mark.title = t(lang, `history_state_${state}`);
    mark.setAttribute("role", "img");
    mark.setAttribute("aria-label", mark.title);

    const textBox = document.createElement("span");
    textBox.className = "history-text";
    const name = document.createElement("span");
    name.className = "history-name";
    name.dataset.role = "history-name";
    name.textContent = String(record.file_name ?? "");
    name.title = name.textContent;
    const meta = this._recordMeta(lang, record);
    if (hadFile && record.file === false) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = t(lang, "file_gone_tag");
      meta.append(tag);
    }
    textBox.append(name, meta);
    open.append(mark, textBox);
    row.append(open);

    if (canDelete) {
      const trash = document.createElement("button");
      trash.type = "button";
      trash.className = "icon-button";
      trash.dataset.role = "history-delete";
      trash.setAttribute("aria-label", t(lang, "delete"));
      trash.title = t(lang, "delete");
      trash.append(svgIcon("delete"));
      trash.addEventListener("click", () => this._deleteHistory(record, trash));
      row.append(trash);
    }
    return row;
  }

  _recordMeta(lang, record) {
    const meta = document.createElement("span");
    meta.className = "history-meta";
    const pages = Number(record.pages);
    const parts = [
      formatHistoryTime(this._timeLanguage(), record.time),
      record.user ? String(record.user) : "",
      pages > 0 ? t(lang, pages === 1 ? "history_pages_one" : "history_pages", { n: pages }) : "",
    ].filter(Boolean);
    for (const part of parts) {
      const span = document.createElement("span");
      span.textContent = part;
      meta.append(span);
    }
    return meta;
  }

  // One row of the Scans tab: tap to preview, download, delete (asks once).
  _scanRow(lang, record, canDelete) {
    const entryId = this._historyEntryId;
    const row = document.createElement("li");
    row.className = "history-item";
    row.dataset.role = "scan-item";

    const open = document.createElement("button");
    open.type = "button";
    open.className = "history-open";
    open.dataset.role = "scan-open";
    open.addEventListener("click", () =>
      this._openPreview({
        title: record.name,
        gone: false,
        isImage: String(record.mime ?? "").startsWith("image/"),
        pages: record.pages,
        pagePath: (page) => scanPagePath(entryId, record.id, page),
        // Cropping is for whoever may change scans.
        crop: canDelete ? { entryId, record } : null,
      }),
    );
    const mark = document.createElement("span");
    mark.className = "history-mark";
    mark.append(svgIcon("scanner"));
    const textBox = document.createElement("span");
    textBox.className = "history-text";
    const name = document.createElement("span");
    name.className = "history-name";
    name.dataset.role = "history-name";
    name.textContent = String(record.name ?? "");
    name.title = name.textContent;
    textBox.append(name, this._recordMeta(lang, record));
    open.append(mark, textBox);
    row.append(open);

    const download = this._iconButton(lang, "download", "scan_download", "scan-row-download");
    download.addEventListener("click", async () => {
      if (!(await this._downloadScan(entryId, record)) && this._historyEntryId === entryId) {
        this._renderHistory({ key: "download_failed", error: true });
      }
    });
    row.append(download);
    if (canDelete) {
      const trash = this._iconButton(lang, "delete", "delete", "scan-row-delete");
      trash.addEventListener("click", () =>
        this._confirmTap(trash, () => this._deleteHistory(record, trash)),
      );
      row.append(trash);
    }
    return row;
  }

  _iconButton(lang, icon, label, roleName) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button";
    button.dataset.role = roleName;
    button.setAttribute("aria-label", t(lang, label));
    button.title = t(lang, label);
    button.append(svgIcon(icon));
    return button;
  }

  _timeLanguage() {
    return String(this._hass?.locale?.language ?? this._hass?.language ?? "en");
  }

  // Pages are signed just before they load: a signed path lives 300 s, and a
  // request with an expired one is a 401 that HA counts as a failed login.
  //
  // `spec`: {title, gone, isImage, pages, pagePath(page) -> unsigned path},
  // so print history and scans share the same viewer.
  _openPreview(spec) {
    if (!this._historyEntryId) return;
    this._stopPreview();
    const lang = pickLanguage(this._hass);
    this._role("preview-title").textContent = String(spec.title ?? "");
    const body = this._role("preview-body");
    body.replaceChildren();
    body.scrollTop = 0;
    this._showDialog(this._role("preview-dialog"));
    if (spec.gone) {
      this._previewNote(body, t(lang, "file_gone"));
      return;
    }
    const known = Number(spec.pages) > 0 ? Number(spec.pages) : null;
    const preview = {
      token: this._previewToken,
      body,
      lang,
      pagePath: spec.pagePath,
      crop: spec.crop ?? null,
      // null: unknown, pages are added one by one until one is missing.
      count: spec.isImage ? 1 : known,
      observer: null,
    };
    this._preview = preview;
    const Observer = globalThis.IntersectionObserver;
    if (typeof Observer === "function") {
      preview.observer = new Observer(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            preview.observer?.unobserve(entry.target);
            this._loadPage(preview, entry.target);
          }
        },
        { root: body, rootMargin: PREVIEW_MARGIN },
      );
    }
    const first = preview.count ?? 1;
    for (let page = 1; page <= first; page += 1) this._addPlaceholder(preview, page);
    // Without an observer, pages load in turn, each after the one before.
    if (!preview.observer) this._loadPage(preview, body.querySelector("[data-page]"));
  }

  _addPlaceholder(preview, page) {
    const box = document.createElement("div");
    box.className = "page";
    box.dataset.page = String(page);
    preview.body.append(box);
    preview.observer?.observe(box);
    return box;
  }

  _signPage(preview, page) {
    return this._signPath(preview.pagePath(page));
  }

  async _signPath(path, expires = PREVIEW_SIGN_SECONDS) {
    const result = await this._hass.callWS({ type: "auth/sign_path", path, expires });
    return String(result?.path ?? "");
  }

  async _loadPage(preview, box) {
    if (!box || box.dataset.state) return;
    box.dataset.state = "loading";
    const live = () => preview.token === this._previewToken && box.isConnected;
    const page = Number(box.dataset.page);
    let path;
    try {
      // A signature that got old while waiting is never used.
      let signedAt;
      do {
        signedAt = Date.now();
        path = await this._signPage(preview, page);
        if (!live()) return;
      } while (Date.now() - signedAt > PREVIEW_RESIGN_MS);
    } catch (_err) {
      if (!live()) return;
      this._stopPreview();
      this._previewNote(preview.body, t(preview.lang, "preview_failed"));
      return;
    }
    const img = document.createElement("img");
    img.alt = t(preview.lang, "preview_page", { n: page });
    img.addEventListener("load", () => {
      if (!live()) return;
      box.classList.add("loaded");
      if (preview.crop) box.append(this._pageCropButton(preview, box, page));
      const next = page + 1;
      const more = preview.count === null || next <= preview.count;
      if (!more) return;
      let nextBox = preview.body.querySelector(`[data-page="${next}"]`);
      if (!nextBox) nextBox = this._addPlaceholder(preview, next);
      if (!preview.observer) this._loadPage(preview, nextBox);
    });
    img.addEventListener("error", () => {
      if (!live()) return;
      // The path was signed a moment ago, so a later page of an unknown count
      // that fails is past the end of the document.
      if (preview.count === null && page > 1) box.remove();
      else box.replaceChildren(this._previewNote(null, t(preview.lang, "preview_failed")));
    });
    img.src = path;
    box.append(img);
  }

  // A crop button on a scan's preview page; after cropping the page reloads.
  _pageCropButton(preview, box, page) {
    const button = this._iconButton(preview.lang, "crop", "crop", "page-crop");
    button.classList.add("page-crop");
    button.addEventListener("click", () => {
      const { entryId, record } = preview.crop;
      this._openCrop({
        entryId,
        record,
        page,
        onDone: (updated, cropped) => {
          preview.crop = { entryId, record: updated };
          this._reloadScans(entryId);
          if (preview.token !== this._previewToken) return;
          // The page cropped may be another one than this button's.
          const target = preview.body.querySelector(`[data-page="${cropped}"]`);
          if (!target?.isConnected) return;
          delete target.dataset.state;
          target.classList.remove("loaded");
          target.replaceChildren();
          this._loadPage(preview, target);
        },
      });
    });
    return button;
  }

  _previewNote(body, text) {
    const note = document.createElement("div");
    note.className = "sheet-status";
    note.textContent = text;
    if (body) body.replaceChildren(note);
    return note;
  }

  _stopPreview() {
    this._previewToken += 1;
    this._preview?.observer?.disconnect();
    this._preview = null;
  }

  _closePreview() {
    this._stopPreview();
    this._hideDialog(this._role("preview-dialog"));
    this._role("preview-body").replaceChildren();
  }
}
