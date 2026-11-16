/* Home Print dashboard card.
 *
 * A single, build-free Web Component. It lists printers through the
 * `home_print/printers` WebSocket command, uploads files to
 * `/api/home_print/upload/<entry_id>` with `hass.fetchWithAuth` and follows the
 * job with `home_print/job`. A clock button opens the print history
 * (`home_print/history`, `home_print/history/delete`) and a page preview
 * served by `/api/home_print/history/<entry_id>/<id>/page/<n>`.
 */

const CARD_TYPE = "home-print-card";
const EDITOR_TYPE = "home-print-card-editor";
const REFRESH_MS = 60 * 1000;
const POLL_MS = 3 * 1000;
const POLL_LIMIT_MS = 10 * 60 * 1000;
// Past this the job no longer holds the Print button while its status can't
// be read, so a stalled poll never locks the card.
const STALL_MS = 30 * 1000;
// A little over the server's own 300 s print timeout.
const UPLOAD_TIMEOUT_MS = 330 * 1000;
const EDITOR_RETRY_MS = 30 * 1000;
const PAGE_RANGES_RE = /^\s*\d+(\s*-\s*\d*)?(\s*,\s*\d+(\s*-\s*\d*)?)*\s*$/;
const ACCEPT = "application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png";
// Some Android pickers honour only the first MIME type of ACCEPT, which greys
// out photos; this second picker asks for images only (iOS hands Photos' HEIC
// over as JPEG for it).
const PHOTO_ACCEPT = "image/jpeg,image/png";
const CAMERA_ACCEPT = "image/*";
const FILE_INPUTS = ["input-file", "input-photo", "input-camera"];
const PREVIEW_SIGN_SECONDS = 300;
// A signature older than this is renewed before its image is requested.
const PREVIEW_RESIGN_MS = 240 * 1000;
const PREVIEW_MARGIN = "800px 0px";
const DEFAULT_FORMATS = ["application/pdf", "image/jpeg", "image/png"];
const EXT_FORMATS = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};
const WORD_EXTS = ["doc", "docx", "odt", "rtf"];
const WORD_TYPES = [
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.oasis.opendocument.text",
  "application/rtf",
  "text/rtf",
];
const RUNNING_JOB_STATES = ["pending", "held", "processing", "stopped"];
const FATAL_JOB_ERRORS = ["not_found", "unauthorized"];
// IPP job-state-reasons worth showing, by prefix; any other reason is hidden.
const REASONS = [
  [["media-empty", "media-needed"], "reason_media_empty"],
  [["media-jam"], "reason_media_jam"],
  [["marker-supply-empty", "toner-empty"], "reason_ink_empty"],
  [["door-open", "cover-open"], "reason_cover_open"],
];
// Housekeeping keywords printers send all the time; never worth showing.
const NOISE_REASONS = [
  "none",
  "job-printing",
  "job-incoming",
  "job-queued",
  "processing-to-stop-point",
  "job-data-insufficient",
  "job-completed-successfully",
];
const PRINTER_ERROR_LIMIT = 3;
const KNOWN_STATES = ["idle", "processing", "stopped"];
const HISTORY_STATES = ["sent", "completed", "aborted", "canceled", "error"];

// Material Design Icons paths (Apache 2.0), drawn inline so the card needs
// no HA icon component.
const ICONS = {
  history:
    "M13.5,8H12V13L16.28,15.54L17,14.33L13.5,12.25V8M13,3A9,9 0 0,0 4,12H1L4.96,16.03L9,12H6A7,7 0 0,1 13,5A7,7 0 0,1 20,12A7,7 0 0,1 13,19C11.07,19 9.32,18.21 8.06,16.94L6.64,18.36C8.27,20 10.5,21 13,21A9,9 0 0,0 22,12A9,9 0 0,0 13,3",
  delete:
    "M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19M8,9H16V19H8V9M15.5,4L14.5,3H9.5L8.5,4H5V6H19V4H15.5Z",
  close:
    "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  paperclip:
    "M16.5,6V17.5A4,4 0 0,1 12.5,21.5A4,4 0 0,1 8.5,17.5V5A2.5,2.5 0 0,1 11,2.5A2.5,2.5 0 0,1 13.5,5V15.5A1,1 0 0,1 12.5,16.5A1,1 0 0,1 11.5,15.5V6H10V15.5A2.5,2.5 0 0,0 12.5,18A2.5,2.5 0 0,0 15,15.5V5A4,4 0 0,0 11,1A4,4 0 0,0 7,5V17.5A5.5,5.5 0 0,0 12.5,23A5.5,5.5 0 0,0 18,17.5V6H16.5Z",
  images:
    "M22,16V4A2,2 0 0,0 20,2H8A2,2 0 0,0 6,4V16A2,2 0 0,0 8,18H20A2,2 0 0,0 22,16M11,12L13.03,14.71L16,11L20,16H8M2,6V20A2,2 0 0,0 4,22H18V20H4V6",
  camera:
    "M4,4H7L9,2H15L17,4H20A2,2 0 0,1 22,6V18A2,2 0 0,1 20,20H4A2,2 0 0,1 2,18V6A2,2 0 0,1 4,4M12,7A5,5 0 0,0 7,12A5,5 0 0,0 12,17A5,5 0 0,0 17,12A5,5 0 0,0 12,7M12,9A3,3 0 0,1 15,12A3,3 0 0,1 12,15A3,3 0 0,1 9,12A3,3 0 0,1 12,9Z",
};

