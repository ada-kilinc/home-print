// Timings, limits and fixed lists.

export const CARD_TYPE = "home-print-card";
export const EDITOR_TYPE = "home-print-card-editor";
export const REFRESH_MS = 60 * 1000;
export const POLL_MS = 3 * 1000;
export const POLL_LIMIT_MS = 10 * 60 * 1000;
// Past this the job no longer holds the Print button while its status can't
// be read, so a stalled poll never locks the card.
export const STALL_MS = 30 * 1000;
// A little over the server's own 300 s print timeout.
export const UPLOAD_TIMEOUT_MS = 330 * 1000;
export const EDITOR_RETRY_MS = 30 * 1000;
export const PAGE_RANGES_RE = /^\s*\d+(\s*-\s*\d*)?(\s*,\s*\d+(\s*-\s*\d*)?)*\s*$/;
export const ACCEPT = "application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png";
// Some Android pickers honour only the first MIME type of ACCEPT, which greys
// out photos; this second picker asks for images only (iOS hands Photos' HEIC
// over as JPEG for it).
export const PHOTO_ACCEPT = "image/jpeg,image/png";
export const CAMERA_ACCEPT = "image/*";
export const FILE_INPUTS = ["input-file", "input-photo", "input-camera"];
export const PREVIEW_SIGN_SECONDS = 300;
// A signature older than this is renewed before its image is requested.
export const PREVIEW_RESIGN_MS = 240 * 1000;
export const PREVIEW_MARGIN = "800px 0px";
export const DOWNLOAD_SIGN_SECONDS = 60;
export const SCAN_POLL_MS = 1500;
// The card stops following a scan that shows no progress for this long.
export const SCAN_POLL_LIMIT_MS = 10 * 60 * 1000;
// A destructive button asks once ("Sure?") and forgets after this long.
export const CONFIRM_MS = 4 * 1000;
export const SCAN_SELECTS = ["scan-source", "scan-color", "scan-resolution", "scan-format"];
export const SCAN_ERRORS = [
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
];
// Poll answers that mean the scan can no longer be followed.
export const FATAL_SCAN_ERRORS = ["not_found", "no_scanner", "unauthorized"];
export const DEFAULT_FORMATS = ["application/pdf", "image/jpeg", "image/png"];
export const EXT_FORMATS = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
};
export const WORD_EXTS = ["doc", "docx", "odt", "rtf"];
export const WORD_TYPES = [
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.oasis.opendocument.text",
  "application/rtf",
  "text/rtf",
];
export const RUNNING_JOB_STATES = ["pending", "held", "processing", "stopped"];
export const FATAL_JOB_ERRORS = ["not_found", "unauthorized"];
// IPP job-state-reasons worth showing, by prefix; any other reason is hidden.
export const REASONS = [
  [["media-empty", "media-needed"], "reason_media_empty"],
  [["media-jam"], "reason_media_jam"],
  [["marker-supply-empty", "toner-empty"], "reason_ink_empty"],
  [["door-open", "cover-open"], "reason_cover_open"],
];
// Housekeeping keywords printers send all the time; never worth showing.
export const NOISE_REASONS = [
  "none",
  "job-printing",
  "job-incoming",
  "job-queued",
  "processing-to-stop-point",
  "job-data-insufficient",
  "job-completed-successfully",
];
export const PRINTER_ERROR_LIMIT = 3;
export const KNOWN_STATES = ["idle", "processing", "stopped"];
// States of the scanner status sensor (a scanner without a printer).
export const SCANNER_STATES = ["idle", "scanning", "adf_loaded", "stopped"];
export const HISTORY_STATES = ["sent", "completed", "aborted", "canceled", "error"];
