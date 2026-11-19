// A stand-in `hass` for the README screenshots (scripts/screenshots.py).
// Same shapes as tests/frontend/fake-hass.js, without vitest.

const day = (d, hm) => `2026-11-${d}T${hm}:00+01:00`;

function printer(overrides = {}) {
  return {
    entry_id: "deskjet",
    title: "HP DeskJet 4670 series",
    available: true,
    can_print: true,
    state: "idle",
    entities: {
      status: "sensor.deskjet_status",
      problem: "binary_sensor.deskjet_problem",
      last_job: "sensor.deskjet_last_job",
      markers: ["sensor.deskjet_tri_color_ink", "sensor.deskjet_black_ink"],
    },
    capabilities: {
      formats: ["application/pdf", "image/jpeg", "image/png"],
      sides: ["one-sided", "two-sided-long-edge", "two-sided-short-edge"],
      color_modes: ["monochrome", "color"],
      copies_max: 99,
      page_ranges: true,
    },
    defaults: { sides: "two-sided-long-edge", color_mode: "monochrome" },
    max_file_mb: 25,
    scanner: {
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
    },
    ...overrides,
  };
}

const laser = printer({
  entry_id: "office",
  title: "Brother HL-L2350DW",
  scanner: null,
  state: "processing",
  entities: {
    status: "sensor.office_status",
    problem: "binary_sensor.office_problem",
    last_job: "sensor.office_last_job",
    markers: ["sensor.office_toner"],
  },
  capabilities: { ...printer().capabilities, color_modes: ["monochrome"] },
});

const studio = printer({
  entry_id: "studio",
  title: "Canon PIXMA G650",
  available: false,
  scanner: null,
  entities: { status: "sensor.studio_status", problem: null, last_job: null, markers: [] },
});

const STATES = {
  "sensor.deskjet_status": { state: "idle", attributes: {} },
  "binary_sensor.deskjet_problem": { state: "off", attributes: {} },
  "sensor.deskjet_black_ink": {
    state: "40",
    attributes: { color: "#000000", kind: "ink-cartridge", friendly_name: "HP DeskJet 4670 series Black" },
  },
  "sensor.deskjet_tri_color_ink": {
    state: "20",
    attributes: {
      color: "#00FFFF#FF00FF#FFFF00",
      kind: "ink-cartridge",
      friendly_name: "HP DeskJet 4670 series Colour",
    },
  },
  "sensor.office_status": { state: "processing", attributes: {} },
  "binary_sensor.office_problem": { state: "off", attributes: {} },
  "sensor.office_toner": {
    state: "65",
    attributes: { color: "#000000", kind: "toner", friendly_name: "Brother HL-L2350DW Black" },
  },
  "sensor.studio_status": { state: "unavailable", attributes: {} },
};

const HISTORY = [
  ["monthly-report.pdf", day(18, "13:23"), "Ada", 4],
  ["boarding-pass.pdf", day(18, "10:15"), "Dad", 1],
  ["IMG_2041.jpg", day(17, "12:35"), "Ada", 1, "image/jpeg"],
].map(([file_name, time, user, pages, mime = "application/pdf"], i) => ({
  id: String(i + 1).repeat(32),
  time,
  file_name,
  user,
  job_id: 10 + i,
  state: "completed",
  pages,
  converted_to: null,
  error: null,
  file: true,
  size: 200000,
  mime,
}));

const SCANS = [
  ["scan_2026-11-18_1252", day(18, "13:32"), 2],
  ["receipt_march", day(17, "13:35"), 1],
  ["passport_copy", day(15, "13:55"), 1],
].map(([name, time, pages], i) => ({
  id: String.fromCharCode(97 + i).repeat(32),
  time,
  name,
  user: "Ada",
  pages,
  size: 400000,
  mime: "application/pdf",
  path: `home_print/scans/2026-11/${name}.pdf`,
  source: "platen",
  color_mode: "color",
  resolution: 300,
}));

export function makeHass({ several = false } = {}) {
  const printers = several ? [printer(), laser, studio] : [printer()];
  let polls = 0;
  return {
    language: "en",
    locale: { language: "en", time_format: "12" },
    states: STATES,
    async callWS(msg) {
      switch (msg.type) {
        case "home_print/printers":
          return { printers };
        case "home_print/history":
          return { entries: HISTORY };
        case "home_print/scans":
          return { entries: SCANS };
        case "home_print/scan/start":
          return { scan: { scan_id: "s1", state: "scanning", pages: 0, error: null, record: null, user: "Ada" } };
        case "home_print/scan/state":
          polls += 1;
          return {
            scan:
              polls < 2
                ? { scan_id: "s1", state: "scanning", pages: 1, error: null, record: null, user: "Ada" }
                : { scan_id: "s1", state: "done", pages: 2, error: null, record: SCANS[0], user: "Ada" },
          };
        case "auth/sign_path":
          return { path: `${msg.path}?authSig=demo` };
        default:
          throw { code: "unknown_command", message: msg.type };
      }
    },
    async fetchWithAuth() {
      return { ok: true, status: 200, json: async () => ({ job_id: 1 }) };
    },
  };
}
