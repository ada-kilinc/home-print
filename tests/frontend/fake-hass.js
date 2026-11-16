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
} = {}) {
  const jobQueue = [...jobs];
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
