/* Home Print dashboard card.
 *
 * Built from frontend/src/ with `npm run build`: edit those files, not this one.
 *
 * It lists printers through the `home_print/printers` WebSocket command,
 * uploads files to `/api/home_print/upload/<entry_id>` with
 * `hass.fetchWithAuth` and follows the job with `home_print/job`. A clock
 * button opens the print history (`home_print/history`,
 * `home_print/history/delete`) and a page preview served by
 * `/api/home_print/history/<entry_id>/<id>/page/<n>`.
 *
 * A printer with a scanner splits the card body into Print and Scan tabs; the
 * Scan tab starts `home_print/scan/start`, polls `home_print/scan/state`
 * (stopped with `home_print/scan/cancel`) and shows the result. The history
 * dialog then has a second tab listing `home_print/scans`.
 */

// frontend/src/constants.js
var CARD_TYPE = "home-print-card";
var EDITOR_TYPE = "home-print-card-editor";
var REFRESH_MS = 60 * 1e3;
var POLL_MS = 3 * 1e3;
var POLL_LIMIT_MS = 10 * 60 * 1e3;
var STALL_MS = 30 * 1e3;
var UPLOAD_TIMEOUT_MS = 330 * 1e3;
var EDITOR_RETRY_MS = 30 * 1e3;
var PAGE_RANGES_RE = /^\s*\d+(\s*-\s*\d*)?(\s*,\s*\d+(\s*-\s*\d*)?)*\s*$/;
var ACCEPT = "application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png";
var PHOTO_ACCEPT = "image/jpeg,image/png";
var CAMERA_ACCEPT = "image/*";
var FILE_INPUTS = ["input-file", "input-photo", "input-camera"];
var PREVIEW_SIGN_SECONDS = 300;
var PREVIEW_RESIGN_MS = 240 * 1e3;
var PREVIEW_MARGIN = "800px 0px";
var DOWNLOAD_SIGN_SECONDS = 60;
var SCAN_POLL_MS = 1500;
var SCAN_POLL_LIMIT_MS = 10 * 60 * 1e3;
var CONFIRM_MS = 4 * 1e3;
var SCAN_SELECTS = ["scan-source", "scan-color", "scan-resolution", "scan-format"];
var SCAN_ERRORS = [
  "scanner_busy",
  "scanner_unavailable",
  "adf_empty",
  "invalid_option",
  "bad_scan",
  "too_large",
  "too_many_pages",
  "not_found",
  "no_scanner",
  "unauthorized",
  "scan_failed",
  "canceled",
  "invalid_crop",
  "scan_running"
];
var FATAL_SCAN_ERRORS = ["not_found", "no_scanner", "unauthorized"];
var DEFAULT_FORMATS = ["application/pdf", "image/jpeg", "image/png"];
var EXT_FORMATS = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png"
};
var WORD_EXTS = ["doc", "docx", "odt", "rtf"];
var WORD_TYPES = [
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.oasis.opendocument.text",
  "application/rtf",
  "text/rtf"
];
var RUNNING_JOB_STATES = ["pending", "held", "processing", "stopped"];
var FATAL_JOB_ERRORS = ["not_found", "unauthorized"];
var REASONS = [
  [["media-empty", "media-needed"], "reason_media_empty"],
  [["media-jam"], "reason_media_jam"],
  [["marker-supply-empty", "toner-empty"], "reason_ink_empty"],
  [["door-open", "cover-open"], "reason_cover_open"]
];
var NOISE_REASONS = [
  "none",
  "job-printing",
  "job-incoming",
  "job-queued",
  "processing-to-stop-point",
  "job-data-insufficient",
  "job-completed-successfully"
];
var PRINTER_ERROR_LIMIT = 3;
var KNOWN_STATES = ["idle", "processing", "stopped"];
var SCANNER_STATES = ["idle", "scanning", "adf_loaded", "stopped"];
var HISTORY_STATES = ["sent", "completed", "aborted", "canceled", "error"];
var CROP_DETECT_SIZE = 256;
var CROP_KEY_STEP = 0.01;
var CROP_KEY_STEP_BIG = 0.05;

