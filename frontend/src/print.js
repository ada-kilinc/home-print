// Print tab: file picker, options, upload and job tracking.

import {
  FATAL_JOB_ERRORS,
  FILE_INPUTS,
  PAGE_RANGES_RE,
  POLL_LIMIT_MS,
  POLL_MS,
  PRINTER_ERROR_LIMIT,
  RUNNING_JOB_STATES,
  STALL_MS,
  UPLOAD_TIMEOUT_MS,
} from "./constants.js";
import {
  buildForm,
  fileFormat,
  formatSize,
  isAuthError,
  isProblemState,
  jobLabel,
  twoSided,
  usesPickMenu,
  validateFile,
  visibleRawReasons,
} from "./helpers.js";
import { pickLanguage, t } from "./i18n.js";
import { markerBackground } from "./icons.js";

export class PrintPart {
  _fileCheck(printer) {
    return this._file ? validateFile(this._file, printer) : null;
  }

  // A running job holds the Print button, unless its status has been out of
  // reach for longer than STALL_MS.
  _jobHolds(printer) {
    const job = this._job;
    if (!job || job.entryId !== printer?.entry_id) return false;
    return job.troubleSince === null || Date.now() - job.troubleSince <= STALL_MS;
  }

  _canSubmit(printer) {
    return (
      !this._uploading &&
      !this._jobHolds(printer) &&
      Boolean(printer) &&
      this._reachable(printer) &&
      printer.can_print !== false &&
      this._fileCheck(printer)?.ok === true
    );
  }

  _onFile(ev) {
    this._file = ev.target.files?.[0] ?? null;
    // Only the input just used holds a file, so any picker fires "change"
    // again for the same file later.
    for (const name of FILE_INPUTS) {
      const input = this._role(name);
      if (input !== ev.target) input.value = "";
    }
    if (!this._uploading && !this._job) this._message = null;
    this._update();
  }

  _onPickButton() {
    // iOS offers Photo Library / Take Photo / Choose File itself; desktops
    // just get the file dialog. Decided per click: a mouse may be plugged in.
    if (!usesPickMenu(globalThis.navigator, globalThis)) {
      if (!this._role("pick-menu").hidden) this._closeMenu();
      this._openInput("input-file");
      return;
    }
    if (this._role("pick-menu").hidden) this._openMenu();
    else this._closeMenu();
  }

  _onPickOption(option) {
    this._closeMenu();
    this._openInput(`input-${option}`);
  }

  _openInput(name) {
    const input = this._role(name);
    if (!input) return;
    // Cleared first, so picking the file already chosen still fires "change".
    input.value = "";
    input.click();
  }

  _openMenu() {
    this._role("pick-menu").hidden = false;
    this._role("pick").setAttribute("aria-expanded", "true");
    document.addEventListener("click", this._onDocumentClick, true);
    this._menuItems()[0]?.focus();
  }

  _menuItems() {
    return [...this.shadowRoot.querySelectorAll("[data-option]")];
  }

  _onMenuKey(ev) {
    if (ev.key === "Escape") {
      ev.preventDefault();
      this._closeMenu(true);
      return;
    }
    const step = { ArrowDown: 1, ArrowUp: -1 }[ev.key];
    if (!step) return;
    ev.preventDefault();
    const items = this._menuItems();
    const index = items.indexOf(this.shadowRoot.activeElement);
    items[(index + step + items.length) % items.length].focus();
  }

  _closeMenu(focusButton = false) {
    const menu = this._role("pick-menu");
    document.removeEventListener("click", this._onDocumentClick, true);
    if (menu.hidden) return;
    menu.hidden = true;
    this._role("pick").setAttribute("aria-expanded", "false");
    if (focusButton) this._role("pick").focus();
  }

  // Tab (or any focus move) to something outside the menu closes it. A null
  // relatedTarget is left to the outside-click handler: Safari doesn't focus
  // tapped buttons, so closing here would swallow the tap on an option.
  _onMenuFocusOut(ev) {
    const next = ev.relatedTarget;
    if (!next || this._role("pick-menu").hidden) return;
    if (this._role("pick-menu").contains(next) || next === this._role("pick")) return;
    this._closeMenu();
  }

  _closeMenuOutside(ev) {
    const path = ev.composedPath();
    if (path.includes(this._role("pick-menu")) || path.includes(this._role("pick"))) return;
    this._closeMenu();
  }