const svg = (name) =>
  `<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false"><path d="${ICONS[name]}"></path></svg>`;

const STRINGS = {
  tr: {
    choose_file: "Dosya seç",
    pick_file: "Dosyadan seç",
    pick_photo: "Fotoğraf seç",
    pick_camera: "Fotoğraf çek",
    history: "Geçmiş",
    close: "Kapat",
    delete: "Sil",
    history_loading: "Yükleniyor…",
    history_empty: "Henüz baskı yok.",
    history_failed: "Geçmiş alınamadı. Birazdan tekrar dene.",
    delete_failed: "Silinemedi. Birazdan tekrar dene.",
    delete_not_allowed: "Kayıtları yalnızca yöneticiler silebilir.",
    history_pages_one: "1 sayfa",
    history_pages: "{n} sayfa",
    file_gone_tag: "dosya yok",
    file_gone: "Bu dosya artık saklanmıyor.",
    preview_failed: "Ön izleme yüklenemedi.",
    preview_page: "Sayfa {n}",
    history_state_sent: "Gönderildi",
    history_state_completed: "Tamamlandı",
    history_state_aborted: "Yarıda kaldı",
    history_state_canceled: "İptal edildi",
    history_state_error: "Hata verdi",
    editor_printer: "Yazıcı",
    editor_auto: "Otomatik (ilk yazıcı)",
    editor_not_found: "{id} (bulunamadı)",
    editor_title: "Başlık",
    editor_show_ink: "Mürekkep seviyelerini göster",
    copies: "Kopya",
    duplex: "Çift taraf",
    color: "Renkli",
    pages: "Sayfalar",
    pages_placeholder: "hepsi",
    print: "Yazdır",
    state_idle: "Hazır",
    state_processing: "Yazdırıyor",
    state_stopped: "Durdu",
    state_unreachable: "Ulaşılamıyor",
    state_unknown: "Bilinmiyor",
    problem: "Sorun var",
    ink_black: "Siyah",
    ink_color: "Renkli",
    percent: "%{value}",
    picker: "Yazıcı",
    loading: "Yazıcılar yükleniyor…",
    load_failed:
      "Yazıcı listesi alınamadı. Home Print hâlâ yükleniyor olabilir, birazdan tekrar denerim. Böyle sürerse entegrasyonun kurulu olup olmadığına bak.",
    no_printers:
      "Yazıcı görünmüyor. Home Print hâlâ yükleniyor olabilir, birazdan tekrar bakarım. Hiç eklemediysen önce entegrasyonu ekle.",
    unknown_printer:
      "Kartta ayarlı yazıcı ({id}) şu an listede yok. Entegrasyon hâlâ yükleniyor olabilir; silindiyse kart ayarlarından başka bir yazıcı seç.",
    not_allowed: "Bu yazıcıyla yalnızca yöneticiler yazdırabilir.",
    word_file:
      "Word dosyalarını şimdilik yazdıramıyorum. Dosyayı önce PDF olarak kaydet (telefonda: Paylaş → PDF olarak yazdır/kaydet).",
    unsupported_type: "Bu dosya türünü yazdıramıyorum. PDF, JPEG ya da PNG seç.",
    too_large: "Dosya çok büyük. En fazla {mb} MB olabilir.",
    bad_pages: "Sayfa aralığını anlayamadım. Örnek: 1-3,5",
    uploading: "Gönderiliyor…",
    session_expired: "Oturum süresi doldu, sayfayı yenile.",
    network_error: "Bağlantı kurulamadı. Ağını kontrol edip tekrar dene.",
    upload_failed: "Yazdırılamadı (HTTP {status}).",
    job_printing: "Yazdırılıyor…",
    job_held: "Yazıcıda bekliyor…",
    job_pausing: "Yazıcı bekliyor…",
    job_pausing_duplex:
      "Yazıcı bekliyor… Çift taraflı baskıda arka yüz öncesi mürekkebin kuruması beklenir.",
    job_stopped: "Yazıcı durdu, yazıcıya bak.",
    job_completed: "Tamamlandı ✓",
    job_canceled: "İş iptal edildi.",
    job_aborted: "Yazdırma yarıda kaldı.",
    job_reasons: " ({reasons})",
    job_checking: "Durum şu an alınamıyor, takip etmeye devam ediyorum…",
    job_lost: "İşin durumu alınamıyor.",
    job_status_failed: "Durum alınamadı, yazıcıya bak.",
    job_timeout: "Durum bilinmiyor, yazıcıya bak.",
    job_gone: "İş yazıcının listesinde yok, muhtemelen bitti. Kâğıda bak.",
    upload_timeout:
      "Yükleme çok uzun sürdü. İş yine de yazdırılmış olabilir, tekrar denemeden önce yazıcıya bak.",
    reason_media_empty: "Kâğıt bitti",
    reason_media_jam: "Kâğıt sıkıştı",
    reason_ink_empty: "Mürekkep bitti",
    reason_cover_open: "Kapak açık",
    reason_canceled_at_device: "Yazıcıdan iptal edildi",
  },
  en: {
    editor_printer: "Printer",
    editor_auto: "Automatic (first printer)",
    editor_not_found: "{id} (not found)",
    editor_title: "Title",
    editor_show_ink: "Show ink levels",
    choose_file: "Choose file",
    pick_file: "From files",
    pick_photo: "Photo library",
    pick_camera: "Take photo",
    history: "History",
    close: "Close",
    delete: "Delete",
    history_loading: "Loading…",
    history_empty: "No prints yet.",
    history_failed: "Couldn't load the history. Try again shortly.",
    delete_failed: "Couldn't delete it. Try again shortly.",
    delete_not_allowed: "Only administrators can delete history entries.",
    history_pages_one: "1 page",
    history_pages: "{n} pages",
    file_gone_tag: "file not kept",
    file_gone: "This file is no longer kept.",
    preview_failed: "Couldn't load the preview.",
    preview_page: "Page {n}",
    history_state_sent: "Sent",
    history_state_completed: "Completed",
    history_state_aborted: "Aborted",
    history_state_canceled: "Canceled",
    history_state_error: "Failed",
    copies: "Copies",
    duplex: "Two-sided",
    color: "Colour",
    pages: "Pages",
    pages_placeholder: "all",
    print: "Print",
    state_idle: "Ready",
    state_processing: "Printing",
    state_stopped: "Stopped",
    state_unreachable: "Unreachable",
    state_unknown: "Unknown",
    problem: "Needs attention",
    ink_black: "Black",
    ink_color: "Colour",
    percent: "{value}%",
    picker: "Printer",
    loading: "Loading printers…",
    load_failed:
      "Couldn't load the printer list. Home Print may still be loading; I'll try again shortly. If this persists, check that the integration is installed.",
    no_printers:
      "No printers listed. Home Print may still be loading; I'll check again shortly. If you haven't added one yet, add the integration first.",
    unknown_printer:
      "The printer set for this card ({id}) isn't listed right now. The integration may still be loading; if it was removed, pick another printer in the card settings.",
    not_allowed: "Only administrators can print on this printer.",
    word_file: "Word files can't be printed yet. Save the file as PDF first.",
    unsupported_type: "This file type can't be printed. Choose a PDF, JPEG or PNG.",
    too_large: "The file is too large. The limit is {mb} MB.",
    bad_pages: "Couldn't read the page range. Example: 1-3,5",
    uploading: "Sending…",
    session_expired: "Your session has expired. Reload the page.",
    network_error: "Couldn't connect. Check your network and try again.",
    upload_failed: "Printing failed (HTTP {status}).",
    job_printing: "Printing…",
    job_held: "Waiting at the printer…",
    job_pausing: "The printer is pausing…",
    job_pausing_duplex:
      "The printer is pausing… With two-sided printing it waits for the ink to dry before the back side.",
    job_stopped: "The printer has stopped. Check the printer.",
    job_completed: "Done ✓",
    job_canceled: "The job was canceled.",
    job_aborted: "Printing was aborted.",
    job_reasons: " ({reasons})",
    job_checking: "Can't get the status right now, still checking…",
    job_lost: "Can't get the job's status.",
    job_status_failed: "Couldn't get the status, check the printer.",
    job_timeout: "Status unknown, check the printer.",
    job_gone: "The printer no longer lists the job; it probably finished.",
    upload_timeout:
      "The upload took too long. The job may still have printed; check the printer before trying again.",
    reason_media_empty: "Out of paper",
    reason_media_jam: "Paper jam",
    reason_ink_empty: "Out of ink",
    reason_cover_open: "Cover open",
    reason_canceled_at_device: "Cancelled at the printer",
  },
};