// frontend/src/i18n.js
var STRINGS = {
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
    scanner_state_idle: "Hazır",
    scanner_state_scanning: "Tarıyor",
    scanner_state_adf_loaded: "Besleyicide kâğıt var",
    scanner_state_stopped: "Durdu",
    problem: "Sorun var",
    ink_black: "Siyah",
    ink_color: "Renkli",
    percent: "%{value}",
    picker: "Yazıcı",
    tab_print: "Yazdır",
    tab_scan: "Tara",
    switch_printer: "Yazıcı değiştir",
    loading: "Yazıcılar yükleniyor…",
    load_failed: "Yazıcı listesi alınamadı. Home Print hâlâ yükleniyor olabilir, birazdan tekrar denerim. Böyle sürerse entegrasyonun kurulu olup olmadığına bak.",
    no_printers: "Yazıcı görünmüyor. Home Print hâlâ yükleniyor olabilir, birazdan tekrar bakarım. Hiç eklemediysen önce entegrasyonu ekle.",
    unknown_printer: "Kartta ayarlı yazıcı ({id}) şu an listede yok. Entegrasyon hâlâ yükleniyor olabilir; silindiyse kart ayarlarından başka bir yazıcı seç.",
    not_allowed: "Bu yazıcıyla yalnızca yöneticiler yazdırabilir.",
    word_file: "Word dosyalarını şimdilik yazdıramıyorum. Dosyayı önce PDF olarak kaydet (telefonda: Paylaş → PDF olarak yazdır/kaydet).",
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
    job_pausing_duplex: "Yazıcı bekliyor… Çift taraflı baskıda arka yüz öncesi mürekkebin kuruması beklenir.",
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
    upload_timeout: "Yükleme çok uzun sürdü. İş yine de yazdırılmış olabilir, tekrar denemeden önce yazıcıya bak.",
    reason_media_empty: "Kâğıt bitti",
    reason_media_jam: "Kâğıt sıkıştı",
    reason_ink_empty: "Mürekkep bitti",
    reason_cover_open: "Kapak açık",
    reason_canceled_at_device: "Yazıcıdan iptal edildi",
    scan: "Tara",
    scan_source: "Kaynak",
    scan_color: "Renk",
    scan_resolution: "Çözünürlük",
    scan_format: "Format",
    scan_source_platen: "Cam",
    scan_source_adf: "Besleyici",
    scan_source_adf_duplex: "Besleyici (çift taraf)",
    scan_color_color: "Renkli",
    scan_color_gray: "Siyah-beyaz",
    scan_color_bw: "Siyah-beyaz",
    scan_color_bw_sharp: "Siyah-beyaz (keskin)",
    scan_format_pdf: "PDF",
    scan_format_jpeg: "JPEG",
    scan_dpi: "{n} dpi",
    scan_start: "Taramayı başlat",
    scan_cancel: "İptal",
    scan_scanning: "Taranıyor…",
    scan_scanning_page: "Taranıyor… ({n}. sayfa)",
    scan_saving: "Kaydediliyor…",
    scan_done: "Tarama hazır ✓",
    scan_saved: "Tarama kaydedildi. Geçmiş > Taramalar'da bulabilirsin.",
    scan_deleted: "Tarama silindi.",
    scan_lost: "Taramanın durumu alınamıyor. Taramalar listesine bak.",
    scan_timeout: "Tarama çok uzun sürdü, yazıcıya bak.",
    scan_page_of: "Sayfa {n}/{total}",
    scan_prev: "Önceki sayfa",
    scan_next: "Sonraki sayfa",
    scan_name: "Ad",
    scan_download: "İndir",
    scan_add_page: "Sayfa ekle",
    confirm_delete: "Emin misin?",
    rename_failed: "Ad değiştirilemedi. Birazdan tekrar dene.",
    edit_not_allowed: "Bunu yalnızca yöneticiler yapabilir.",
    download_failed: "İndirilemedi. Birazdan tekrar dene.",
    tab_prints: "Baskılar",
    tab_scans: "Taramalar",
    scans_empty: "Henüz tarama yok.",
    scan_error_scanner_busy: "Tarayıcı şu an meşgul.",
    scan_error_scanner_unavailable: "Tarayıcıya ulaşılamadı.",
    update_available: "Home Print {version} sürümüne güncellendi.",
    update_reload: "Yenile",
    update_restart_needed: "Home Print {version} yüklendi. Bitmesi için Home Assistant'ın yeniden başlaması gerekiyor.",
    update_restart: "Yeniden başlat",
    update_restart_confirm: "Emin misin?",
    update_restarting: "Home Assistant yeniden başlıyor…",
    crop: "Kırp",
    crop_title: "Sayfa {n}: kırp",
    crop_save: "Kırp",
    crop_full: "Tüm sayfa",
    crop_cancel: "Vazgeç",
    crop_hint: "Köşeleri sürükleyerek kırpılacak alanı seç.",
    crop_found: "Kâğıdın kenarları bulundu. Gerekirse köşeleri düzelt.",
    crop_saving: "Kırpılıyor…",
    crop_failed: "Sayfa kırpılamadı.",
    crop_done: "Sayfa {n} kırpıldı.",
    crop_corner_nw: "Sol üst köşe",
    crop_corner_ne: "Sağ üst köşe",
    crop_corner_sw: "Sol alt köşe",
    crop_corner_se: "Sağ alt köşe",
    crop_frame: "Kırpma alanı",
    scan_error_invalid_crop: "Kırpma alanı geçersiz.",
    scan_error_scan_running: "Tarama sürerken kırpılamaz.",
    scan_error_adf_empty: "Besleyicide kâğıt yok.",
    scan_error_invalid_option: "Tarayıcı bu ayarı desteklemiyor. Başka bir ayar seç.",
    scan_error_bad_scan: "Tarayıcıdan gelen görüntü okunamadı. Tekrar dene.",
    scan_error_too_large: "Tarama çok büyük. Daha düşük bir çözünürlük seç.",
    scan_error_too_many_pages: "Sayfa sayısı çok fazla. Belgeyi parça parça tara.",
    scan_error_not_found: "Belge bulunamadı, silinmiş olabilir.",
    scan_error_no_scanner: "Bu yazıcıda tarayıcı yok.",
    scan_error_unauthorized: "Bu yazıcıda yalnızca yöneticiler tarayabilir.",
    scan_error_scan_failed: "Tarama yapılamadı. Birazdan tekrar dene.",
    scan_error_canceled: "Tarama iptal edildi."
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
    scanner_state_idle: "Ready",
    scanner_state_scanning: "Scanning",
    scanner_state_adf_loaded: "Paper in the feeder",
    scanner_state_stopped: "Stopped",
    problem: "Needs attention",
    ink_black: "Black",
    ink_color: "Colour",
    percent: "{value}%",
    picker: "Printer",
    tab_print: "Print",
    tab_scan: "Scan",
    switch_printer: "Switch printer",
    loading: "Loading printers…",
    load_failed: "Couldn't load the printer list. Home Print may still be loading; I'll try again shortly. If this persists, check that the integration is installed.",
    no_printers: "No printers listed. Home Print may still be loading; I'll check again shortly. If you haven't added one yet, add the integration first.",
    unknown_printer: "The printer set for this card ({id}) isn't listed right now. The integration may still be loading; if it was removed, pick another printer in the card settings.",
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
    job_pausing_duplex: "The printer is pausing… With two-sided printing it waits for the ink to dry before the back side.",
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
    upload_timeout: "The upload took too long. The job may still have printed; check the printer before trying again.",
    reason_media_empty: "Out of paper",
    reason_media_jam: "Paper jam",
    reason_ink_empty: "Out of ink",
    reason_cover_open: "Cover open",
    reason_canceled_at_device: "Cancelled at the printer",
    scan: "Scan",
    scan_source: "Source",
    scan_color: "Colour",
    scan_resolution: "Resolution",
    scan_format: "Format",
    scan_source_platen: "Glass",
    scan_source_adf: "Document feeder",
    scan_source_adf_duplex: "Document feeder (two-sided)",
    scan_color_color: "Colour",
    scan_color_gray: "Black and white",
    scan_color_bw: "Black and white",
    scan_color_bw_sharp: "Black and white (sharp)",
    scan_format_pdf: "PDF",
    scan_format_jpeg: "JPEG",
    scan_dpi: "{n} dpi",
    scan_start: "Start scan",
    scan_cancel: "Cancel",
    scan_scanning: "Scanning…",
    scan_scanning_page: "Scanning… (page {n})",
    scan_saving: "Saving…",
    scan_done: "Scan ready ✓",
    scan_saved: "Scan saved. You'll find it under History > Scans.",
    scan_deleted: "Scan deleted.",
    scan_lost: "Can't get the scan's status. Check the Scans list.",
    scan_timeout: "The scan took too long, check the printer.",
    scan_page_of: "Page {n}/{total}",
    scan_prev: "Previous page",
    scan_next: "Next page",
    scan_name: "Name",
    scan_download: "Download",
    scan_add_page: "Add page",
    confirm_delete: "Sure?",
    rename_failed: "Couldn't rename it. Try again shortly.",
    edit_not_allowed: "Only administrators can do this.",
    download_failed: "Couldn't download it. Try again shortly.",
    tab_prints: "Prints",
    tab_scans: "Scans",
    scans_empty: "No scans yet.",
    scan_error_scanner_busy: "The scanner is busy right now.",
    scan_error_scanner_unavailable: "Couldn't reach the scanner.",
    update_available: "Home Print was updated to {version}.",
    update_reload: "Reload",
    update_restart_needed: "Home Print {version} is installed. Home Assistant needs to restart to finish the update.",
    update_restart: "Restart",
    update_restart_confirm: "Sure?",
    update_restarting: "Home Assistant is restarting…",
    crop: "Crop",
    crop_title: "Page {n}: crop",
    crop_save: "Crop",
    crop_full: "Whole page",
    crop_cancel: "Cancel",
    crop_hint: "Drag the corners to choose the area to keep.",
    crop_found: "Found the paper's edges. Adjust the corners if needed.",
    crop_saving: "Cropping…",
    crop_failed: "Couldn't crop the page.",
    crop_done: "Page {n} cropped.",
    crop_corner_nw: "Top left corner",
    crop_corner_ne: "Top right corner",
    crop_corner_sw: "Bottom left corner",
    crop_corner_se: "Bottom right corner",
    crop_frame: "Crop area",
    scan_error_invalid_crop: "The crop area is not valid.",
    scan_error_scan_running: "Can't crop while a scan is running.",
    scan_error_adf_empty: "The document feeder is empty.",
    scan_error_invalid_option: "The scanner doesn't support this setting. Pick another one.",
    scan_error_bad_scan: "Couldn't read the image from the scanner. Try again.",
    scan_error_too_large: "The scan is too large. Pick a lower resolution.",
    scan_error_too_many_pages: "Too many pages. Scan the document in parts.",
    scan_error_not_found: "Document not found; it may have been deleted.",
    scan_error_no_scanner: "This printer has no scanner.",
    scan_error_unauthorized: "Only administrators can scan on this printer.",
    scan_error_scan_failed: "The scan failed. Try again shortly.",
    scan_error_canceled: "Scan canceled."
  }
};
function pickLanguage(hass) {
  const language = hass?.locale?.language ?? hass?.language ?? "en";
  return String(language).toLowerCase().startsWith("tr") ? "tr" : "en";
}
function t(lang, key, vars = {}) {
  const template = STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
  return template.replace(
    /\{(\w+)\}/g,
    (match, name) => name in vars ? String(vars[name]) : match
  );
}

