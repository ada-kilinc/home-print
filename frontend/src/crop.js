// Crop dialog: a frame with four corner handles over one scanned page.

import { CROP_DETECT_SIZE, CROP_KEY_STEP, CROP_KEY_STEP_BIG } from "./constants.js";
import {
  clampCropBox,
  detectPaper,
  moveCropCorner,
  scanErrorText,
  scanPagePath,
} from "./helpers.js";
import { pickLanguage, t } from "./i18n.js";

const FULL_PAGE = Object.freeze({ x: 0, y: 0, width: 1, height: 1 });

export class CropPart {
  // spec: { entryId, record, page, onDone(record) }
  _openCrop(spec) {
    this._closeCrop();
    const lang = pickLanguage(this._hass);
    const crop = {
      spec,
      lang,
      token: ++this._cropToken,
      box: { ...FULL_PAGE },
      found: false,
      drag: null,
      saving: false,
    };
    this._crop = crop;
    this._role("crop-title").textContent = t(lang, "crop_title", { n: spec.page });
    this._role("crop-frame").hidden = true;
    this._setCropStatus(t(lang, "history_loading"));
    this._renderCropButtons();
    this._showDialog(this._role("crop-dialog"));
    this._loadCropImage(crop);
  }

  async _loadCropImage(crop) {
    const { spec, lang } = crop;
    let path;
    try {
      path = await this._signPath(scanPagePath(spec.entryId, spec.record.id, spec.page));
    } catch (_err) {
      if (crop === this._crop) this._setCropStatus(t(lang, "preview_failed"), true);
      return;
    }
    if (crop !== this._crop) return;
    // A fresh image each time, so a late load of the previous one is ignored.
    const img = document.createElement("img");
    img.dataset.role = "crop-img";
    img.draggable = false;
    img.alt = t(lang, "preview_page", { n: spec.page });
    this._role("crop-img")?.remove();
    this._role("crop-stage").prepend(img);
    img.onload = () => {
      if (crop !== this._crop) return;
      const found = this._findPaper(img);
      crop.found = Boolean(found);
      crop.box = found ?? { ...FULL_PAGE };
      this._role("crop-frame").hidden = false;
      this._setCropStatus(t(lang, found ? "crop_found" : "crop_hint"));
      this._renderCrop();
    };
    img.onerror = () => {
      if (crop === this._crop) this._setCropStatus(t(lang, "preview_failed"), true);
    };
    img.src = path;
  }