  async _onPrint() {
    const printer = this._printer();
    if (!this._canSubmit(printer)) return;
    const lang = pickLanguage(this._hass);
    const pages = this._optionShown("pages") ? this._role("pages").value.trim() : "";
    if (pages && !PAGE_RANGES_RE.test(pages)) {
      this._setMessage(t(lang, "bad_pages"), "error");
      return;
    }

    // A new upload replaces any job still being followed.
    clearTimeout(this._pollTimer);
    this._pollTimer = null;
    this._job = null;
    this._uploading = true;
    const entryId = printer.entry_id;
    this._uploadEntryId = entryId;
    this._setMessage(t(lang, "uploading"));
    const form = buildForm(this._file, { ...this._options(printer), page_ranges: pages });

    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
    let response;
    let body = null;
    try {
      response = await this._hass.fetchWithAuth(
        `/api/home_print/upload/${encodeURIComponent(entryId)}`,
        { method: "POST", body: form, signal: controller.signal },
      );
      if (response.status !== 401) {
        try {
          body = await response.json();
        } catch (_err) {
          body = null;
        }
      }
    } catch (err) {
      let key = "network_error";
      if (controller.signal.aborted) key = "upload_timeout";
      else if (isAuthError(err, this._hass)) key = "session_expired";
      this._finish(t(lang, key), "error");
      return;
    } finally {
      clearTimeout(abortTimer);
    }
    if (controller.signal.aborted) {
      this._finish(t(lang, "upload_timeout"), "error");
      return;
    }
    if (response.status === 401) {
      this._finish(t(lang, "session_expired"), "error");
      return;
    }
    if (!response.ok || body?.job_id === undefined || body?.job_id === null) {
      const text =
        typeof body?.message === "string" && body.message
          ? body.message
          : t(lang, "upload_failed", { status: response.status });
      this._finish(text, "error");
      return;
    }

    // The upload is confirmed: follow the job, which holds the button, and
    // clear the picked file so choosing the same one again fires "change".
    this._uploading = false;
    this._uploadEntryId = null;
    this._file = null;
    for (const name of FILE_INPUTS) this._role(name).value = "";
    this._job = {
      entryId,
      jobId: body.job_id,
      started: Date.now(),
      printerErrors: 0,
      troubleSince: null,
      twoSided: String(form.get("sides") ?? printer.defaults?.sides ?? "").startsWith("two-sided"),
    };
    this._setMessage(jobLabel(lang, { state: "pending" }));
    this._schedulePoll();
    // The new record is at the top of the history now.
    if (this._historyEntryId === entryId) this._loadHistory();
  }

  _options(printer) {
    const caps = printer.capabilities ?? {};
    const options = {};
    if (this._optionShown("copies")) {
      const max = Math.max(1, Number(caps.copies_max) || 1);
      const copies = parseInt(this._role("copies").value, 10);
      options.copies = Math.min(max, Math.max(1, Number.isNaN(copies) ? 1 : copies));
    }
    if (this._optionShown("duplex")) {
      options.sides = this._role("duplex").checked ? twoSided(printer) : "one-sided";
    }
    if (this._optionShown("color")) {
      options.color_mode = this._role("color").checked ? "color" : "monochrome";
    }
    return options;
  }

  _schedulePoll() {
    clearTimeout(this._pollTimer);
    this._pollTimer = setTimeout(() => {
      this._pollTimer = null;
      this._poll();
    }, POLL_MS);
  }

  async _poll() {
    const job = this._job;
    if (!job || !this._hass) return;
    const lang = pickLanguage(this._hass);
    if (Date.now() - job.started >= POLL_LIMIT_MS) {
      this._finish(t(lang, "job_timeout"), "warning");
      return;
    }
    let status;
    try {
      status = (
        await this._hass.callWS({
          type: "home_print/job",
          entry_id: job.entryId,
          job_id: job.jobId,
        })
      )?.job;
    } catch (err) {
      if (this._job !== job) return;
      if (FATAL_JOB_ERRORS.includes(err?.code)) {
        this._finish(t(lang, "job_lost"), "error");
        return;
      }
      if (err?.code === "job_gone") {
        this._finish(t(lang, "job_gone"));
        return;
      }
      if (err?.code === "printer_error") {
        job.printerErrors += 1;
        if (job.printerErrors >= PRINTER_ERROR_LIMIT) {
          this._finish(t(lang, "job_status_failed"), "error");
          return;
        }
      } else {
        job.printerErrors = 0;
        job.troubleSince ??= Date.now();
      }
      // printer_unavailable, a dropped connection, an occasional printer_error.
      this._setMessage(t(lang, "job_checking"));
      if (this.isConnected) this._schedulePoll();
      return;
    }
    if (this._job !== job) return;
    job.printerErrors = 0;
    job.troubleSince = null;
    const label = jobLabel(lang, status, { twoSided: job.twoSided });
    if (RUNNING_JOB_STATES.includes(status?.state)) {
      this._setMessage(
        label,
        isProblemState(status, lang) ? "error" : "info",
        visibleRawReasons(status.reasons).join(", "),
      );
      if (this.isConnected) this._schedulePoll();
      return;
    }
    if (status?.state === "completed") this._finish(label, "success");
    else if (status?.state === "canceled" || status?.state === "aborted") {
      this._finish(label, "error", visibleRawReasons(status.reasons).join(", "));
    } else {
      this._setMessage(t(lang, "job_checking"));
      if (this.isConnected) this._schedulePoll();
      return;
    }
    // The server has recorded the final state; show it in an open history.
    if (this._historyEntryId === job.entryId) this._loadHistory();
  }