// frontend/src/helpers.js
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
    if (value === void 0 || value === null || String(value).trim() === "") continue;
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
function isAuthError(err, hass) {
  if (hass?.auth?.expired === true) return true;
  if (err?.status === 401 || err?.code === 401) return true;
  const text = `${err?.message ?? ""} ${err?.code ?? ""}`.toLowerCase();
  return ["auth", "token", "401"].some((word) => text.includes(word));
}
function visibleRawReasons(reasons) {
  const raw = Array.isArray(reasons) ? reasons.map((r) => String(r ?? "")) : [];
  return [
    ...new Set(raw.filter((r) => r && !NOISE_REASONS.includes(r) && reasonLabel("en", r) === null))
  ];
}
function knownReasons(lang, status) {
  const raw = Array.isArray(status?.reasons) ? status.reasons : [];
  return [...new Set(raw.map((reason) => reasonLabel(lang, reason)).filter(Boolean))];
}
function isProblemState(status, lang = "en") {
  return status?.state === "stopped" && knownReasons(lang, status).length > 0;
}
function jobLabel(lang, status, { twoSided: twoSided2 = false } = {}) {
  const state2 = status?.state;
  const reasons = knownReasons(lang, status);
  const withReasons = (key) => t(lang, key) + (reasons.length ? t(lang, "job_reasons", { reasons: reasons.join(", ") }) : "");
  const pausing = () => t(lang, twoSided2 ? "job_pausing_duplex" : "job_pausing");
  switch (state2) {
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
function twoSided(printer) {
  const sides = printer?.capabilities?.sides ?? [];
  const preferred = printer?.defaults?.sides;
  if (String(preferred ?? "").startsWith("two-sided") && sides.includes(preferred))
    return preferred;
  if (sides.includes("two-sided-long-edge")) return "two-sided-long-edge";
  return sides.find((s) => s.startsWith("two-sided"));
}
function formatSize(bytes, lang) {
  const locale = lang === "tr" ? "tr-TR" : "en-US";
  const fmt = (n) => n.toLocaleString(locale, { maximumFractionDigits: 1 });
  if (bytes >= 1024 * 1024) return `${fmt(bytes / (1024 * 1024))} MB`;
  return `${fmt(Math.max(bytes, 1) / 1024)} KB`;
}
function isIOS(nav) {
  if (!nav) return false;
  return /iPad|iPhone|iPod/.test(String(nav.userAgent ?? "")) || nav.platform === "MacIntel" && nav.maxTouchPoints > 1;
}
function usesPickMenu(nav, win) {
  if (!nav || isIOS(nav)) return false;
  const mm = win?.matchMedia;
  if (typeof mm !== "function") return (nav.maxTouchPoints ?? 0) > 0;
  const query = (q) => Boolean(mm.call(win, q)?.matches);
  return query("(pointer: coarse)") && !query("(any-pointer: fine)");
}
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
function historyStateIcon(state2) {
  if (state2 === "completed") return "✓";
  if (["aborted", "canceled", "error"].includes(state2)) return "✗";
  return "…";
}
function previewPath(entryId, recordId, page) {
  return `/api/home_print/history/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/page/${page}`;
}
function scanPagePath(entryId, recordId, page) {
  return `/api/home_print/scans/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/page/${page}`;
}
function scanFilePath(entryId, recordId) {
  return `/api/home_print/scans/${encodeURIComponent(entryId)}/${encodeURIComponent(recordId)}/file`;
}
function scanErrorText(lang, code) {
  const name = code === "printer_unavailable" ? "scanner_unavailable" : String(code ?? "");
  return t(lang, SCAN_ERRORS.includes(name) ? `scan_error_${name}` : "scan_error_scan_failed");
}
var SCAN_COLOR_ORDER = ["color", "gray", "bw"];
function scanColorChoices(modes) {
  const known = SCAN_COLOR_ORDER.filter((mode) => modes.includes(mode));
  return [...known, ...modes.filter((mode) => !SCAN_COLOR_ORDER.includes(mode))];
}
function scanColorLabel(lang, mode, modes) {
  if (mode === "bw" && modes.includes("gray")) return t(lang, "scan_color_bw_sharp");
  return scanOptionLabel(lang, "color", mode);
}
function scanOptionLabel(lang, kind, value) {
  if (kind === "resolution") return t(lang, "scan_dpi", { n: value });
  const key = `scan_${kind}_${value}`;
  return key in STRINGS.en ? t(lang, key) : String(value);
}
function storageKey(entryId) {
  return `home-print-card:printer:${entryId ?? ""}`;
}
function readStored(key) {
  try {
    const value = globalThis.localStorage?.getItem(key);
    return typeof value === "string" && value ? value : null;
  } catch (_err) {
    return null;
  }
}
function writeStored(key, value) {
  try {
    globalThis.localStorage?.setItem(key, value);
  } catch (_err) {
  }
}
function detectPaper(image) {
  const { width: w, height: h, data } = image ?? {};
  if (!data || w < 16 || h < 16) return null;
  const lum = new Float32Array(w * h);
  for (let i = 0; i < w * h; i += 1) {
    lum[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
  }
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
        Math.abs(data[i + 2] - bg[2])
      );
      const edge = Math.abs(blur[p + 1] - blur[p - 1]) + Math.abs(blur[p + w] - blur[p - w]);
      if (colorDiff > COLOR_DIFF || edge > EDGE_DIFF) {
        rows[y] += 1;
        cols[x] += 1;
      }
    }
  }
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
  if (box.width * box.height > 0.95 || box.width < 0.05 || box.height < 0.05) return null;
  return box;
}
function clampCropBox(box, min = 0.05) {
  const width = Math.min(1, Math.max(min, box.width));
  const height = Math.min(1, Math.max(min, box.height));
  const x = Math.min(1 - width, Math.max(0, box.x));
  const y = Math.min(1 - height, Math.max(0, box.y));
  return { x, y, width, height };
}
function moveCropCorner(box, corner, dx, dy, min = 0.05) {
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

// frontend/src/crop.js
var FULL_PAGE = Object.freeze({ x: 0, y: 0, width: 1, height: 1 });
var CropPart = class {
  // spec: { entryId, record, page, onDone(record, page) }
  // The arrows move between the scan's pages; each page keeps its own frame
  // while the dialog is open, and Crop saves the page shown.
  _openCrop(spec) {
    this._closeCrop();
    const lang = pickLanguage(this._hass);
    const crop = {
      spec,
      lang,
      record: spec.record,
      page: spec.page,
      // Frames already moved on other pages, by page number.
      boxes: /* @__PURE__ */ new Map(),
      box: { ...FULL_PAGE },
      found: false,
      drag: null,
      saving: false,
      load: 0
    };
    this._crop = crop;
    this._cropToken += 1;
    this._showDialog(this._role("crop-dialog"));
    this._showCropPage(crop);
  }
  _cropTotal(crop) {
    return Math.max(1, Number(crop.record.pages) || 1);
  }
  _showCropPage(crop, note = null) {
    const { lang } = crop;
    const total = this._cropTotal(crop);
    this._role("crop-title").textContent = t(lang, "crop_title", { n: crop.page });
    this._role("crop-nav").hidden = total <= 1;
    this._role("crop-page-label").textContent = t(lang, "scan_page_of", { n: crop.page, total });
    this._role("crop-frame").hidden = true;
    this._setCropStatus(note ?? t(lang, "history_loading"));
    this._renderCropButtons();
    this._loadCropImage(crop, note);
  }
  _onCropPage(step) {
    const crop = this._crop;
    if (!crop || crop.saving) return;
    const page = Math.min(Math.max(1, crop.page + step), this._cropTotal(crop));
    if (page === crop.page) return;
    if (!this._role("crop-frame").hidden) crop.boxes.set(crop.page, { ...crop.box });
    crop.drag = null;
    crop.page = page;
    this._showCropPage(crop);
  }
  async _loadCropImage(crop, note = null) {
    const { spec, lang } = crop;
    const load = ++crop.load;
    const live = () => crop === this._crop && load === crop.load;
    let path;
    try {
      path = await this._signPath(scanPagePath(spec.entryId, crop.record.id, crop.page));
    } catch (_err) {
      if (live()) this._setCropStatus(t(lang, "preview_failed"), true);
      return;
    }
    if (!live()) return;
    const img = document.createElement("img");
    img.dataset.role = "crop-img";
    img.draggable = false;
    img.alt = t(lang, "preview_page", { n: crop.page });
    this._role("crop-img")?.remove();
    this._role("crop-stage").prepend(img);
    img.onload = () => {
      if (!live()) return;
      const kept = crop.boxes.get(crop.page);
      const found = kept ? null : this._findPaper(img);
      crop.found = Boolean(found);
      crop.box = kept ?? found ?? { ...FULL_PAGE };
      this._role("crop-frame").hidden = false;
      this._setCropStatus(note ?? t(lang, kept ? "crop_hint" : found ? "crop_found" : "crop_hint"));
      this._renderCrop();
    };
    img.onerror = () => {
      if (live()) this._setCropStatus(t(lang, "preview_failed"), true);
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
    const total = crop ? this._cropTotal(crop) : 1;
    this._role("crop-prev").disabled = !crop || crop.saving || crop.page <= 1;
    this._role("crop-next").disabled = !crop || crop.saving || crop.page >= total;
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
      height: rect.height
    };
    ev.target.setPointerCapture?.(ev.pointerId);
  }
  _onCropPointerMove(ev) {
    const drag = this._crop?.drag;
    if (!drag || drag.id !== ev.pointerId) return;
    ev.preventDefault();
    const dx = (ev.clientX - drag.startX) / drag.width;
    const dy = (ev.clientY - drag.startY) / drag.height;
    this._crop.box = drag.corner ? moveCropCorner(drag.startBox, drag.corner, dx, dy) : clampCropBox({ ...drag.startBox, x: drag.startBox.x + dx, y: drag.startBox.y + dy });
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
      ArrowDown: [0, step]
    };
    const move = moves[ev.key];
    if (!move) return;
    ev.preventDefault();
    const corner = ev.target.closest?.("[data-corner]")?.dataset.corner;
    crop.box = corner ? moveCropCorner(crop.box, corner, move[0], move[1]) : clampCropBox({ ...crop.box, x: crop.box.x + move[0], y: crop.box.y + move[1] });
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
      record = (await this._hass.callWS({
        type: "home_print/scans/crop",
        entry_id: spec.entryId,
        scan_record_id: crop.record.id,
        page: crop.page,
        box: roundBox(crop.box)
      }))?.entry;
    } catch (err) {
      if (crop !== this._crop) return;
      crop.saving = false;
      const code = err?.code;
      this._setCropStatus(code ? scanErrorText(lang, code) : t(lang, "crop_failed"), true);
      this._renderCropButtons();
      return;
    }
    if (crop !== this._crop) return;
    const page = crop.page;
    crop.record = record ?? crop.record;
    crop.saving = false;
    crop.boxes.delete(page);
    spec.onDone?.(crop.record, page);
    if (this._cropTotal(crop) <= 1) {
      this._closeCrop();
      return;
    }
    this._showCropPage(crop, t(lang, "crop_done", { n: page }));
  }
  _closeCrop() {
    if (this._crop) this._crop.drag = null;
    this._crop = null;
    this._cropToken += 1;
    this._role("crop-img")?.remove();
    this._hideDialog(this._role("crop-dialog"));
  }
};
function isFullPage(box) {
  return box.x <= 1e-3 && box.y <= 1e-3 && box.width >= 0.999 && box.height >= 0.999;
}
function roundBox(box) {
  const r = (v) => Math.round(v * 1e4) / 1e4;
  return clampCropBox(
    { x: r(box.x), y: r(box.y), width: r(box.width), height: r(box.height) },
    0.02
  );
}

