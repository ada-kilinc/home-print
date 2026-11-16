/* Home Print dashboard card.
 *
 * A single, build-free Web Component. It lists printers through the
 * `home_print/printers` WebSocket command, uploads files to
 * `/api/home_print/upload/<entry_id>` with `hass.fetchWithAuth` and follows the
 * job with `home_print/job`.
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
const PRINTER_ERROR_LIMIT = 3;
const KNOWN_STATES = ["idle", "processing", "stopped"];

const STRINGS = {
  tr: {
    choose_file: "Dosya seç",
    choose_photo: "Fotoğraf seç",
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
    last: "Son: {name} {mark} {time}",
    last_user: " — {user}",
    picker: "Yazıcı",
    loading: "Yazıcılar yükleniyor…",
    load_failed:
      "Yazıcı listesi alınamadı. Home Print hâlâ yükleniyor olabilir, birazdan tekrar denerim. Sürerse entegrasyonun kurulu olduğuna bak.",
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
    choose_photo: "Choose photo",
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
    last: "Last: {name} {mark} {time}",
    last_user: " — {user}",
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

function jobLabel(lang, status) {
  const state = status?.state;
  const raw = Array.isArray(status?.reasons) ? status.reasons : [];
  const reasons = [...new Set(raw.map((reason) => reasonLabel(lang, reason)).filter(Boolean))];
  const withReasons = (key) =>
    t(lang, key) + (reasons.length ? t(lang, "job_reasons", { reasons: reasons.join(", ") }) : "");
  switch (state) {
    case "pending":
    case "processing":
      return t(lang, "job_printing");
    case "held":
      return t(lang, "job_held");
    case "stopped":
      return withReasons("job_stopped");
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

function formatTime(iso, lang) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const locale = lang === "tr" ? "tr-TR" : "en-GB";
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === new Date().toDateString()) return time;
  return `${date.toLocaleDateString(locale, { day: "numeric", month: "short" })} ${time}`;
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
  .file-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; }
  .file-button {
    position: relative;
    flex: none;
    display: inline-flex;
    align-items: center;
    min-height: 44px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid var(--primary-color);
    color: var(--primary-color);
    cursor: pointer;
  }
  .file-button input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }
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
  .last {
    color: var(--secondary-text-color);
    font-size: 0.9em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
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
      </div>
      <div class="notice" data-role="notice" role="alert" hidden></div>
      <div class="ink" data-role="ink"></div>
      <div class="file-row">
        <label class="file-button">
          <input type="file" data-role="file" accept="${ACCEPT}" />
          <span data-t="choose_file"></span>
        </label>
        <label class="file-button">
          <input type="file" data-role="photo" accept="${PHOTO_ACCEPT}" />
          <span data-t="choose_photo"></span>
        </label>
        <span class="file-name" data-role="file-name"></span>
        <span class="file-size" data-role="file-size"></span>
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
      <div class="last" data-role="last"></div>
    </div>
  </ha-card>
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
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = TEMPLATE;
    for (const name of ["file", "photo"]) {
      this._role(name).addEventListener("change", (ev) => this._onFile(ev));
    }
    this._role("print").addEventListener("click", () => this._onPrint());
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
    if (!this._uploading && !this._job) this._message = null;
    this._update();
  }

  _onPick(ev) {
    this._pickedId = ev.target.value || null;
    this._update();
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
    for (const name of ["file", "photo"]) this._role(name).value = "";
    this._job = {
      entryId,
      jobId: body.job_id,
      started: Date.now(),
      printerErrors: 0,
      troubleSince: null,
    };
    this._setMessage(jobLabel(lang, { state: "pending" }));
    this._schedulePoll();
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
    const label = jobLabel(lang, status);
    if (RUNNING_JOB_STATES.includes(status?.state)) {
      this._setMessage(label, status.state === "stopped" ? "error" : "info");
      if (this.isConnected) this._schedulePoll();
      return;
    }
    if (status?.state === "completed") this._finish(label, "success");
    else if (status?.state === "canceled" || status?.state === "aborted") this._finish(label, "error");
    else {
      this._setMessage(t(lang, "job_checking"));
      if (this.isConnected) this._schedulePoll();
    }
  }

  _finish(text, kind) {
    clearTimeout(this._pollTimer);
    this._pollTimer = null;
    this._job = null;
    this._uploading = false;
    this._setMessage(text, kind);
  }

  _setMessage(text, kind = "info") {
    this._message = { text, kind };
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
    this._renderLast(lang, printer);
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

  _renderLast(lang, printer) {
    const last = this._role("last");
    const entity = this._entityState(printer?.entities?.last_job);
    const name = entity?.state;
    if (!entity || !name || name === "unknown" || name === "unavailable") {
      last.textContent = "";
      last.hidden = true;
      return;
    }
    const attrs = entity.attributes ?? {};
    const mark =
      attrs.state === "completed"
        ? "✓"
        : ["aborted", "canceled", "error"].includes(attrs.state)
          ? "✗"
          : "…";
    let text = t(lang, "last", { name, mark, time: formatTime(attrs.time, lang) }).trim();
    if (attrs.user) text += t(lang, "last_user", { user: attrs.user });
    last.textContent = text;
    last.title = text;
    last.hidden = false;
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
