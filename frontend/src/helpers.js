// Pure helpers: file checks, labels, paths, browser storage.

import {
  DEFAULT_FORMATS,
  EXT_FORMATS,
  NOISE_REASONS,
  REASONS,
  SCAN_ERRORS,
  WORD_EXTS,
  WORD_TYPES,
} from "./constants.js";
import { STRINGS, t } from "./i18n.js";

export function fileExt(file) {
  const name = String(file?.name ?? "");
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot + 1).toLowerCase();
}

export function fileFormat(file) {
  const type = String(file?.type ?? "").toLowerCase();
  if (DEFAULT_FORMATS.includes(type)) return type;
  return EXT_FORMATS[fileExt(file)] ?? type;
}

export function isWordFile(file) {
  const type = String(file?.type ?? "").toLowerCase();
  return WORD_EXTS.includes(fileExt(file)) || WORD_TYPES.includes(type);
}

export function validateFile(file, printer) {
  if (isWordFile(file)) return { ok: false, key: "word_file" };
  const formats = printer?.capabilities?.formats ?? DEFAULT_FORMATS;
  if (!formats.includes(fileFormat(file))) return { ok: false, key: "unsupported_type" };
  const mb = Number(printer?.max_file_mb);
  if (mb > 0 && file.size > mb * 1024 * 1024) return { ok: false, key: "too_large" };
  return { ok: true };
}

export function buildForm(file, options = {}) {
  const form = new FormData();
  form.append("file", file, file.name);
  for (const key of ["copies", "sides", "color_mode", "page_ranges"]) {
    const value = options[key];
    if (value === undefined || value === null || String(value).trim() === "") continue;
    form.append(key, String(value).trim());
  }
  return form;
}

export function reasonLabel(lang, reason) {
  const name = String(reason ?? "");
  if (name === "job-canceled-at-device") return t(lang, "reason_canceled_at_device");
  for (const [prefixes, key] of REASONS) {
    if (prefixes.some((prefix) => name.startsWith(prefix))) return t(lang, key);
  }
  return null;
}

// fetchWithAuth rejects before sending when the token can't be refreshed.
export function isAuthError(err, hass) {
  if (hass?.auth?.expired === true) return true;
  if (err?.status === 401 || err?.code === 401) return true;
  const text = `${err?.message ?? ""} ${err?.code ?? ""}`.toLowerCase();
  return ["auth", "token", "401"].some((word) => text.includes(word));
}

// Raw IPP keywords the card has no wording for, for the muted detail line.
export function visibleRawReasons(reasons) {
  const raw = Array.isArray(reasons) ? reasons.map((r) => String(r ?? "")) : [];
  return [
    ...new Set(raw.filter((r) => r && !NOISE_REASONS.includes(r) && reasonLabel("en", r) === null)),
  ];
}

export function knownReasons(lang, status) {
  const raw = Array.isArray(status?.reasons) ? status.reasons : [];
  return [...new Set(raw.map((reason) => reasonLabel(lang, reason)).filter(Boolean))];
}

// A stopped job with a known problem is an error; stopped/held without one is
// usually the printer pausing (e.g. letting ink dry between duplex sides).
export function isProblemState(status, lang = "en") {
  return status?.state === "stopped" && knownReasons(lang, status).length > 0;
}

export function jobLabel(lang, status, { twoSided = false } = {}) {
  const state = status?.state;
  const reasons = knownReasons(lang, status);
  const withReasons = (key) =>
    t(lang, key) + (reasons.length ? t(lang, "job_reasons", { reasons: reasons.join(", ") }) : "");
  const pausing = () => t(lang, twoSided ? "job_pausing_duplex" : "job_pausing");
  switch (state) {
    case "pending":
    case "processing":
      return t(lang, "job_printing");
    case "held":
      return reasons.length ? withReasons("job_held") : t(lang, "job_pausing");
    case "stopped":
      return reasons.length ? withReasons("job_stopped") : pausing();
    case "completed":
      return t(lang, "job_completed");
    case "canceled":
      return withReasons("job_canceled");
    case "aborted":
      return withReasons("job_aborted");
    default:
      return t(lang, "job_checking");
  }
}

// The two-sided value a checked box sends: the printer's own two-sided default
// (so a short-edge default survives), else long edge, else any two-sided.
export function twoSided(printer) {
  const sides = printer?.capabilities?.sides ?? [];
  const preferred = printer?.defaults?.sides;
  if (String(preferred ?? "").startsWith("two-sided") && sides.includes(preferred))
    return preferred;
  if (sides.includes("two-sided-long-edge")) return "two-sided-long-edge";
  return sides.find((s) => s.startsWith("two-sided"));
}