// frontend/src/icons.js
var ICONS = {
  history: "M13.5,8H12V13L16.28,15.54L17,14.33L13.5,12.25V8M13,3A9,9 0 0,0 4,12H1L4.96,16.03L9,12H6A7,7 0 0,1 13,5A7,7 0 0,1 20,12A7,7 0 0,1 13,19C11.07,19 9.32,18.21 8.06,16.94L6.64,18.36C8.27,20 10.5,21 13,21A9,9 0 0,0 22,12A9,9 0 0,0 13,3",
  delete: "M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19M8,9H16V19H8V9M15.5,4L14.5,3H9.5L8.5,4H5V6H19V4H15.5Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  paperclip: "M16.5,6V17.5A4,4 0 0,1 12.5,21.5A4,4 0 0,1 8.5,17.5V5A2.5,2.5 0 0,1 11,2.5A2.5,2.5 0 0,1 13.5,5V15.5A1,1 0 0,1 12.5,16.5A1,1 0 0,1 11.5,15.5V6H10V15.5A2.5,2.5 0 0,0 12.5,18A2.5,2.5 0 0,0 15,15.5V5A4,4 0 0,0 11,1A4,4 0 0,0 7,5V17.5A5.5,5.5 0 0,0 12.5,23A5.5,5.5 0 0,0 18,17.5V6H16.5Z",
  images: "M22,16V4A2,2 0 0,0 20,2H8A2,2 0 0,0 6,4V16A2,2 0 0,0 8,18H20A2,2 0 0,0 22,16M11,12L13.03,14.71L16,11L20,16H8M2,6V20A2,2 0 0,0 4,22H18V20H4V6",
  camera: "M4,4H7L9,2H15L17,4H20A2,2 0 0,1 22,6V18A2,2 0 0,1 20,20H4A2,2 0 0,1 2,18V6A2,2 0 0,1 4,4M12,7A5,5 0 0,0 7,12A5,5 0 0,0 12,17A5,5 0 0,0 17,12A5,5 0 0,0 12,7M12,9A3,3 0 0,1 15,12A3,3 0 0,1 12,15A3,3 0 0,1 9,12A3,3 0 0,1 12,9Z",
  scanner: "M4.2,10.7L19.8,5L20.5,6.9L6.4,12H19A2,2 0 0,1 21,14V18A2,2 0 0,1 19,20H5A2,2 0 0,1 3,18V12.5C3,11.7 3.5,10.9 4.2,10.7M17,17H19V15H17V17M5,17H15V15H5V17Z",
  download: "M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9Z",
  file_plus: "M13.81 22H6C4.89 22 4 21.11 4 20V4C4 2.9 4.89 2 6 2H14L20 8V13.09C19.67 13.04 19.34 13 19 13S18.33 13.04 18 13.09V9H13V4H6V20H13.09C13.21 20.72 13.46 21.39 13.81 22M23 18H20V15H18V18H15V20H18V23H20V20H23V18Z",
  chevron_left: "M15.41,16.58L10.83,12L15.41,7.41L14,6L8,12L14,18L15.41,16.58Z",
  chevron_right: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  printer: "M18,3H6V7H18M19,12A1,1 0 0,1 18,11A1,1 0 0,1 19,10A1,1 0 0,1 20,11A1,1 0 0,1 19,12M16,19H8V14H16M19,8H5A3,3 0 0,0 2,11V17H6V21H18V17H22V11A3,3 0 0,0 19,8Z",
  // mdi:unfold-more-horizontal
  unfold: "M12,18.17L8.83,15L7.42,16.41L12,21L16.59,16.41L15.17,15M12,5.83L15.17,9L16.58,7.59L12,3L7.41,7.59L8.83,9L12,5.83Z",
  check: "M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z",
  crop: "M7,17V1H5V5H1V7H5V17A2,2 0 0,0 7,19H17V23H19V19H23V17M17,15H19V7C19,5.89 18.1,5 17,5H9V7H17V15Z"
};
var svg = (name) => `<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" focusable="false"><path d="${ICONS[name]}"></path></svg>`;
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

// frontend/src/history.js
var HistoryPart = class {
  _wireDialog(dialog, close) {
    dialog.addEventListener("click", (ev) => {
      if (ev.target === dialog) close();
    });
    dialog.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      ev.preventDefault();
      ev.stopPropagation();
      close();
    });
    dialog.addEventListener("cancel", (ev) => {
      ev.preventDefault();
      close();
    });
  }
  _anyDialogOpen() {
    return ["history-dialog", "preview-dialog", "crop-dialog"].some(
      (name) => this._role(name).open
    );
  }
  _showDialog(dialog) {
    if (dialog.open) return;
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
    const scannerOnly = printer.kind === "scanner";
    this._historyTab = scannerOnly ? "scans" : "prints";
    const tabbed = Boolean(printer.scanner) && !scannerOnly;
    this._role("history-tabs").hidden = !tabbed;
    const panel = this._role("history-panel");
    if (tabbed) panel.setAttribute("role", "tabpanel");
    else panel.removeAttribute("role");
    this._historyEntries = [];
    this._deletedIds = /* @__PURE__ */ new Set();
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
    this._deletedIds = /* @__PURE__ */ new Set();
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
      this._renderHistory({ key: "history_failed", error: true });
      return;
    }
    if (token !== this._historyToken) return;
    const entries = Array.isArray(result?.entries) ? result.entries : [];
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
        scans ? { type: "home_print/scans/delete", entry_id: entryId, scan_record_id: record.id } : { type: "home_print/history/delete", entry_id: entryId, history_id: record.id }
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
    if (this._historyTab !== (scans ? "scans" : "prints")) return;
    this._deletedIds.add(record.id);
    const index = this._historyEntries.findIndex((e) => e.id === record.id);
    this._historyEntries = this._historyEntries.filter((e) => e.id !== record.id);
    this._renderHistory();
    const rows = this._role("history-list").querySelectorAll(
      '[data-role="history-delete"], [data-role="scan-row-delete"]'
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
      ...entries.map(
        (record) => scans ? this._scanRow(lang, record, canDelete) : this._historyRow(lang, record, canDelete)
      )
    );
  }
  _historyRow(lang, record, canDelete) {
    const row = document.createElement("li");
    row.className = "history-item";
    row.dataset.role = "history-item";
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
          pagePath: (page) => previewPath(entryId, record.id, page)
        });
      });
    }
    const state2 = HISTORY_STATES.includes(record.state) ? record.state : "sent";
    const icon = historyStateIcon(state2);
    const mark = document.createElement("span");
    mark.className = `history-mark ${icon === "✓" ? "ok" : icon === "✗" ? "bad" : "busy"}`;
    mark.textContent = icon;
    mark.title = t(lang, `history_state_${state2}`);
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
      pages > 0 ? t(lang, pages === 1 ? "history_pages_one" : "history_pages", { n: pages }) : ""
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
    open.addEventListener(
      "click",
      () => this._openPreview({
        title: record.name,
        gone: false,
        isImage: String(record.mime ?? "").startsWith("image/"),
        pages: record.pages,
        pagePath: (page) => scanPagePath(entryId, record.id, page),
        // Cropping is for whoever may change scans.
        crop: canDelete ? { entryId, record } : null
      })
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
      if (!await this._downloadScan(entryId, record) && this._historyEntryId === entryId) {
        this._renderHistory({ key: "download_failed", error: true });
      }
    });
    row.append(download);
    if (canDelete) {
      const trash = this._iconButton(lang, "delete", "delete", "scan-row-delete");
      trash.addEventListener(
        "click",
        () => this._confirmTap(trash, () => this._deleteHistory(record, trash))
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
      observer: null
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
        { root: body, rootMargin: PREVIEW_MARGIN }
      );
    }
    const first = preview.count ?? 1;
    for (let page = 1; page <= first; page += 1) this._addPlaceholder(preview, page);
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
          const target = preview.body.querySelector(`[data-page="${cropped}"]`);
          if (!target?.isConnected) return;
          delete target.dataset.state;
          target.classList.remove("loaded");
          target.replaceChildren();
          this._loadPage(preview, target);
        }
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
};