// ---------------------------------------------------------------- helpers

function pickLanguage(hass) {
  const language = hass?.locale?.language ?? hass?.language ?? "en";
  return String(language).toLowerCase().startsWith("tr") ? "tr" : "en";
}

function t(lang, key, vars = {}) {
  const template = STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    name in vars ? String(vars[name]) : match,
  );
}

function fileExt(file) {
  const name = String(file?.name ?? "");
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot + 1).toLowerCase();
}

function fileFormat(file) {
  const type = String(file?.type ?? "").toLowerCase();
  if (DEFAULT_FORMATS.includes(type)) return type;
  return EXT_FORMATS[fileExt(file)] ?? type;
}

function isWordFile(file) {
  const type = String(file?.type ?? "").toLowerCase();
  return WORD_EXTS.includes(fileExt(file)) || WORD_TYPES.includes(type);
}

function validateFile(file, printer) {
  if (isWordFile(file)) return { ok: false, key: "word_file" };
  const formats = printer?.capabilities?.formats ?? DEFAULT_FORMATS;
  if (!formats.includes(fileFormat(file))) return { ok: false, key: "unsupported_type" };
  const mb = Number(printer?.max_file_mb);
  if (mb > 0 && file.size > mb * 1024 * 1024) return { ok: false, key: "too_large" };
  return { ok: true };
}