export function formatSize(bytes, lang) {
  const locale = lang === "tr" ? "tr-TR" : "en-US";
  const fmt = (n) => n.toLocaleString(locale, { maximumFractionDigits: 1 });
  if (bytes >= 1024 * 1024) return `${fmt(bytes / (1024 * 1024))} MB`;
  return `${fmt(Math.max(bytes, 1) / 1024)} KB`;
}

// iOS shows its own three-way sheet (Photo Library / Take Photo / Choose
// File) for a plain file input, so the card's menu would be a second one.
export function isIOS(nav) {
  if (!nav) return false;
  return (
    /iPad|iPhone|iPod/.test(String(nav.userAgent ?? "")) ||
    (nav.platform === "MacIntel" && nav.maxTouchPoints > 1)
  );
}

// The card's own "From files / Photo library / Take photo" menu is for
// touch-only phones and tablets that aren't iOS (Android's HA app offers no
// camera option itself). With a mouse or trackpad (desktop, touchscreen
// laptop) "Choose file" opens the system file dialog like any web app.
export function usesPickMenu(nav, win) {
  if (!nav || isIOS(nav)) return false;
  const mm = win?.matchMedia;
  if (typeof mm !== "function") return (nav.maxTouchPoints ?? 0) > 0;
  const query = (q) => Boolean(mm.call(win, q)?.matches);
  return query("(pointer: coarse)") && !query("(any-pointer: fine)");
}

// Local date and time in the user's language.
export function formatHistoryTime(lang, iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return "";
  const options = { dateStyle: "medium", timeStyle: "short" };
  try {
    return new Intl.DateTimeFormat(lang, options).format(date);
  } catch (_err) {
    return new Intl.DateTimeFormat("en", options).format(date);
  }
}

export function historyStateIcon(state) {
  if (state === "completed") return "✓";
  if (["aborted", "canceled", "error"].includes(state)) return "✗";
  return "…";
}

export function previewPath(entryId, recordId, page) {
  return `/api/home_print/history/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/page/${page}`;
}

export function scanPagePath(entryId, recordId, page) {
  return `/api/home_print/scans/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/page/${page}`;
}

export function scanFilePath(entryId, recordId) {
  return `/api/home_print/scans/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/file`;
}

// A scan error code in words; an unknown code gets the general text.
export function scanErrorText(lang, code) {
  const name = code === "printer_unavailable" ? "scanner_unavailable" : String(code ?? "");
  return t(lang, SCAN_ERRORS.includes(name) ? `scan_error_${name}` : "scan_error_scan_failed");
}

// Label of a scan option value: a known keyword in words, else as sent.
// Every colour mode the scanner reports is offered, colour first. Greyscale
// is shown as Black and white, as people call it; 1-bit black and white
// gets "(sharp)" only when greyscale is offered too, so the two differ.
export const SCAN_COLOR_ORDER = ["color", "gray", "bw"];

export function scanColorChoices(modes) {
  const known = SCAN_COLOR_ORDER.filter((mode) => modes.includes(mode));
  return [...known, ...modes.filter((mode) => !SCAN_COLOR_ORDER.includes(mode))];
}

export function scanColorLabel(lang, mode, modes) {
  if (mode === "bw" && modes.includes("gray")) return t(lang, "scan_color_bw_sharp");
  return scanOptionLabel(lang, "color", mode);
}

export function scanOptionLabel(lang, kind, value) {
  if (kind === "resolution") return t(lang, "scan_dpi", { n: value });
  const key = `scan_${kind}_${value}`;
  return key in STRINGS.en ? t(lang, key) : String(value);
}

// The printer picked in this browser, kept per card entry_id so two cards
// pinned to different printers don't share one choice.
export function storageKey(entryId) {
  return `home-print-card:printer:${entryId ?? ""}`;
}

export function readStored(key) {
  try {
    const value = globalThis.localStorage?.getItem(key);
    return typeof value === "string" && value ? value : null;
  } catch (_err) {
    return null;
  }
}

export function writeStored(key, value) {
  try {
    globalThis.localStorage?.setItem(key, value);
  } catch (_err) {
    // Private mode or storage off: the choice lasts until the page reloads.
  }
}