// frontend/src/print.js
var PrintPart = class {
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
    return !this._uploading && !this._jobHolds(printer) && Boolean(printer) && this._reachable(printer) && printer.can_print !== false && this._fileCheck(printer)?.ok === true;
  }
  _onFile(ev) {
    this._file = ev.target.files?.[0] ?? null;
    for (const name of FILE_INPUTS) {
      const input = this._role(name);
      if (input !== ev.target) input.value = "";
    }
    if (!this._uploading && !this._job) this._message = null;
    this._update();
  }
  _onPickButton() {
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
        { method: "POST", body: form, signal: controller.signal }
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
    if (!response.ok || body?.job_id === void 0 || body?.job_id === null) {
      const text = typeof body?.message === "string" && body.message ? body.message : t(lang, "upload_failed", { status: response.status });
      this._finish(text, "error");
      return;
    }
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
      twoSided: String(form.get("sides") ?? printer.defaults?.sides ?? "").startsWith("two-sided")
    };
    this._setMessage(jobLabel(lang, { state: "pending" }));
    this._schedulePoll();
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
      status = (await this._hass.callWS({
        type: "home_print/job",
        entry_id: job.entryId,
        job_id: job.jobId
      }))?.job;
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
        visibleRawReasons(status.reasons).join(", ")
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
    const modes = caps?.color_modes ?? [];
    this._row("color").hidden = !(modes.includes("color") && modes.includes("monochrome"));
    this._role("options").hidden = this._row("duplex").hidden && this._row("color").hidden;
    const format = this._file ? fileFormat(this._file) : "application/pdf";
    const pdfOk = (caps?.formats ?? []).includes("application/pdf");
    this._row("pages").hidden = !caps || (format === "application/pdf" ? !pdfOk : !caps.page_ranges_passthrough);
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
          attrs: entity.attributes ?? {}
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
      })
    );
  }
};