  // The paper's edges, found on a small copy of the page; null if the
  // browser can't read the pixels.
  _findPaper(img) {
    const width = img.naturalWidth;
    const height = img.naturalHeight;
    if (!width || !height) return null;
    const scale = Math.min(1, CROP_DETECT_SIZE / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    try {
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      if (!ctx) return null;
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return detectPaper(ctx.getImageData(0, 0, canvas.width, canvas.height));
    } catch (_err) {
      return null;
    }
  }

  _renderCrop() {
    const crop = this._crop;
    if (!crop) return;
    const frame = this._role("crop-frame");
    const { x, y, width, height } = crop.box;
    frame.style.left = `${x * 100}%`;
    frame.style.top = `${y * 100}%`;
    frame.style.width = `${width * 100}%`;
    frame.style.height = `${height * 100}%`;
    this._renderCropButtons();
  }

  _renderCropButtons() {
    const crop = this._crop;
    const ready = Boolean(crop) && !this._role("crop-frame").hidden;
    const whole = !crop || isFullPage(crop.box);
    this._role("crop-save").disabled = !ready || crop.saving || whole;
    this._role("crop-full").disabled = !ready || crop.saving || whole;
    this._role("crop-cancel").disabled = Boolean(crop?.saving);
  }

  _setCropStatus(text, error = false) {
    const status = this._role("crop-status");
    status.textContent = text;
    status.classList.toggle("error", error);
  }

  // ---- pointer: drag a corner, or the frame itself to move it

  _onCropPointerDown(ev) {
    const crop = this._crop;
    if (!crop || crop.saving || ev.button > 0) return;
    const corner = ev.target.closest?.("[data-corner]")?.dataset.corner ?? null;
    if (!corner && !ev.target.closest?.('[data-role="crop-frame"]')) return;
    ev.preventDefault();
    const rect = this._role("crop-img")?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return;
    crop.drag = {
      id: ev.pointerId,
      corner,
      startX: ev.clientX,
      startY: ev.clientY,
      startBox: { ...crop.box },
      width: rect.width,
      height: rect.height,
    };
    ev.target.setPointerCapture?.(ev.pointerId);
  }

  _onCropPointerMove(ev) {
    const drag = this._crop?.drag;
    if (!drag || drag.id !== ev.pointerId) return;
    ev.preventDefault();
    const dx = (ev.clientX - drag.startX) / drag.width;
    const dy = (ev.clientY - drag.startY) / drag.height;
    this._crop.box = drag.corner
      ? moveCropCorner(drag.startBox, drag.corner, dx, dy)
      : clampCropBox({ ...drag.startBox, x: drag.startBox.x + dx, y: drag.startBox.y + dy });
    this._renderCrop();
  }

  _onCropPointerUp(ev) {
    const crop = this._crop;
    if (!crop?.drag || crop.drag.id !== ev.pointerId) return;
    crop.drag = null;
  }

  // ---- keyboard: arrows move the focused corner, or the whole frame

  _onCropKey(ev) {
    const crop = this._crop;
    if (!crop || crop.saving) return;
    const step = ev.shiftKey ? CROP_KEY_STEP_BIG : CROP_KEY_STEP;
    const moves = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    };
    const move = moves[ev.key];
    if (!move) return;
    ev.preventDefault();
    const corner = ev.target.closest?.("[data-corner]")?.dataset.corner;
    crop.box = corner
      ? moveCropCorner(crop.box, corner, move[0], move[1])
      : clampCropBox({ ...crop.box, x: crop.box.x + move[0], y: crop.box.y + move[1] });
    this._renderCrop();
  }

  _onCropFull() {
    const crop = this._crop;
    if (!crop || crop.saving) return;
    crop.box = { ...FULL_PAGE };
    this._setCropStatus(t(crop.lang, "crop_hint"));
    this._renderCrop();
  }

  async _onCropSave() {
    const crop = this._crop;
    if (!crop || crop.saving || isFullPage(crop.box)) return;
    const { spec, lang } = crop;
    crop.saving = true;
    this._setCropStatus(t(lang, "crop_saving"));
    this._renderCropButtons();
    let record;
    try {
      record = (
        await this._hass.callWS({
          type: "home_print/scans/crop",
          entry_id: spec.entryId,
          scan_record_id: spec.record.id,
          page: spec.page,
          box: roundBox(crop.box),
        })
      )?.entry;
    } catch (err) {
      if (crop !== this._crop) return;
      crop.saving = false;
      const code = err?.code;
      this._setCropStatus(code ? scanErrorText(lang, code) : t(lang, "crop_failed"), true);
      this._renderCropButtons();
      return;
    }
    if (crop !== this._crop) return;
    this._closeCrop();
    spec.onDone?.(record ?? spec.record);
  }

  _closeCrop() {
    if (this._crop) this._crop.drag = null;
    this._crop = null;
    this._cropToken += 1;
    this._role("crop-img")?.remove();
    this._hideDialog(this._role("crop-dialog"));
  }
}

function isFullPage(box) {
  return box.x <= 0.001 && box.y <= 0.001 && box.width >= 0.999 && box.height >= 0.999;
}

function roundBox(box) {
  const r = (v) => Math.round(v * 10000) / 10000;
  return clampCropBox(
    { x: r(box.x), y: r(box.y), width: r(box.width), height: r(box.height) },
    0.02,
  );
}