// Where the paper lies on a scanned page, as fractions of the page, or null
// when nothing clear stands out (then the whole page is the start).
// ``image`` is ImageData-like: { width, height, data } with RGBA bytes,
// best a small copy (a few hundred pixels wide).
//
// The scanner lid is the background: its colour is taken from the page's
// border. A pixel belongs to the paper when its colour differs from the lid,
// or when it sits on a sharp change of brightness (the paper's edge or
// shadow, which also finds white paper on a white lid). Rows and columns
// with enough such pixels give the box, padded a little.
export function detectPaper(image) {
  const { width: w, height: h, data } = image ?? {};
  if (!data || w < 16 || h < 16) return null;
  const lum = new Float32Array(w * h);
  for (let i = 0; i < w * h; i += 1) {
    lum[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  }
  // The lid's colour: the median of a thin band along the border.
  const band = Math.max(1, Math.round(Math.min(w, h) * 0.02));
  const samples = [[], [], []];
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      if (x >= band && x < w - band && y >= band && y < h - band) continue;
      const i = (y * w + x) * 4;
      for (let c = 0; c < 3; c += 1) samples[c].push(data[i + c]);
    }
  }
  const bg = samples.map((list) => {
    list.sort((a, b) => a - b);
    return list[list.length >> 1];
  });
  // A light blur first, so scanner noise and JPEG grain don't count as
  // edges, but the faint step from a white lid to white paper does.
  const blur = new Float32Array(w * h);
  for (let y = 1; y < h - 1; y += 1) {
    for (let x = 1; x < w - 1; x += 1) {
      let sum = 0;
      for (let dy = -1; dy <= 1; dy += 1) {
        const row = (y + dy) * w + x;
        sum += lum[row - 1] + lum[row] + lum[row + 1];
      }
      blur[y * w + x] = sum / 9;
    }
  }
  const COLOR_DIFF = 40;
  const EDGE_DIFF = 8;
  const margin = Math.max(2, Math.round(Math.min(w, h) * 0.015));
  const rows = new Uint32Array(h);
  const cols = new Uint32Array(w);
  for (let y = margin; y < h - margin; y += 1) {
    for (let x = margin; x < w - margin; x += 1) {
      const p = y * w + x;
      const i = p * 4;
      const colorDiff = Math.max(
        Math.abs(data[i] - bg[0]),
        Math.abs(data[i + 1] - bg[1]),
        Math.abs(data[i + 2] - bg[2]),
      );
      const edge = Math.abs(blur[p + 1] - blur[p - 1]) + Math.abs(blur[p + w] - blur[p - w]);
      if (colorDiff > COLOR_DIFF || edge > EDGE_DIFF) {
        rows[y] += 1;
        cols[x] += 1;
      }
    }
  }
  // Specks and dust: a row or column needs a few percent of hits.
  const rowMin = Math.max(2, Math.round(w * 0.02));
  const colMin = Math.max(2, Math.round(h * 0.02));
  const first = (counts, min) => counts.findIndex((n) => n >= min);
  const last = (counts, min) => {
    for (let i = counts.length - 1; i >= 0; i -= 1) if (counts[i] >= min) return i;
    return -1;
  };
  const top = first(rows, rowMin);
  const bottom = last(rows, rowMin);
  const left = first(cols, colMin);
  const right = last(cols, colMin);
  if (top < 0 || left < 0 || bottom <= top || right <= left) return null;
  const pad = 0.01;
  const x0 = Math.max(0, left / w - pad);
  const y0 = Math.max(0, top / h - pad);
  const x1 = Math.min(1, (right + 1) / w + pad);
  const y1 = Math.min(1, (bottom + 1) / h + pad);
  const box = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  // Almost the whole page, or a sliver: no useful suggestion.
  if (box.width * box.height > 0.95 || box.width < 0.05 || box.height < 0.05) return null;
  return box;
}

// Keeps a crop box inside the page and at least ``min`` on each side.
export function clampCropBox(box, min = 0.05) {
  const width = Math.min(1, Math.max(min, box.width));
  const height = Math.min(1, Math.max(min, box.height));
  const x = Math.min(1 - width, Math.max(0, box.x));
  const y = Math.min(1 - height, Math.max(0, box.y));
  return { x, y, width, height };
}

// Moves one corner (``nw``, ``ne``, ``sw``, ``se``) of a box by (dx, dy),
// keeping the opposite corner where it is.
export function moveCropCorner(box, corner, dx, dy, min = 0.05) {
  let x0 = box.x;
  let y0 = box.y;
  let x1 = box.x + box.width;
  let y1 = box.y + box.height;
  if (corner.includes("w")) x0 = Math.min(x1 - min, Math.max(0, x0 + dx));
  if (corner.includes("e")) x1 = Math.max(x0 + min, Math.min(1, x1 + dx));
  if (corner.includes("n")) y0 = Math.min(y1 - min, Math.max(0, y0 + dy));
  if (corner.includes("s")) y1 = Math.max(y0 + min, Math.min(1, y1 + dy));
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}