function buildForm(file, options = {}) {
  const form = new FormData();
  form.append("file", file, file.name);
  for (const key of ["copies", "sides", "color_mode", "page_ranges"]) {
    const value = options[key];
    if (value === undefined || value === null || String(value).trim() === "") continue;
    form.append(key, String(value).trim());
  }
  return form;
}

function reasonLabel(lang, reason) {
  const name = String(reason ?? "");
  if (name === "job-canceled-at-device") return t(lang, "reason_canceled_at_device");
  for (const [prefixes, key] of REASONS) {
    if (prefixes.some((prefix) => name.startsWith(prefix))) return t(lang, key);
  }
  return null;
}

// fetchWithAuth rejects before sending when the token can't be refreshed.
function isAuthError(err, hass) {
  if (hass?.auth?.expired === true) return true;
  if (err?.status === 401 || err?.code === 401) return true;
  const text = `${err?.message ?? ""} ${err?.code ?? ""}`.toLowerCase();
  return ["auth", "token", "401"].some((word) => text.includes(word));
}

// Raw IPP keywords the card has no wording for, for the muted detail line.
function visibleRawReasons(reasons) {
  const raw = Array.isArray(reasons) ? reasons.map((r) => String(r ?? "")) : [];
  return [
    ...new Set(
      raw.filter((r) => r && !NOISE_REASONS.includes(r) && reasonLabel("en", r) === null),
    ),
  ];
}

function knownReasons(lang, status) {
  const raw = Array.isArray(status?.reasons) ? status.reasons : [];
  return [...new Set(raw.map((reason) => reasonLabel(lang, reason)).filter(Boolean))];
}

// A stopped job with a known problem is an error; stopped/held without one is
// usually the printer pausing (e.g. letting ink dry between duplex sides).
function isProblemState(status, lang = "en") {
  return status?.state === "stopped" && knownReasons(lang, status).length > 0;
}

function jobLabel(lang, status, { twoSided = false } = {}) {
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
function twoSided(printer) {
  const sides = printer?.capabilities?.sides ?? [];
  const preferred = printer?.defaults?.sides;
  if (String(preferred ?? "").startsWith("two-sided") && sides.includes(preferred)) return preferred;
  if (sides.includes("two-sided-long-edge")) return "two-sided-long-edge";
  return sides.find((s) => s.startsWith("two-sided"));
}

function formatSize(bytes, lang) {
  const locale = lang === "tr" ? "tr-TR" : "en-US";
  const fmt = (n) => n.toLocaleString(locale, { maximumFractionDigits: 1 });
  if (bytes >= 1024 * 1024) return `${fmt(bytes / (1024 * 1024))} MB`;
  return `${fmt(Math.max(bytes, 1) / 1024)} KB`;
}

// iOS shows its own three-way sheet (Photo Library / Take Photo / Choose
// File) for a plain file input, so the card's menu would be a second one.
function isIOS(nav) {
  if (!nav) return false;
  return (
    /iPad|iPhone|iPod/.test(String(nav.userAgent ?? "")) ||
    (nav.platform === "MacIntel" && nav.maxTouchPoints > 1)
  );
}

// Local date and time in the user's language.
function formatHistoryTime(lang, iso) {
  const date = new Date(iso);
  if (!iso || Number.isNaN(date.getTime())) return "";
  const options = { dateStyle: "medium", timeStyle: "short" };
  try {
    return new Intl.DateTimeFormat(lang, options).format(date);
  } catch (_err) {
    return new Intl.DateTimeFormat("en", options).format(date);
  }
}

function historyStateIcon(state) {
  if (state === "completed") return "✓";
  if (["aborted", "canceled", "error"].includes(state)) return "✗";
  return "…";
}

function previewPath(entryId, recordId, page) {
  return `/api/home_print/history/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/page/${page}`;
}

function svgIcon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(ns, "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("width", "24");
  icon.setAttribute("height", "24");
  icon.setAttribute("aria-hidden", "true");
  icon.setAttribute("focusable", "false");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name]);
  icon.append(path);
  return icon;
}