  _finish(text, kind, detail = "") {
    const entryId = this._messageEntryId();
    clearTimeout(this._pollTimer);
    this._pollTimer = null;
    this._job = null;
    this._uploading = false;
    this._uploadEntryId = null;
    this._setMessage(text, kind, detail, entryId);
  }

  // The printer a print message is about: the job's or upload's printer,
  // else the one shown. Only that printer shows it.
  _messageEntryId() {
    return this._job?.entryId ?? this._uploadEntryId ?? this._printer()?.entry_id ?? null;
  }

  _setMessage(text, kind = "info", detail = "", entryId = this._messageEntryId()) {
    this._message = { text, kind, detail, entryId };
    this._update();
  }

  _applyPrinter(printer) {
    // Reset the form to the printer's defaults when the printer changes.
    const id = printer?.entry_id ?? null;
    if (id === this._appliedId) return;
    this._appliedId = id;
    if (!printer) return;
    const caps = printer.capabilities ?? {};
    const defaults = printer.defaults ?? {};
    this._role("copies").value = "1";
    this._role("duplex").checked = String(defaults.sides ?? "").startsWith("two-sided");
    this._role("color").checked = defaults.color_mode === "color";
    this._role("pages").value = "";
  }

  _renderOptions(printer) {
    const caps = printer?.capabilities ?? null;
    const copiesMax = Number(caps?.copies_max) || 0;
    this._row("copies").hidden = copiesMax <= 1;
    this._role("copies").max = String(Math.max(1, copiesMax));
    this._row("duplex").hidden = !(caps?.sides ?? []).some((s) => s.startsWith("two-sided"));
    // Only a real choice is shown: without both modes the printer's own
    // default applies and no color_mode is sent.
    const modes = caps?.color_modes ?? [];
    this._row("color").hidden = !(modes.includes("color") && modes.includes("monochrome"));
    this._role("options").hidden = this._row("duplex").hidden && this._row("color").hidden;
    const format = this._file ? fileFormat(this._file) : "application/pdf";
    const pdfOk = (caps?.formats ?? []).includes("application/pdf");
    // PDFs always take a page range (conversion selects the pages); images
    // only when the printer accepts page-ranges for passthrough.
    this._row("pages").hidden =
      !caps || (format === "application/pdf" ? !pdfOk : !caps.page_ranges_passthrough);
  }

  _renderFile(lang, printer) {
    this._role("file-name").textContent = this._file ? this._file.name : "";
    this._role("file-size").textContent = this._file ? formatSize(this._file.size, lang) : "";
    this._role("file-info").hidden = !this._file;
    const message = this._role("message");
    const check = this._fileCheck(printer);
    let shown = this._message;
    if (shown?.entryId && shown.entryId !== printer?.entry_id) shown = null;
    if (!shown && check && !check.ok) {
      shown = { text: t(lang, check.key, { mb: printer?.max_file_mb }), kind: "error" };
    }
    message.textContent = shown?.text ?? "";
    message.className = `message ${shown?.kind ?? ""}`.trim();
    const detail = this._role("detail");
    detail.textContent = shown?.detail ?? "";
    detail.hidden = !shown?.detail;
  }

  _renderInk(lang, printer) {
    const ink = this._role("ink");
    const markers = [];
    if (this._config.show_ink && printer) {
      for (const entityId of printer.entities?.markers ?? []) {
        const entity = this._entityState(entityId);
        const level = Number.parseFloat(entity?.state);
        if (!entity || Number.isNaN(level)) continue;
        markers.push({
          entityId,
          level: Math.min(100, Math.max(0, level)),
          attrs: entity.attributes ?? {},
        });
      }
    }
    ink.hidden = markers.length === 0;
    ink.replaceChildren(
      ...markers.map(({ entityId, level, attrs }) => {
        const colors = String(attrs.color ?? "").match(/#[0-9a-fA-F]{6}/g) ?? [];
        let label = attrs.friendly_name ?? entityId;
        if (colors.length > 1) label = t(lang, "ink_color");
        else if (colors[0]?.toLowerCase() === "#000000") label = t(lang, "ink_black");

        const row = document.createElement("div");
        row.className = "marker";
        row.dataset.role = "marker";
        const name = document.createElement("span");
        name.textContent = label;
        const bar = document.createElement("span");
        bar.className = "bar";
        const fill = document.createElement("span");
        fill.className = "bar-fill";
        fill.style.display = "block";
        fill.style.width = `${level}%`;
        fill.style.background = markerBackground(attrs.color);
        bar.append(fill);
        const pct = document.createElement("span");
        pct.className = "pct";
        pct.textContent = t(lang, "percent", { value: Math.round(level) });
        row.append(name, bar, pct);
        return row;
      }),
    );
  }
}
