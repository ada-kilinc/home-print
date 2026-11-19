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
