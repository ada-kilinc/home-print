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

/**
 * Build a fake hass.
 *
 * `printers` is the `home_print/printers` list. `jobs` is a queue of
 * `home_print/job` answers: an object is returned as `{job}`, an object with
 * `error` rejects like HA's callWS does. The last answer repeats.
 */
export function makeHass({
  printers = [deskjetPrinter()],
  states = deskjetStates(),
  language = "tr",
  jobs = [],
  upload = { status: 200, body: { job_id: 42 } },
  printersError = null,
} = {}) {
  const jobQueue = [...jobs];
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
      throw { code: "unknown_command", message: msg.type };
    }),
    fetchWithAuth: vi.fn(async () => {
      if (upload instanceof Error) throw upload;
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