function markerBackground(color) {
  const parts = String(color ?? "").match(/#[0-9a-fA-F]{6}/g) ?? [];
  if (parts.length === 0) return "var(--primary-color)";
  if (parts.length === 1) return parts[0];
  return `linear-gradient(90deg, ${parts.join(", ")})`;
}

// ---------------------------------------------------------------- view

const STYLE = `
  :host { display: block; }
  ha-card { display: block; overflow: hidden; }
  .card {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    box-sizing: border-box;
    min-width: 0;
  }
  [hidden] { display: none !important; }
  .header { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-width: 0; }
  .title {
    font-size: 1.2em;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .state { color: var(--secondary-text-color); }
  .picker-slot { margin-left: auto; }
  svg { width: 24px; height: 24px; flex: none; fill: currentColor; }
  .icon-button {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: none;
    color: var(--secondary-text-color);
    cursor: pointer;
  }
  .icon-button:hover { color: var(--primary-text-color); }
  .icon-button:disabled { opacity: 0.4; cursor: default; }
  select, input[type="number"], input[type="text"] {
    min-height: 44px;
    box-sizing: border-box;
    font: inherit;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    padding: 0 8px;
    max-width: 100%;
  }
  .notice {
    color: var(--error-color);
    border: 1px solid var(--error-color);
    border-radius: 8px;
    padding: 8px 12px;
  }
  .notice.info { color: var(--secondary-text-color); border-color: var(--divider-color); }
  .ink { display: flex; flex-wrap: wrap; gap: 8px 16px; }
  .marker { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .bar {
    width: 64px;
    height: 10px;
    border-radius: 5px;
    background: var(--divider-color);
    overflow: hidden;
    flex: none;
  }
  .bar-fill { height: 100%; }
  .pct { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .file-row {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .file-button {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid var(--primary-color);
    font: inherit;
    color: var(--primary-color);
    background: none;
    cursor: pointer;
  }
  .hidden-input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    pointer-events: none;
  }
  .pick-menu {
    flex: 1 1 100%;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    overflow: hidden;
  }
  .pick-menu button {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    padding: 0 16px;
    border: none;
    background: none;
    font: inherit;
    text-align: start;
    color: var(--primary-text-color);
    cursor: pointer;
  }
  .pick-menu button + button { border-top: 1px solid var(--divider-color); }
  .pick-menu button svg { color: var(--secondary-text-color); }
  .file-name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-size { flex: none; color: var(--secondary-text-color); }
  .options { display: flex; flex-wrap: wrap; gap: 8px 16px; }
  .option { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; }
  .option input[type="checkbox"] { width: 24px; height: 24px; margin: 10px; accent-color: var(--primary-color); }
  .option input[type="number"] { width: 72px; }
  .pages { display: flex; align-items: center; gap: 8px; }
  .pages input { flex: 1 1 auto; min-width: 0; }
  .print {
    min-height: 48px;
    width: 100%;
    border: none;
    border-radius: 8px;
    font: inherit;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-primary-color);
    background: var(--primary-color);
    cursor: pointer;
  }
  .print:disabled { opacity: 0.5; cursor: default; }
  .message { min-height: 1.2em; overflow-wrap: anywhere; }
  .message.error { color: var(--error-color); }
  .detail {
    color: var(--secondary-text-color);
    font-size: 0.85em;
    overflow-wrap: anywhere;
  }

  /* Dialogs: showModal() puts them in the top layer, so a dashboard layout
     that contains fixed elements can't trap them inside the card. */
  dialog {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    max-width: none;
    max-height: none;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--primary-text-color);
    box-sizing: border-box;
    overscroll-behavior: contain;
  }
  dialog[open] { display: flex; align-items: flex-end; justify-content: center; }
  dialog::backdrop { background: var(--mdc-dialog-scrim-color, rgba(0, 0, 0, 0.32)); }
  .sheet {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-height: 85vh;
    max-height: 85dvh;
    min-width: 0;
    box-sizing: border-box;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.2);
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  @media (min-width: 600px) {
    dialog[open] { align-items: center; }
    .sheet { max-width: 480px; border-radius: 16px; }
  }
  .sheet-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 8px 8px 16px;
    border-bottom: 1px solid var(--divider-color);
    min-width: 0;
  }
  .sheet-title {
    flex: 1 1 auto;
    min-width: 0;
    font-size: 1.1em;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sheet-status { padding: 12px 16px; color: var(--secondary-text-color); overflow-wrap: anywhere; }
  .sheet-status.error { color: var(--error-color); }
  .history-list {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    min-height: 0;
  }
  .history-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding-right: 8px;
    border-bottom: 1px solid var(--divider-color);
    min-width: 0;
  }
  .history-open {
    flex: 1 1 auto;
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    min-height: 56px;
    padding: 8px 8px 8px 16px;
    border: none;
    background: none;
    font: inherit;
    text-align: start;
    color: inherit;
    cursor: pointer;
  }
  .history-open.static { cursor: default; }
  .history-mark { flex: none; width: 1.5em; text-align: center; font-weight: 500; }
  .history-mark.ok { color: var(--success-color, var(--primary-color)); }
  .history-mark.bad { color: var(--error-color); }
  .history-mark.busy { color: var(--secondary-text-color); }
  .history-text { flex: 1 1 auto; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .history-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .history-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 8px;
    color: var(--secondary-text-color);
    font-size: 0.85em;
  }
  .tag {
    padding: 0 6px;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    font-size: 0.9em;
  }
  .preview-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
    overflow-y: auto;
    overscroll-behavior: contain;
    min-height: 0;
  }
  .page {
    width: 100%;
    aspect-ratio: 210 / 297;
    flex: none;
    background: var(--secondary-background-color);
  }
  .page.loaded { aspect-ratio: auto; background: none; }
  .preview-body img {
    display: block;
    width: 100%;
    height: auto;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  }
  .preview-body .sheet-status { padding: 0; }
`;

const TEMPLATE = `
  <style>${STYLE}</style>
  <ha-card>
    <div class="card">
      <div class="header">
        <span aria-hidden="true">🖨</span>
        <span class="title" data-role="title"></span>
        <span class="state" data-role="state-dash" aria-hidden="true">—</span>
        <span class="state" data-role="state"></span>
        <span class="picker-slot" data-role="picker-slot"></span>
        <button type="button" class="icon-button" data-role="history-button" data-aria="history">
          ${svg("history")}
        </button>
      </div>
      <div class="notice" data-role="notice" role="alert" hidden></div>
      <div class="ink" data-role="ink"></div>
      <div class="file-row">
        <button type="button" class="file-button" data-role="pick">
          ${svg("paperclip")}<span data-t="choose_file"></span>
        </button>
        <span class="file-name" data-role="file-name"></span>
        <span class="file-size" data-role="file-size"></span>
        <div class="pick-menu" data-role="pick-menu" role="menu" hidden>
          <button type="button" role="menuitem" data-option="file">
            ${svg("paperclip")}<span data-t="pick_file"></span>
          </button>
          <button type="button" role="menuitem" data-option="photo">
            ${svg("images")}<span data-t="pick_photo"></span>
          </button>
          <button type="button" role="menuitem" data-option="camera">
            ${svg("camera")}<span data-t="pick_camera"></span>
          </button>
        </div>
        <input type="file" class="hidden-input" data-role="input-file" accept="${ACCEPT}" tabindex="-1" aria-hidden="true" />
        <input type="file" class="hidden-input" data-role="input-photo" accept="${PHOTO_ACCEPT}" tabindex="-1" aria-hidden="true" />
        <input type="file" class="hidden-input" data-role="input-camera" accept="${CAMERA_ACCEPT}" capture="environment" tabindex="-1" aria-hidden="true" />
      </div>
      <div class="options">
        <label class="option" data-opt="copies">
          <span data-t="copies"></span>
          <input type="number" data-role="copies" min="1" value="1" inputmode="numeric" />
        </label>
        <label class="option" data-opt="duplex">
          <span data-t="duplex"></span>
          <input type="checkbox" data-role="duplex" />
        </label>
        <label class="option" data-opt="color">
          <span data-t="color"></span>
          <input type="checkbox" data-role="color" />
        </label>
      </div>
      <label class="pages" data-opt="pages">
        <span data-t="pages"></span>
        <input type="text" data-role="pages" autocomplete="off" />
      </label>
      <button type="button" class="print" data-role="print" data-t="print"></button>
      <div class="message" data-role="message" aria-live="polite"></div>
      <div class="detail" data-role="detail" hidden></div>
    </div>
  </ha-card>
  <dialog data-role="history-dialog" aria-labelledby="history-title">
    <div class="sheet">
      <div class="sheet-head">
        <span class="sheet-title" id="history-title" data-t="history"></span>
        <button type="button" class="icon-button" data-role="history-close" data-aria="close">
          ${svg("close")}
        </button>
      </div>
      <div class="sheet-status" data-role="history-status" role="status"></div>
      <ul class="history-list" data-role="history-list"></ul>
    </div>
  </dialog>
  <dialog data-role="preview-dialog" aria-labelledby="preview-title">
    <div class="sheet">
      <div class="sheet-head">
        <span class="sheet-title" id="preview-title" data-role="preview-title"></span>
        <button type="button" class="icon-button" data-role="preview-close" data-aria="close">
          ${svg("close")}
        </button>
      </div>
      <div class="preview-body" data-role="preview-body"></div>
    </div>
  </dialog>
`;

// ---------------------------------------------------------------- card

class HomePrintCard extends HTMLElement {
  constructor() {
    super();
    this._config = { show_ink: true };
    this._hass = null;
    this._printers = null;
    this._loadFailed = false;
    this._loading = false;
    this._pickedId = null;
    this._appliedId = null;
    this._pickerKey = "";
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
    this._deletedIds = new Set();
    this._savedOverflow = null;
    this._onDocumentClick = (ev) => this._closeMenuOutside(ev);
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
    this._role("history-button").addEventListener("click", () => this._openHistory());
    this._role("history-close").addEventListener("click", () => this._closeHistory());
    this._role("preview-close").addEventListener("click", () => this._closePreview());
    this._wireDialog(this._role("history-dialog"), () => this._closeHistory());
    this._wireDialog(this._role("preview-dialog"), () => this._closePreview());
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
      entry_id: typeof config.entry_id === "string" && config.entry_id ? config.entry_id : undefined,
      title: typeof config.title === "string" && config.title ? config.title : undefined,
      show_ink: config.show_ink !== false,
    };
    if (next.entry_id !== this._config.entry_id) this._pickedId = null;
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
    if (this._hass) this._startRefresh();
    if (this._job && !this._pollTimer) this._schedulePoll();
  }

  disconnectedCallback() {
    this._closeHistory();
    this._closeMenu();
    clearInterval(this._refreshTimer);
    clearTimeout(this._pollTimer);
    this._refreshTimer = null;
    this._pollTimer = null;
  }

  // ------------------------------------------------------------ data

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
      this._loadFailed = false;
    } catch (_err) {
      // Keep the last good list; only complain when there never was one.
      if (this._printers === null) this._loadFailed = true;
    } finally {
      this._loading = false;
    }
    this._update();
  }

  _wantedId() {
    return this._pickedId ?? this._config.entry_id ?? null;
  }

  _printer() {
    const printers = this._printers ?? [];
    const wanted = this._wantedId();
    if (wanted) return printers.find((p) => p.entry_id === wanted) ?? null;
    return printers[0] ?? null;
  }

  _reachable(printer) {
    if (!printer || !printer.available) return false;
    const status = this._entityState(printer.entities?.status);
    return status?.state !== "unavailable";
  }

  _entityState(entityId) {
    return entityId ? this._hass?.states?.[entityId] : undefined;
  }

  _fileCheck(printer) {
    return this._file ? validateFile(this._file, printer) : null;
  }

  // A running job holds the Print button, unless its status has been out of
  // reach for longer than STALL_MS.
  _jobHolds() {
    const job = this._job;
    if (!job) return false;
    return job.troubleSince === null || Date.now() - job.troubleSince <= STALL_MS;
  }

  _canSubmit(printer) {
    return (
      !this._uploading &&
      !this._jobHolds() &&
      Boolean(printer) &&
      this._reachable(printer) &&
      printer.can_print !== false &&
      this._fileCheck(printer)?.ok === true
    );
  }

  // ------------------------------------------------------------ events

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

  _onPick(ev) {
    this._pickedId = ev.target.value || null;
    this._update();
  }

  // ------------------------------------------------------------ file picker

  _onPickButton() {
    // iOS already offers Photo Library / Take Photo / Choose File itself.
    if (isIOS(globalThis.navigator)) {
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

  // ------------------------------------------------------------ dialogs

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
    return this._role("history-dialog").open || this._role("preview-dialog").open;
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
    this._historyEntries = [];
    this._deletedIds = new Set();
    this._renderHistory({ key: "history_loading" });
    this._showDialog(this._role("history-dialog"));
    this._loadHistory();
  }

  _closeHistory() {
    this._closePreview();
    this._historyEntryId = null;
    this._historyToken += 1;
    this._hideDialog(this._role("history-dialog"));
  }

  async _loadHistory() {
    const entryId = this._historyEntryId;
    if (!entryId || !this._hass) return;
    const token = ++this._historyToken;
    let result;
    try {
      result = await this._hass.callWS({ type: "home_print/history", entry_id: entryId });
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
    button.disabled = true;
    try {
      await this._hass.callWS({
        type: "home_print/history/delete",
        entry_id: entryId,
        history_id: record.id,
      });
    } catch (err) {
      button.disabled = false;
      if (this._historyEntryId !== entryId) return;
      const key = err?.code === "unauthorized" ? "delete_not_allowed" : "delete_failed";
      this._renderHistory({ key, error: true });
      return;
    }
    if (this._historyEntryId !== entryId) return;
    // {"deleted": false} means it was already gone; either way the row goes.
    this._deletedIds.add(record.id);
    const index = this._historyEntries.findIndex((e) => e.id === record.id);
    this._historyEntries = this._historyEntries.filter((e) => e.id !== record.id);
    this._renderHistory();
    // Focus moves on to the row that took its place, else to the close button.
    const rows = this._role("history-list").querySelectorAll('[data-role="history-delete"]');
    (rows[Math.max(index, 0)] ?? this._role("history-close")).focus();
  }

  _renderHistory(status = null) {
    const lang = pickLanguage(this._hass);
    const entries = this._historyEntries;
    const shown = status ?? (entries.length === 0 ? { key: "history_empty" } : null);
    const statusEl = this._role("history-status");
    statusEl.textContent = shown ? t(lang, shown.key) : "";
    statusEl.hidden = !shown;
    statusEl.classList.toggle("error", Boolean(shown?.error));
    const canDelete = this._printer()?.can_print !== false;
    this._role("history-list").replaceChildren(
      ...entries.map((record) => this._historyRow(lang, record, canDelete)),
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
      open.addEventListener("click", () => this._openPreview(record));
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

  _timeLanguage() {
    return String(this._hass?.locale?.language ?? this._hass?.language ?? "en");
  }

  // Pages are signed just before they load: a signed path lives 300 s, and a
  // request with an expired one is a 401 that HA counts as a failed login.
  _openPreview(record) {
    const entryId = this._historyEntryId;
    if (!entryId) return;
    this._stopPreview();
    const lang = pickLanguage(this._hass);
    this._role("preview-title").textContent = String(record.file_name ?? "");
    const body = this._role("preview-body");
    body.replaceChildren();
    body.scrollTop = 0;
    this._showDialog(this._role("preview-dialog"));
    if (record.file === false) {
      this._previewNote(body, t(lang, "file_gone"));
      return;
    }
    const isImage = String(record.mime ?? "").startsWith("image/");
    const known = Number(record.pages) > 0 ? Number(record.pages) : null;
    const preview = {
      token: this._previewToken,
      body,
      lang,
      entryId,
      recordId: record.id,
      // null: unknown, pages are added one by one until one is missing.
      count: isImage ? 1 : known,
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

  async _signPage(preview, page) {
    const result = await this._hass.callWS({
      type: "auth/sign_path",
      path: previewPath(preview.entryId, preview.recordId, page),
      expires: PREVIEW_SIGN_SECONDS,
    });
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
    this._setMessage(t(lang, "uploading"));
    const entryId = printer.entry_id;
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

  // ------------------------------------------------------------ job polling

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
    }
    else {
      this._setMessage(t(lang, "job_checking"));
      if (this.isConnected) this._schedulePoll();
      return;
    }
    // The server has recorded the final state; show it in an open history.
    if (this._historyEntryId === job.entryId) this._loadHistory();
  }

  _finish(text, kind, detail = "") {
    clearTimeout(this._pollTimer);
    this._pollTimer = null;
    this._job = null;
    this._uploading = false;
    this._setMessage(text, kind, detail);
  }

  _setMessage(text, kind = "info", detail = "") {
    this._message = { text, kind, detail };
    this._update();
  }

  // ------------------------------------------------------------ rendering

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
    this._role("title").textContent = this._config.title || printer?.title || "Home Print";
    this._role("state").textContent = printer ? this._statusText(lang, printer) : "";
    this._role("state-dash").hidden = !printer;
    this._renderPicker(lang, printers, printer, unknown);
    this._applyPrinter(printer);
    this._renderInk(lang, printer);
    this._renderOptions(printer);
    this._renderFile(lang, printer);
    this._role("print").disabled = !this._canSubmit(printer);
    this._role("history-button").hidden = !printer;
    const pick = this._role("pick");
    if (isIOS(globalThis.navigator)) {
      pick.removeAttribute("aria-haspopup");
      pick.removeAttribute("aria-expanded");
    } else {
      pick.setAttribute("aria-haspopup", "menu");
      pick.setAttribute("aria-expanded", String(!this._role("pick-menu").hidden));
    }
    // The open history belongs to one printer; another one closes it.
    if (this._historyEntryId && this._historyEntryId !== printer?.entry_id) this._closeHistory();
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
    const entity = this._entityState(printer.entities?.status)?.state;
    const state = KNOWN_STATES.includes(entity) ? entity : printer.state;
    let text = KNOWN_STATES.includes(state) ? t(lang, `state_${state}`) : t(lang, "state_unknown");
    if (this._entityState(printer.entities?.problem)?.state === "on") {
      text += ` · ${t(lang, "problem")}`;
    }
    return text;
  }

  _renderPicker(lang, printers, printer, unknown) {
    const slot = this._role("picker-slot");
    const show = printers.length > 1 || (unknown && printers.length > 0);
    if (!show) {
      slot.replaceChildren();
      this._pickerKey = "";
      return;
    }
    const key = JSON.stringify([unknown, printers.map((p) => [p.entry_id, p.title])]);
    let select = slot.querySelector("select");
    if (!select || key !== this._pickerKey) {
      select = document.createElement("select");
      select.dataset.role = "picker";
      select.addEventListener("change", (ev) => this._onPick(ev));
      const option = (label, value) => {
        const el = document.createElement("option");
        el.value = value;
        el.textContent = label;
        return el;
      };
      if (unknown) select.append(option("—", ""));
      for (const p of printers) select.append(option(p.title || p.entry_id, p.entry_id));
      slot.replaceChildren(select);
      this._pickerKey = key;
    }
    select.setAttribute("aria-label", t(lang, "picker"));
    select.value = printer?.entry_id ?? "";
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
    const message = this._role("message");
    const check = this._fileCheck(printer);
    let shown = this._message;
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
        markers.push({ entityId, level: Math.min(100, Math.max(0, level)), attrs: entity.attributes ?? {} });
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

HomePrintCard.helpers = Object.freeze({
  pickLanguage,
  t,
  isWordFile,
  validateFile,
  buildForm,
  jobLabel,
  reasonLabel,
  visibleRawReasons,
  isProblemState,
  isIOS,
  formatHistoryTime,
  historyStateIcon,
});

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, HomePrintCard);
}

// ---------------------------------------------------------------- editor

const EDITOR_STYLE = `
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

const EDITOR_TEMPLATE = `
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

class HomePrintCardEditor extends HTMLElement {
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

if (!customElements.get(EDITOR_TYPE)) {
  customElements.define(EDITOR_TYPE, HomePrintCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: "Home Print",
    description:
      "Yazıcıya dosya gönder ve durumu izle. / Send files to a printer and monitor its status.",
  });
}
