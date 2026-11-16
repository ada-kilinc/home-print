// A minimal stand-in for the `hass` object Home Assistant passes to cards.
import { vi } from "vitest";

export function deskjetPrinter(overrides = {}) {
  return {
    entry_id: "deskjet",
    title: "DeskJet 4670",
    available: true,
    can_print: true,
    state: "idle",
    entities: {
      status: "sensor.deskjet_status",
      problem: "binary_sensor.deskjet_problem",
      last_job: "sensor.deskjet_last_job",
      markers: ["sensor.deskjet_black_ink", "sensor.deskjet_tri_color_ink"],
    },
    capabilities: {
      formats: ["application/pdf", "image/jpeg", "image/png"],
      sides: ["one-sided", "two-sided-long-edge", "two-sided-short-edge"],
      color_modes: ["monochrome", "color"],
      copies_max: 99,
      page_ranges_passthrough: false,
    },
    defaults: { sides: "two-sided-long-edge", color_mode: "monochrome" },
    max_file_mb: 25,
    ...overrides,
  };
}

export function deskjetStates() {
  return {
    "sensor.deskjet_status": { state: "idle", attributes: {} },
    "binary_sensor.deskjet_problem": { state: "off", attributes: {} },
    "sensor.deskjet_black_ink": {
      state: "40",
      attributes: { color: "#000000", kind: "ink-cartridge", friendly_name: "DeskJet black ink" },
    },
    "sensor.deskjet_tri_color_ink": {
      state: "20",
      attributes: {
        color: "#00FFFF#FF00FF#FFFF00",
        kind: "ink-cartridge",
        friendly_name: "DeskJet tri-color ink",
      },
    },
    "sensor.deskjet_last_job": {
      state: "rapor.pdf",
      attributes: { state: "completed", user: "Ada", time: "2026-11-16T16:52:00+01:00", job_id: 7 },
    },
  };
}

export function historyEntry(overrides = {}) {
  return {
    id: "a".repeat(32),
    time: "2026-11-16T15:52:00+00:00",
    file_name: "rapor.pdf",
    user: "Ada",
    job_id: 7,
    state: "completed",
    pages: 2,
    converted_to: null,
    error: null,
    file: true,
    size: 1234,
    mime: "application/pdf",
    ...overrides,
  };
}

export function scannerBlock(overrides = {}) {
  return {
    available: true,
    state: "idle",
    adf_loaded: false,
    sources: {
      platen: { color_modes: ["color", "gray", "bw"], resolutions: [75, 150, 300, 600] },
      adf: { color_modes: ["color", "gray"], resolutions: [150, 300] },
    },
    formats: ["pdf", "jpeg"],
    defaults: { source: "platen", color_mode: "color", resolution: 300, format: "pdf" },
    active_scan_id: null,
    last_scan: null,
    ...overrides,
  };
}

export function scanRecord(overrides = {}) {
  return {
    id: "c".repeat(32),
    time: "2026-11-16T15:52:00+00:00",
    name: "tarama_2026-11-16_1652",
    user: "Ada",
    pages: 1,
    size: 4321,
    mime: "application/pdf",
    path: "home_print/scans/2026-11/tarama_2026-11-16_1652.pdf",
    source: "platen",
    color_mode: "color",
    resolution: 300,
    ...overrides,
  };
}

export function scanState(overrides = {}) {
  return {
    scan_id: "s1",
    state: "scanning",
    pages: 0,
    error: null,
    record: null,
    user: "Ada",
    ...overrides,
  };
}