// frontend/src/scan.js
var ScanPart = class {
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
      format: this._role("scan-format").value
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
        append_to: record.id
      },
      Number(record.pages) || 0
    );
  }
  async _startScan(entryId, request, appendPages = null) {
    const lang = pickLanguage(this._hass);
    const now = Date.now();
    const scan = { entryId, scanId: null, started: now, progressAt: now, appendPages };
    this._scan = scan;
    this._disarmAll();
    if (appendPages === null) this._clearScanResult();
    this._scanMessage = { text: t(lang, "scan_scanning"), kind: "info" };
    this._update();
    let state2;
    try {
      state2 = (await this._hass.callWS({ type: "home_print/scan/start", entry_id: entryId, ...request }))?.scan;
    } catch (err) {
      if (this._scan !== scan) return;
      this._endScan(scanErrorText(lang, err?.code), "error");
      return;
    }
    if (this._scan !== scan) return;
    scan.scanId = state2?.scan_id ?? null;
    if (!scan.scanId) {
      this._endScan(scanErrorText(lang, "scan_failed"), "error");
      return;
    }
    this._scanSeen.add(scan.scanId);
    this._onScanState(scan, state2);
  }
  // A scan the server is running that this card isn't following yet: after
  // a reload, or one started on another screen. A finished last_scan alone
  // is not shown, so a card opened later doesn't pop open on old news.
  _resumeScan(printer) {
    const id = printer.scanner?.active_scan_id;
    if (!id || this._scan || this._scanSeen.has(id) || printer.can_print === false) return;
    this._scanSeen.add(id);
    this._scan = {
      entryId: printer.entry_id,
      scanId: id,
      started: Date.now(),
      progressAt: Date.now(),
      appendPages: null,
      resumed: true
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
    if (Date.now() - scan.progressAt >= SCAN_POLL_LIMIT_MS) {
      this._endScan(t(lang, "scan_timeout"), "error");
      return;
    }
    let state2;
    try {
      state2 = (await this._hass.callWS({
        type: "home_print/scan/state",
        entry_id: scan.entryId,
        scan_id: scan.scanId
      }))?.scan;
    } catch (err) {
      if (this._scan !== scan) return;
      if (FATAL_SCAN_ERRORS.includes(err?.code)) {
        this._endScan(t(lang, "scan_lost"), "error");
        return;
      }
      if (this.isConnected) this._scheduleScanPoll();
      return;
    }
    if (this._scan !== scan) return;
    this._onScanState(scan, state2);
  }
  _onScanState(scan, state2) {
    const lang = pickLanguage(this._hass);
    const progress = `${state2?.state}:${state2?.pages}`;
    if (progress !== scan.progressKey) {
      scan.progressKey = progress;
      scan.progressAt = Date.now();
    }
    switch (state2?.state) {
      case "done": {
        const record = state2.record;
        if (record) {
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
          scanErrorText(lang, state2.error),
          state2.error === "canceled" ? "info" : "error"
        );
        return;
      case "saving":
        this._scanMessage = { text: t(lang, "scan_saving"), kind: "info" };
        break;
      default: {
        const pages = Number(state2?.pages) || 0;
        const text = pages > 0 ? t(lang, "scan_scanning_page", { n: pages + 1 }) : t(lang, "scan_scanning");
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
    let state2;
    try {
      state2 = (await this._hass.callWS({
        type: "home_print/scan/cancel",
        entry_id: scan.entryId,
        scan_id: scan.scanId
      }))?.scan;
    } catch (err) {
      if (this._scan !== scan) return;
      if (FATAL_SCAN_ERRORS.includes(err?.code)) {
        this._endScan(t(pickLanguage(this._hass), "scan_lost"), "error");
        return;
      }
      scan.canceling = false;
      this._update();
      return;
    }
    if (this._scan !== scan) return;
    scan.canceling = false;
    this._onScanState(scan, state2);
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
      deleting: false
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
    const img = document.createElement("img");
    img.dataset.role = "scan-img";
    img.alt = t(lang, "preview_page", { n: result.page });
    img.addEventListener("error", failed);
    img.src = path;
    box.replaceChildren(img);
  }
  _onScanCrop() {
    const result = this._scanResult;
    if (!result || this._scanBusy() || result.deleting) return;
    this._openCrop({
      entryId: result.entryId,
      record: result.record,
      page: result.page,
      onDone: (updated, page) => {
        if (this._scanResult !== result) return;
        result.record = { ...result.record, ...updated };
        if (page === result.page) this._loadScanImage();
        this._reloadScans(result.entryId);
        this._update();
      }
    });
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
    if (name === (result.pendingName ?? result.record.name)) return;
    result.pendingName = name;
    const seq = ++result.renameSeq;
    let entry;
    try {
      entry = (await this._hass.callWS({
        type: "home_print/scans/rename",
        entry_id: result.entryId,
        scan_record_id: result.record.id,
        name
      }))?.entry;
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
      this._clearScanResult();
      this._scanMessage = { text: t(lang, "scan_error_not_found"), kind: "error" };
    } else {
      result.record = entry;
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
        scan_record_id: result.record.id
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
      source
    );
    field("source").hidden = sources.length < 2;
    this._setOptions(
      this._role("scan-color"),
      colors,
      (v) => scanColorLabel(lang, v, colors),
      pick(colors, this._role("scan-color").value, defaults.color_mode)
    );
    this._setOptions(
      this._role("scan-resolution"),
      resolutions,
      (v) => scanOptionLabel(lang, "resolution", v),
      pick(resolutions, this._role("scan-resolution").value, defaults.resolution)
    );
    this._setOptions(
      this._role("scan-format"),
      formats,
      (v) => scanOptionLabel(lang, "format", v),
      pick(formats, this._role("scan-format").value, defaults.format)
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
    const scannerOnly = printer?.kind === "scanner";
    if (!scanner || !editable) this._tab = "print";
    if (scannerOnly) this._tab = "scan";
    const open = this._tab === "scan" && (editable || !scannerOnly);
    const tabbed = Boolean(scanner) && !scannerOnly;
    this._role("body-tabs").hidden = !tabbed;
    const scanTab = this._role("body-tab-scan");
    scanTab.disabled = !editable;
    for (const tab of this._bodyTabs()) {
      const selected = tab.dataset.bodyTab === this._tab;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    }
    const printPanel = this._role("print-panel");
    const scanPanel = this._role("scan-panel");
    printPanel.hidden = open || scannerOnly;
    scanPanel.hidden = !open;
    for (const [panel, tab] of [
      [printPanel, "body-tab-print"],
      [scanPanel, "body-tab-scan"]
    ]) {
      if (tabbed) {
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
    const crop = this._role("scan-crop");
    crop.hidden = !editable;
    crop.disabled = busy || result.deleting;
    const add = this._role("scan-add");
    add.hidden = !editable || record.mime !== "application/pdf" || record.source !== "platen";
    add.disabled = busy;
    const remove = this._role("scan-delete");
    remove.hidden = !editable;
    remove.disabled = busy || result.deleting;
  }
};

// frontend/src/switcher.js
var SwitcherPart = class {
  _selectPrinter(entryId) {
    if (!entryId) return;
    const changed = entryId !== this._printer()?.entry_id;
    this._pickedId = entryId;
    writeStored(this._storageKey, entryId);
    this._update();
    if (changed) this._loadPrinters();
  }
  _listItems() {
    return [...this._role("printer-list").querySelectorAll('[role="option"]')];
  }
  _onSwitcher() {
    if (this._role("printer-list").hidden) this._openList();
    else this._closeList(true);
  }
  _onSwitcherKey(ev) {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
    ev.preventDefault();
    this._openList();
  }
  _openList() {
    const list = this._role("printer-list");
    if (this._role("switcher").hidden || !list.hidden) return;
    list.hidden = false;
    this._role("switcher").setAttribute("aria-expanded", "true");
    document.addEventListener("click", this._onDocumentClickList, true);
    const items = this._listItems();
    (items.find((el) => el.getAttribute("aria-selected") === "true") ?? items[0])?.focus();
  }
  _closeList(focusButton = false) {
    const list = this._role("printer-list");
    document.removeEventListener("click", this._onDocumentClickList, true);
    if (list.hidden) return;
    list.hidden = true;
    this._role("switcher").setAttribute("aria-expanded", "false");
    if (focusButton) this._role("switcher").focus();
  }
  _onListKey(ev) {
    const items = this._listItems();
    const index = items.indexOf(this.shadowRoot.activeElement);
    if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      this._closeList(true);
      return;
    }
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      if (index >= 0) this._chooseFromList(items[index].dataset.entryId);
      return;
    }
    const moves = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: items.length - 1 };
    if (!(ev.key in moves) || items.length === 0) return;
    ev.preventDefault();
    items[(moves[ev.key] + items.length) % items.length].focus();
  }
  _onListClick(ev) {
    const item = ev.target.closest?.('[role="option"]');
    if (item) this._chooseFromList(item.dataset.entryId);
  }
  _chooseFromList(entryId) {
    this._closeList(true);
    this._selectPrinter(entryId);
  }
  // As with the file menu, a null relatedTarget is left to the outside-click
  // handler so a tap on an option in Safari isn't swallowed.
  _onListFocusOut(ev) {
    const next = ev.relatedTarget;
    if (!next || this._role("printer-list").hidden) return;
    if (this._role("printer-list").contains(next) || next === this._role("switcher")) return;
    this._closeList();
  }
  _closeListOutside(ev) {
    const path = ev.composedPath();
    if (path.includes(this._role("printer-list")) || path.includes(this._role("switcher"))) return;
    this._closeList();
  }
  _renderSwitcher(lang, printers, printer, unknown) {
    const multi = printers.length > 1 || unknown && printers.length > 0;
    const who = this._role("who");
    const button = this._role("switcher");
    const home = multi ? button : who;
    if (this._role("title").parentNode !== home) {
      home.prepend(this._role("who-icon"), this._role("title"));
    }
    who.hidden = multi;
    button.hidden = !multi;
    const icon = printer?.kind === "scanner" ? "scanner" : "printer";
    const iconBox = this._role("who-icon");
    if (iconBox.dataset.icon !== icon) {
      iconBox.dataset.icon = icon;
      iconBox.replaceChildren(svgIcon(icon));
    }
    if (!multi) {
      this._closeList();
      this._listKey = "";
      this._role("printer-list").replaceChildren();
      return;
    }
    const label = t(lang, "switch_printer");
    button.setAttribute("aria-label", `${label}: ${this._role("title").textContent}`);
    button.title = label;
    this._role("printer-list").setAttribute("aria-label", t(lang, "picker"));
    const current = printer?.entry_id ?? null;
    const rows = printers.map((p) => [
      p.entry_id,
      p.title || p.entry_id,
      this._statusText(lang, p),
      p.entry_id === current
    ]);
    const key = JSON.stringify(rows);
    if (key === this._listKey) return;
    this._listKey = key;
    const list = this._role("printer-list");
    const focused = this.shadowRoot.activeElement?.dataset?.entryId;
    const items = rows.map(([id, name, status, selected], i) => {
      const li = document.createElement("li");
      li.className = "printer-option";
      li.setAttribute("role", "option");
      li.id = `printer-option-${i}`;
      li.dataset.entryId = id;
      li.tabIndex = -1;
      li.setAttribute("aria-selected", String(selected));
      const check = document.createElement("span");
      check.className = "check";
      check.append(svgIcon("check"));
      const nameEl = document.createElement("span");
      nameEl.className = "name";
      nameEl.textContent = name;
      const statusEl = document.createElement("span");
      statusEl.className = "status";
      statusEl.textContent = status;
      li.append(check, nameEl, statusEl);
      return li;
    });
    list.replaceChildren(...items);
    if (focused) items.find((el) => el.dataset.entryId === focused)?.focus();
  }
};

// frontend/src/styles.js
var STYLE = `
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
  .header { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .header-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .who {
    flex: 0 1 auto;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    min-height: 44px;
    padding: 0;
    border: none;
    border-radius: 8px;
    background: none;
    font: inherit;
    color: inherit;
    text-align: start;
  }
  button.who { cursor: pointer; padding: 0 4px; margin: 0 -4px; }
  button.who:hover { background: var(--secondary-background-color, rgba(127, 127, 127, 0.12)); }
  .who svg { display: block; color: var(--secondary-text-color); }
  .who-icon, .chevron { flex: none; }
  .title {
    font-size: 1.2em;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .state {
    margin-left: auto;
    flex: none;
    color: var(--secondary-text-color);
    white-space: nowrap;
  }
  .printer-list {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    overflow: hidden;
  }
  .printer-option {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    padding: 0 16px;
    cursor: pointer;
    min-width: 0;
    outline: none;
  }
  .printer-option + .printer-option { border-top: 1px solid var(--divider-color); }
  .printer-option:hover, .printer-option:focus-visible {
    background: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
  }
  .printer-option .check { width: 24px; flex: none; color: var(--primary-color); }
  .printer-option .check svg { display: block; }
  .printer-option[aria-selected="false"] .check svg { visibility: hidden; }
  .printer-option .name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .printer-option .status { flex: none; color: var(--secondary-text-color); white-space: nowrap; }
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
  .print-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .file-row {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  /* Choose file and Copies share one row, even on a ~300 px card. */
  .file-row .option[data-opt="copies"] { margin-left: auto; }
  .file-row .option input[type="number"] { width: 56px; }
  .file-info { flex: 1 1 100%; display: flex; align-items: baseline; gap: 8px; min-width: 0; }
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
  .options { display: flex; flex-wrap: wrap; gap: 8px 16px; min-width: 0; }
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

  /* Scanning */
  .scan-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .scan-fields {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 8px 12px;
  }
  .scan-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    color: var(--secondary-text-color);
    font-size: 0.9em;
  }
  .scan-field select { width: 100%; font-size: 1rem; }
  .scan-result { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .scan-page {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 8px;
    border-radius: 8px;
    background: var(--secondary-background-color);
  }
  .scan-page img {
    display: block;
    max-width: 100%;
    max-height: 240px;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  }
  .scan-page .sheet-status { padding: 8px; }
  .scan-nav { display: flex; align-items: center; justify-content: center; gap: 8px; }
  .scan-name { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .scan-name input { flex: 1 1 auto; min-width: 0; }
  .scan-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .file-button:disabled { opacity: 0.5; cursor: default; }
  .file-button.danger { color: var(--error-color); border-color: var(--error-color); }
  .icon-button.armed {
    width: auto;
    padding: 0 8px;
    border-radius: 8px;
    color: var(--error-color);
    white-space: nowrap;
  }
  .history-panel { display: flex; flex-direction: column; min-height: 0; }
  .tabs { display: flex; border-bottom: 1px solid var(--divider-color); }
  .tab {
    flex: 1 1 0;
    min-height: 48px;
    border: none;
    border-bottom: 2px solid transparent;
    background: none;
    font: inherit;
    font-weight: 500;
    color: var(--secondary-text-color);
    cursor: pointer;
  }
  .tab[aria-selected="true"] { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .tab:disabled { opacity: 0.5; cursor: default; }
  .history-mark svg { color: var(--secondary-text-color); vertical-align: middle; }
  /* Crop dialog */
  .crop-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
    overflow-y: auto;
    min-height: 0;
  }
  .crop-stage {
    position: relative;
    align-self: center;
    max-width: 100%;
    overflow: hidden;
    line-height: 0;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
  .crop-stage img {
    display: block;
    max-width: 100%;
    max-height: 55vh;
    max-height: 55dvh;
    background: #fff;
  }
  .crop-frame {
    position: absolute;
    box-sizing: border-box;
    border: 2px solid var(--primary-color);
    /* Dims everything outside the frame. */
    box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.55);
    cursor: move;
    touch-action: none;
    outline: none;
  }
  .crop-frame:focus-visible { border-style: dashed; }
  .crop-handle {
    position: absolute;
    width: 44px;
    height: 44px;
    padding: 0;
    border: none;
    background: none;
    touch-action: none;
    cursor: pointer;
  }
  .crop-handle::after {
    content: "";
    position: absolute;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--primary-color);
    border: 2px solid #fff;
    box-sizing: border-box;
  }
  .crop-handle[data-corner="nw"] { left: 0; top: 0; cursor: nwse-resize; }
  .crop-handle[data-corner="ne"] { right: 0; top: 0; cursor: nesw-resize; }
  .crop-handle[data-corner="sw"] { left: 0; bottom: 0; cursor: nesw-resize; }
  .crop-handle[data-corner="se"] { right: 0; bottom: 0; cursor: nwse-resize; }
  .crop-handle[data-corner="nw"]::after { left: -9px; top: -9px; }
  .crop-handle[data-corner="ne"]::after { right: -9px; top: -9px; }
  .crop-handle[data-corner="sw"]::after { left: -9px; bottom: -9px; }
  .crop-handle[data-corner="se"]::after { right: -9px; bottom: -9px; }
  .crop-handle:focus-visible::after { outline: 2px solid #fff; outline-offset: 2px; }
  .crop-body .sheet-status { padding: 0; text-align: center; }
  .crop-body .sheet-status.error { color: var(--error-color); }
  .crop-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
  .crop-actions .print { flex: 1 1 120px; width: auto; }
  .page { position: relative; }
  .page-crop {
    position: absolute;
    right: 8px;
    bottom: 8px;
    background: var(--card-background-color);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
  }
  .update {
    display: flex;
    align-items: center;
    gap: 8px 12px;
    flex-wrap: wrap;
    padding: 8px 12px;
    border-radius: 8px;
    background: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
  }
  .update-text { flex: 1 1 160px; min-width: 0; }
`;

// frontend/src/template.js
var TEMPLATE = `
  <style>${STYLE}</style>
  <ha-card>
    <div class="card">
      <div class="header">
        <div class="header-row">
          <span class="who" data-role="who">
            <span class="who-icon" data-role="who-icon">${svg("printer")}</span>
            <span class="title" data-role="title"></span>
          </span>
          <button type="button" class="who" data-role="switcher" aria-haspopup="listbox" aria-expanded="false" aria-controls="printer-list" hidden>
            <span class="chevron">${svg("unfold")}</span>
          </button>
          <span class="state" data-role="state"></span>
          <button type="button" class="icon-button" data-role="history-button" data-aria="history">
            ${svg("history")}
          </button>
        </div>
        <ul class="printer-list" id="printer-list" data-role="printer-list" role="listbox" hidden></ul>
      </div>
      <div class="update" data-role="update" role="status" hidden>
        <span class="update-text" data-role="update-text"></span>
        <button type="button" class="file-button" data-role="update-reload" data-t="update_reload"></button>
        <button type="button" class="file-button" data-role="update-restart" data-t="update_restart" hidden></button>
      </div>
      <div class="notice" data-role="notice" role="alert" hidden></div>
      <div class="tabs" role="tablist" data-role="body-tabs" hidden>
        <button type="button" role="tab" class="tab" id="body-tab-print" data-role="body-tab-print" data-body-tab="print" data-t="tab_print" aria-controls="print-panel" aria-selected="true"></button>
        <button type="button" role="tab" class="tab" id="body-tab-scan" data-role="body-tab-scan" data-body-tab="scan" data-t="tab_scan" aria-controls="scan-panel" aria-selected="false" tabindex="-1"></button>
      </div>
      <div class="print-panel" id="print-panel" data-role="print-panel">
      <div class="ink" data-role="ink"></div>
      <div class="file-row" data-role="file-row">
        <button type="button" class="file-button" data-role="pick">
          ${svg("paperclip")}<span data-t="choose_file"></span>
        </button>
        <label class="option" data-opt="copies">
          <span data-t="copies"></span>
          <input type="number" data-role="copies" min="1" value="1" inputmode="numeric" />
        </label>
        <span class="file-info" data-role="file-info" hidden>
          <span class="file-name" data-role="file-name"></span>
          <span class="file-size" data-role="file-size"></span>
        </span>
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
      <div class="options" data-role="options">
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
      <div class="scan-panel" id="scan-panel" data-role="scan-panel" hidden>
        <div class="scan-fields">
          <label class="scan-field" data-scan="source">
            <span data-t="scan_source"></span><select data-role="scan-source"></select>
          </label>
          <label class="scan-field" data-scan="color">
            <span data-t="scan_color"></span><select data-role="scan-color"></select>
          </label>
          <label class="scan-field" data-scan="resolution">
            <span data-t="scan_resolution"></span><select data-role="scan-resolution"></select>
          </label>
          <label class="scan-field" data-scan="format">
            <span data-t="scan_format"></span><select data-role="scan-format"></select>
          </label>
        </div>
        <button type="button" class="print" data-role="scan-start" data-t="scan_start"></button>
        <button type="button" class="file-button" data-role="scan-cancel" hidden>
          <span data-t="scan_cancel"></span>
        </button>
        <div class="message" data-role="scan-message" aria-live="polite"></div>
        <div class="scan-result" data-role="scan-result" hidden>
          <div class="scan-page" data-role="scan-page"></div>
          <div class="scan-nav" data-role="scan-nav">
            <button type="button" class="icon-button" data-role="scan-prev" data-aria="scan_prev">
              ${svg("chevron_left")}
            </button>
            <span data-role="scan-page-label"></span>
            <button type="button" class="icon-button" data-role="scan-next" data-aria="scan_next">
              ${svg("chevron_right")}
            </button>
          </div>
          <label class="scan-name">
            <span data-t="scan_name"></span>
            <input type="text" data-role="scan-name" autocomplete="off" maxlength="80" />
          </label>
          <div class="scan-actions">
            <button type="button" class="file-button" data-role="scan-download">
              ${svg("download")}<span data-t="scan_download"></span>
            </button>
            <button type="button" class="file-button" data-role="scan-crop">
              ${svg("crop")}<span data-t="crop"></span>
            </button>
            <button type="button" class="file-button" data-role="scan-add">
              ${svg("file_plus")}<span data-t="scan_add_page"></span>
            </button>
            <button type="button" class="file-button danger" data-role="scan-delete">
              ${svg("delete")}<span data-t="delete"></span>
            </button>
          </div>
        </div>
      </div>
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
      <div class="tabs" role="tablist" data-role="history-tabs" hidden>
        <button type="button" role="tab" class="tab" id="tab-prints" data-role="tab-prints" data-tab="prints" data-t="tab_prints" aria-controls="history-panel" aria-selected="true"></button>
        <button type="button" role="tab" class="tab" id="tab-scans" data-role="tab-scans" data-tab="scans" data-t="tab_scans" aria-controls="history-panel" aria-selected="false"></button>
      </div>
      <div class="history-panel" id="history-panel" data-role="history-panel">
        <div class="sheet-status" data-role="history-status" role="status"></div>
        <ul class="history-list" data-role="history-list"></ul>
      </div>
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
  <dialog data-role="crop-dialog" aria-labelledby="crop-title">
    <div class="sheet">
      <div class="sheet-head">
        <span class="sheet-title" id="crop-title" data-role="crop-title"></span>
        <button type="button" class="icon-button" data-role="crop-close" data-aria="close">
          ${svg("close")}
        </button>
      </div>
      <div class="crop-body">
        <div class="crop-stage" data-role="crop-stage">
          <div class="crop-frame" data-role="crop-frame" tabindex="0" data-aria="crop_frame" hidden>
            <button type="button" class="crop-handle" data-corner="nw" data-aria="crop_corner_nw"></button>
            <button type="button" class="crop-handle" data-corner="ne" data-aria="crop_corner_ne"></button>
            <button type="button" class="crop-handle" data-corner="sw" data-aria="crop_corner_sw"></button>
            <button type="button" class="crop-handle" data-corner="se" data-aria="crop_corner_se"></button>
          </div>
        </div>
        <div class="scan-nav" data-role="crop-nav" hidden>
          <button type="button" class="icon-button" data-role="crop-prev" data-aria="scan_prev">
            ${svg("chevron_left")}
          </button>
          <span data-role="crop-page-label"></span>
          <button type="button" class="icon-button" data-role="crop-next" data-aria="scan_next">
            ${svg("chevron_right")}
          </button>
        </div>
        <div class="sheet-status" data-role="crop-status" role="status"></div>
        <div class="crop-actions">
          <button type="button" class="file-button" data-role="crop-full" data-t="crop_full"></button>
          <button type="button" class="file-button" data-role="crop-cancel" data-t="crop_cancel"></button>
          <button type="button" class="print" data-role="crop-save" data-t="crop_save"></button>
        </div>
      </div>
    </div>
  </dialog>
`;

// frontend/src/update.js
function ownVersion() {
  try {
    return new URL(import.meta.url).searchParams.get("v");
  } catch (_err) {
    return null;
  }
}
var state = {
  // The version this page runs: from the card's URL, else the first one the
  // integration reports (a card added by hand without ?v=).
  running: ownVersion(),
  // A newer version the integration reported, or null.
  pending: null,
  cards: /* @__PURE__ */ new Set(),
  reload: () => globalThis.location.reload()
};
function registerCard(card) {
  state.cards.add(card);
}
function unregisterCard(card) {
  state.cards.delete(card);
}
function noteServerVersion(version) {
  if (typeof version !== "string" || !version) return;
  if (state.running === null) {
    state.running = version;
    return;
  }
  if (version === state.running || version === state.pending) return;
  state.pending = version;
  for (const card of state.cards) card._update();
}
function pendingVersion() {
  return state.pending;
}
function reloadNow() {
  state.reload();
}
var updateState = {
  reset({ running = null, reload } = {}) {
    state.running = running;
    state.pending = null;
    if (reload) state.reload = reload;
  }
};

// frontend/src/card.js
var HomePrintCard = class extends HTMLElement {
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
    this._historyEntryId = null;
    this._historyEntries = [];
    this._historyToken = 0;
    this._previewToken = 0;
    this._preview = null;
    this._crop = null;
    this._cropToken = 0;
    this._restartRequired = null;
    this._deletedIds = /* @__PURE__ */ new Set();
    this._historyTab = "prints";
    this._savedOverflow = null;
    this._tab = "print";
    this._scan = null;
    this._scanTimer = null;
    this._scanResult = null;
    this._scanMessage = null;
    this._scanAppliedId = null;
    this._scanImgToken = 0;
    this._scanSeen = /* @__PURE__ */ new Set();
    this._armed = /* @__PURE__ */ new Map();
    this._onDocumentClick = (ev) => this._closeMenuOutside(ev);
    this._onDocumentClickList = (ev) => this._closeListOutside(ev);
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = TEMPLATE;
    for (const name2 of FILE_INPUTS) {
      this._role(name2).addEventListener("change", (ev) => this._onFile(ev));
    }
    this._role("pick").addEventListener("click", () => this._onPickButton());
    for (const option of this.shadowRoot.querySelectorAll("[data-option]")) {
      option.addEventListener("click", () => this._onPickOption(option.dataset.option));
    }
    this._role("pick-menu").addEventListener("keydown", (ev) => this._onMenuKey(ev));
    for (const name2 of ["pick", "pick-menu"]) {
      this._role(name2).addEventListener("focusout", (ev) => this._onMenuFocusOut(ev));
    }
    this._role("print").addEventListener("click", () => this._onPrint());
    this._role("switcher").addEventListener("click", () => this._onSwitcher());
    this._role("switcher").addEventListener("keydown", (ev) => this._onSwitcherKey(ev));
    const list = this._role("printer-list");
    list.addEventListener("keydown", (ev) => this._onListKey(ev));
    list.addEventListener("click", (ev) => this._onListClick(ev));
    for (const name2 of ["switcher", "printer-list"]) {
      this._role(name2).addEventListener("focusout", (ev) => this._onListFocusOut(ev));
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
    restart.addEventListener(
      "click",
      () => this._confirmTap(restart, () => this._restartHomeAssistant(), "update_restart_confirm")
    );
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
    scanDelete.addEventListener(
      "click",
      () => this._confirmTap(scanDelete, () => this._deleteScanResult())
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
      entry_id: typeof config.entry_id === "string" && config.entry_id ? config.entry_id : void 0,
      title: typeof config.title === "string" && config.title ? config.title : void 0,
      show_ink: config.show_ink !== false
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
      this._restartRequired = typeof result?.restart_required === "string" ? result.restart_required : null;
      this._loadFailed = false;
    } catch (_err) {
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
    return entityId ? this._hass?.states?.[entityId] : void 0;
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
      timer: setTimeout(() => this._disarm(button), CONFIRM_MS)
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
        })
      );
      select.dataset.key = key;
    }
    const strings = items.map(([value]) => value);
    select.value = strings.includes(String(wanted)) ? String(wanted) : strings[0] ?? "";
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
    const multi = printers.length > 1;
    const name = printer ? printer.title || printer.entry_id : "";
    this._role("title").textContent = (multi ? name : this._config.title || name) || this._config.title || "Home Print";
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
    if (this._historyEntryId && this._historyEntryId !== printer?.entry_id) this._closeHistory();
  }
  // A newer Home Print: the bar offers a Reload button; the page is only
  // reloaded when the user taps it. Installed
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
    } else if (installed) {
      this._role("update-text").textContent = t(lang, "update_restart_needed", {
        version: installed
      });
    }
  }
  async _restartHomeAssistant() {
    const lang = pickLanguage(this._hass);
    try {
      await this._hass.callService("homeassistant", "restart", {});
    } catch (_err) {
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
      const state3 = this._entityState(printer.entities?.scanner_status)?.state;
      return SCANNER_STATES.includes(state3) ? t(lang, `scanner_state_${state3}`) : t(lang, "state_unknown");
    }
    const entity = this._entityState(printer.entities?.status)?.state;
    const state2 = KNOWN_STATES.includes(entity) ? entity : printer.state;
    let text = KNOWN_STATES.includes(state2) ? t(lang, `state_${state2}`) : t(lang, "state_unknown");
    if (this._entityState(printer.entities?.problem)?.state === "on") {
      text += ` · ${t(lang, "problem")}`;
    }
    return text;
  }
};
for (const Part of [PrintPart, HistoryPart, ScanPart, SwitcherPart, CropPart]) {
  for (const key of Object.getOwnPropertyNames(Part.prototype)) {
    if (key === "constructor") continue;
    Object.defineProperty(
      HomePrintCard.prototype,
      key,
      Object.getOwnPropertyDescriptor(Part.prototype, key)
    );
  }
}

// frontend/src/editor.js
var EDITOR_STYLE = `
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
var EDITOR_TEMPLATE = `
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
var HomePrintCardEditor = class extends HTMLElement {
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
    this._config = { ...config ?? {} };
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    this._render();
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
    const key = JSON.stringify(options.map(({ value, label }) => [value, label]));
    if (key !== this._optionsKey) {
      select.replaceChildren(
        ...options.map(({ value, label }) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          return option;
        })
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
      new CustomEvent("config-changed", { bubbles: true, composed: true, detail: { config } })
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
};

// frontend/src/index.js
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
  usesPickMenu,
  formatHistoryTime,
  historyStateIcon,
  scanErrorText,
  scanPagePath,
  scanFilePath,
  detectPaper,
  moveCropCorner
});
HomePrintCard.updateState = updateState;
if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, HomePrintCard);
}
if (!customElements.get(EDITOR_TYPE)) {
  customElements.define(EDITOR_TYPE, HomePrintCardEditor);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: "Home Print",
    description: "Yazıcıya dosya gönder ve durumu izle. / Send files to a printer and monitor its status."
  });
}