/**
 * Build a fake hass.
 *
 * `printers` is the `home_print/printers` list. `jobs` is a queue of
 * `home_print/job` answers: an object is returned as `{job}`, an object with
 * `error` rejects like HA's callWS does. The last answer repeats.
 * `upload` is the upload answer, an Error to reject with, or "hang" for a
 * request that only ends when its AbortSignal fires. `history` seeds the
 * `home_print/history` store, which `home_print/history/delete` edits;
 * `historyError`, `deleteError` and `signError` make those calls reject.
 * `scans` seeds the `home_print/scans` store (edited by scans/delete and
 * scans/rename). `scanStart` is the scan/start answer (a state, or an object
 * with `error` to reject); `scanStates` is a queue of scan/state answers like
 * `jobs`. `scanDeleteError` and `renameError` make those calls reject.
 */
export function makeHass({
  printers = [deskjetPrinter()],
  states = deskjetStates(),
  language = "tr",
  jobs = [],
  upload = { status: 200, body: { job_id: 42 } },
  printersError = null,
  history = [],
  historyError = null,
  deleteError = null,
  signError = null,
  scans = [],
  scanStart = null,
  scanStates = [],
  scanDeleteError = null,
  renameError = null,
} = {}) {
  const jobQueue = [...jobs];
  const scanQueue = [...scanStates];
  const scanStore = scans.map((record) => ({ ...record }));
  const historyStore = history.map((entry) => ({ ...entry }));
  const hass = {
    language,
    locale: { language },
    states,
    calls: [],
    callWS: vi.fn(async (msg) => {
      hass.calls.push(msg);
      if (msg.type === "home_print/printers") {
        if (printersError) throw printersError;
        return { printers };
      }
      if (msg.type === "home_print/job") {
        const next = jobQueue.length > 1 ? jobQueue.shift() : jobQueue[0];
        if (!next) throw { code: "not_found", message: "not found" };
        if (next.error) throw { code: next.error, message: next.error };
        return { job: next };
      }
      if (msg.type === "home_print/history") {
        if (historyError) throw historyError;
        return { entries: historyStore.map((entry) => ({ ...entry })) };
      }
      if (msg.type === "home_print/history/delete") {
        if (deleteError) throw deleteError;
        const index = historyStore.findIndex((entry) => entry.id === msg.history_id);
        if (index >= 0) historyStore.splice(index, 1);
        return { deleted: index >= 0 };
      }
      if (msg.type === "home_print/scan/start") {
        if (scanStart?.error) throw { code: scanStart.error, message: scanStart.error };
        return { scan: scanStart ?? scanState() };
      }
      if (msg.type === "home_print/scan/state") {
        const next = scanQueue.length > 1 ? scanQueue.shift() : scanQueue[0];
        if (!next) throw { code: "not_found", message: "not found" };
        if (next.code) throw { code: next.code, message: next.code };
        return { scan: next };
      }
      if (msg.type === "home_print/scans") {
        return { entries: scanStore.map((record) => ({ ...record })) };
      }
      if (msg.type === "home_print/scans/delete") {
        if (scanDeleteError) throw scanDeleteError;
        const index = scanStore.findIndex((record) => record.id === msg.scan_record_id);
        if (index >= 0) scanStore.splice(index, 1);
        return { deleted: index >= 0 };
      }
      if (msg.type === "home_print/scans/rename") {
        if (renameError) throw renameError;
        const record = scanStore.find((r) => r.id === msg.scan_record_id);
        if (record) record.name = msg.name.trim();
        return { entry: record ? { ...record } : null };
      }
      if (msg.type === "auth/sign_path") {
        if (signError) throw signError;
        return { path: `${msg.path}?authSig=sig` };
      }
      throw { code: "unknown_command", message: msg.type };
    }),
    fetchWithAuth: vi.fn(async (_url, init = {}) => {
      if (upload instanceof Error) throw upload;
      if (upload === "hang") {
        return new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("The operation was aborted.", "AbortError")),
          );
        });
      }
      const body = upload.body;
      return {
        ok: upload.status >= 200 && upload.status < 300,
        status: upload.status,
        json: async () => {
          if (body === undefined) throw new SyntaxError("no body");
          return body;
        },
      };
    }),
  };
  return hass;
}
