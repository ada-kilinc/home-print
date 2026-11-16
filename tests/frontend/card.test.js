import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  deskjetPrinter,
  deskjetStates,
  historyEntry,
  makeHass,
  scannerBlock,
  scanRecord,
  scanState,
} from "./fake-hass.js";

let HomePrintCard;
let errorSpy;

beforeAll(async () => {
  await import("../../custom_components/home_print/frontend/home-print-card.js");
  HomePrintCard = customElements.get("home-print-card");
});

beforeEach(() => {
  vi.useFakeTimers();
  errorSpy = vi.spyOn(console, "error");
});

afterEach(() => {
  document.body.innerHTML = "";
  expect(errorSpy).not.toHaveBeenCalled();
  errorSpy.mockRestore();
  vi.useRealTimers();
});

const flush = () => vi.advanceTimersByTimeAsync(0);

async function mount(hass, config = {}) {
  const card = document.createElement("home-print-card");
  card.setConfig({ type: "custom:home-print-card", ...config });
  document.body.appendChild(card);
  card.hass = hass;
  await flush();
  return card;
}

const $ = (card, sel) => card.shadowRoot.querySelector(sel);
const role = (card, name) => $(card, `[data-role="${name}"]`);
const optVisible = (card, name) => {
  const row = $(card, `[data-opt="${name}"]`);
  return Boolean(row) && !row.hidden;
};
const text = (card, name) => (role(card, name)?.textContent ?? "").trim();

function makeFile(name, type, size = 1234) {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

async function selectFile(card, file, input = role(card, "input-file")) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change"));
  await flush();
}

function setInput(card, name, value) {
  const el = role(card, name);
  if (el.type === "checkbox") el.checked = value;
  else el.value = value;
  el.dispatchEvent(new Event("change"));
  el.dispatchEvent(new Event("input"));
}

async function clickPrint(card) {
  role(card, "print").click();
  await flush();
}

describe("registration", () => {
  it("defines the element and lists it once in the card picker", async () => {
    expect(HomePrintCard).toBeTruthy();
    const entries = window.customCards.filter((c) => c.type === "home-print-card");
    expect(entries).toHaveLength(1);
    expect(entries[0].name).toBe("Home Print");
    expect(HomePrintCard.getStubConfig()).toEqual({});
    const card = await mount(makeHass());
    expect(card.getCardSize()).toBe(5);
  });

  it("asks for printers on first hass and every 60 s, not on every state change", async () => {
    const hass = makeHass();
    const card = await mount(hass);
    const count = () => hass.calls.filter((m) => m.type === "home_print/printers").length;
    expect(count()).toBe(1);
    card.hass = { ...hass, states: { ...hass.states } };
    await flush();
    expect(count()).toBe(1);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(count()).toBe(2);
  });
});

describe("options from capabilities", () => {
  it("shows duplex, colour, pages and copies for a DeskJet-like printer", async () => {
    const card = await mount(makeHass());
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    for (const name of ["duplex", "color", "pages", "copies"]) {
      expect(optVisible(card, name), name).toBe(true);
    }
    expect(role(card, "duplex").checked).toBe(true); // defaults.sides two-sided
    expect(role(card, "color").checked).toBe(false); // defaults.color_mode monochrome
    expect(role(card, "pages").placeholder).toBe("hepsi");
    expect(role(card, "copies").max).toBe("99");
  });

  it("hides duplex for a one-sided-only printer", async () => {
    const printer = deskjetPrinter();
    printer.capabilities.sides = ["one-sided"];
    printer.defaults.sides = "one-sided";
    const card = await mount(makeHass({ printers: [printer] }));
    expect(optVisible(card, "duplex")).toBe(false);
  });

  it("shows colour only when both colour and monochrome exist, else sends none", async () => {
    for (const modes of [["monochrome"], ["color"]]) {
      const printer = deskjetPrinter();
      printer.capabilities.color_modes = modes;
      const hass = makeHass({ printers: [printer], jobs: [{ job_id: 42, state: "processing" }] });
      const card = await mount(hass);
      expect(optVisible(card, "color"), modes.join()).toBe(false);
      await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
      await clickPrint(card);
      expect(hass.fetchWithAuth.mock.calls[0][1].body.has("color_mode")).toBe(false);
      document.body.innerHTML = "";
    }
  });

  it("pre-checks colour for a colour default and sends color when checked", async () => {
    const printer = deskjetPrinter();
    printer.defaults.color_mode = "color";
    const hass = makeHass({ printers: [printer], jobs: [{ job_id: 42, state: "processing" }] });
    const card = await mount(hass);
    expect(role(card, "color").checked).toBe(true);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].body.get("color_mode")).toBe("color");
  });

  it("keeps a short-edge two-sided default", async () => {
    const printer = deskjetPrinter();
    printer.defaults.sides = "two-sided-short-edge";
    const hass = makeHass({ printers: [printer], jobs: [{ job_id: 42, state: "processing" }] });
    const card = await mount(hass);
    expect(role(card, "duplex").checked).toBe(true);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].body.get("sides")).toBe("two-sided-short-edge");
  });

  it("sends one-sided when duplex is unchecked", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing" }] });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    setInput(card, "duplex", false);
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].body.get("sides")).toBe("one-sided");
  });

  it("labels an unknown printer state as unknown", async () => {
    const states = deskjetStates();
    states["sensor.deskjet_status"].state = "unknown";
    const card = await mount(
      makeHass({ printers: [deskjetPrinter({ state: "warming-up" })], states }),
    );
    expect(text(card, "state")).toBe("Bilinmiyor");
  });

  it("hides pages for images unless the printer passes page ranges through", async () => {
    let card = await mount(makeHass());
    await selectFile(card, makeFile("foto.jpg", "image/jpeg"));
    expect(optVisible(card, "pages")).toBe(false);
    document.body.innerHTML = "";

    const printer = deskjetPrinter();
    printer.capabilities.page_ranges_passthrough = true;
    card = await mount(makeHass({ printers: [printer] }));
    await selectFile(card, makeFile("foto.jpg", "image/jpeg"));
    expect(optVisible(card, "pages")).toBe(true);
  });

  it("shows status and ink levels from hass.states", async () => {
    const hass = makeHass();
    const card = await mount(hass);
    expect(text(card, "title")).toContain("DeskJet 4670");
    expect(text(card, "state")).toBe("Hazır");
    const markers = card.shadowRoot.querySelectorAll('[data-role="marker"]');
    expect(markers).toHaveLength(2);
    expect(markers[0].textContent).toContain("Siyah");
    expect(markers[0].textContent).toContain("%40");
    expect(markers[1].textContent).toContain("Renkli");
    expect(markers[1].textContent).toContain("%20");

    const states = deskjetStates();
    states["sensor.deskjet_status"].state = "processing";
    card.hass = { ...hass, states };
    await flush();
    expect(text(card, "state")).toBe("Yazdırıyor");
  });

  it("hides ink when show_ink is false", async () => {
    const card = await mount(makeHass(), { show_ink: false });
    expect(card.shadowRoot.querySelectorAll('[data-role="marker"]')).toHaveLength(0);
  });
});

describe("file checks", () => {
  it("warns about Word files and does not upload", async () => {
    const hass = makeHass();
    const card = await mount(hass);
    await selectFile(
      card,
      makeFile(
        "ödev.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ),
    );
    expect(text(card, "message")).toContain("Word dosyalarını şimdilik yazdıramıyorum");
    await clickPrint(card);
    expect(hass.fetchWithAuth).not.toHaveBeenCalled();
  });

  it("refuses a file over max_file_mb", async () => {
    const hass = makeHass();
    const card = await mount(hass);
    await selectFile(card, makeFile("big.pdf", "application/pdf", 26 * 1024 * 1024));
    expect(text(card, "message")).toContain("25");
    await clickPrint(card);
    expect(hass.fetchWithAuth).not.toHaveBeenCalled();
  });

  it("refuses an invalid page range", async () => {
    const hass = makeHass();
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    setInput(card, "pages", "1-3,abc");
    await clickPrint(card);
    expect(hass.fetchWithAuth).not.toHaveBeenCalled();
    expect(text(card, "message")).not.toBe("");
  });
});

describe("printing", () => {
  it("posts the chosen options with fetchWithAuth", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    setInput(card, "copies", "2");
    setInput(card, "pages", "1-3");
    await clickPrint(card);

    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);
    const [url, init] = hass.fetchWithAuth.mock.calls[0];
    expect(url).toBe("/api/home_print/upload/deskjet");
    expect(init.method).toBe("POST");
    const form = init.body;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("file").name).toBe("rapor.pdf");
    expect(form.get("copies")).toBe("2");
    expect(form.get("sides")).toBe("two-sided-long-edge");
    expect(form.get("color_mode")).toBe("monochrome");
    expect(form.get("page_ranges")).toBe("1-3");
  });

  it("uploads once on a double click and disables the button while uploading", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    const button = role(card, "print");
    button.click();
    button.click();
    expect(button.disabled).toBe(true);
    await flush();
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);
    // Upload confirmed: the button stays off while the job is running.
    expect(role(card, "print").disabled).toBe(true);
    expect(text(card, "message")).toBe("Yazdırılıyor…");
  });

  it("sends no second upload when tapped again while the job is printing", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    const file = makeFile("rapor.pdf", "application/pdf");
    await selectFile(card, file);
    await clickPrint(card);
    // The picked file is cleared so the same file can be chosen again.
    expect(text(card, "file-name")).toBe("");
    expect(role(card, "input-file").value).toBe("");
    await selectFile(card, file);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazdırılıyor…");
    expect(role(card, "print").disabled).toBe(true);
    await clickPrint(card);
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(1);
  });

  it("frees the button once the job completes", async () => {
    const hass = makeHass({
      jobs: [
        { job_id: 42, state: "processing", reasons: [] },
        { job_id: 42, state: "completed", reasons: [] },
      ],
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await vi.advanceTimersByTimeAsync(3000);
    expect(role(card, "print").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Tamamlandı ✓");
    expect(role(card, "print").disabled).toBe(false);
    await clickPrint(card);
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(2);
  });

  it("frees the button when the status stays unavailable for over 30 s", async () => {
    const hass = makeHass({
      jobs: [{ job_id: 42, state: "processing", reasons: [] }, { error: "printer_unavailable" }],
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await vi.advanceTimersByTimeAsync(3000 + 30_000);
    expect(text(card, "message")).toContain("Durum şu an alınamıyor");
    expect(role(card, "print").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(6000);
    expect(role(card, "print").disabled).toBe(false);
  });

  it("frees the button when a dropped connection lasts over 30 s", async () => {
    const hass = makeHass({ jobs: [{ error: "connection_lost" }] });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await vi.advanceTimersByTimeAsync(3000);
    expect(role(card, "print").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(36_000);
    expect(role(card, "print").disabled).toBe(false);
  });

  it("uploads a photo from the photo input and clears every input", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    const photo = role(card, "input-photo");
    await selectFile(card, makeFile("IMG_0001.JPG", "image/jpeg"), photo);
    expect(text(card, "file-name")).toBe("IMG_0001.JPG");
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].body.get("file").name).toBe("IMG_0001.JPG");
    for (const name of ["input-file", "input-photo", "input-camera"]) {
      expect(role(card, name).value, name).toBe("");
    }
  });

  it("checks a file from each of the three inputs the same way", async () => {
    for (const name of ["input-file", "input-photo", "input-camera"]) {
      const hass = makeHass();
      const card = await mount(hass);
      await selectFile(card, makeFile("big.png", "image/png", 26 * 1024 * 1024), role(card, name));
      expect(text(card, "message"), name).toContain("25");
      await clickPrint(card);
      expect(hass.fetchWithAuth, name).not.toHaveBeenCalled();
      await selectFile(card, makeFile("ödev.docx", ""), role(card, name));
      expect(text(card, "message"), name).toContain("Word");
      await selectFile(card, makeFile("foto.png", "image/png"), role(card, name));
      expect(role(card, "print").disabled, name).toBe(false);
      document.body.innerHTML = "";
    }
  });

  it("says a job the printer no longer lists probably finished", async () => {
    const hass = makeHass({
      jobs: [{ job_id: 42, state: "processing", reasons: [] }, { error: "job_gone" }],
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await vi.advanceTimersByTimeAsync(6000);
    expect(text(card, "message")).toBe(
      "İş yazıcının listesinde yok, muhtemelen bitti. Kâğıda bak.",
    );
    expect(role(card, "print").disabled).toBe(false);
    const count = hass.calls.filter((m) => m.type === "home_print/job").length;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(hass.calls.filter((m) => m.type === "home_print/job")).toHaveLength(count);
  });

  it("gives up on an upload after 330 s", async () => {
    const hass = makeHass({ upload: "hang" });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    await vi.advanceTimersByTimeAsync(329_000);
    expect(text(card, "message")).toBe("Gönderiliyor…");
    await vi.advanceTimersByTimeAsync(1000);
    expect(text(card, "message")).toBe(
      "Yükleme çok uzun sürdü. İş yine de yazdırılmış olabilir, tekrar denemeden önce yazıcıya bak.",
    );
    expect(text(card, "message")).not.toContain("Bağlantı");
    expect(vi.getTimerCount()).toBe(1); // only the 60 s printer refresh
  });

  it("shows the session text when the token refresh is rejected", async () => {
    for (const [upload, auth] of [
      [new Error("Unable to fetch tokens"), undefined],
      [Object.assign(new Error("x"), { code: "invalid_auth" }), undefined],
      [Object.assign(new Error("x"), { status: 401 }), undefined],
      [new Error("Failed to fetch"), { expired: true }],
    ]) {
      const hass = makeHass({ upload });
      hass.auth = auth;
      const card = await mount(hass);
      await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
      await clickPrint(card);
      expect(text(card, "message"), String(upload.message)).toBe(
        "Oturum süresi doldu, sayfayı yenile.",
      );
      document.body.innerHTML = "";
    }
  });

  it("follows the job until completed", async () => {
    const hass = makeHass({
      jobs: [
        { job_id: 42, state: "processing", reasons: [] },
        { job_id: 42, state: "completed", reasons: [] },
      ],
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    expect(text(card, "message")).toBe("Yazdırılıyor…");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazdırılıyor…");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Tamamlandı ✓");
    expect(role(card, "print").disabled).toBe(false);
    const jobCalls = hass.calls.filter((m) => m.type === "home_print/job");
    expect(jobCalls[0]).toEqual({ type: "home_print/job", entry_id: "deskjet", job_id: 42 });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(hass.calls.filter((m) => m.type === "home_print/job")).toHaveLength(jobCalls.length);
  });

  it("shows known reasons in plain words and hides raw IPP names", async () => {
    const hass = makeHass({
      jobs: [
        {
          job_id: 42,
          state: "stopped",
          reasons: ["media-empty-error", "media-needed", "document-format-error"],
        },
        { job_id: 42, state: "aborted", reasons: ["document-format-error"] },
      ],
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazıcı durdu, yazıcıya bak. (Kâğıt bitti)");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazdırma yarıda kaldı.");
  });

  it("keeps polling an unreachable printer and stops after 10 minutes", async () => {
    const hass = makeHass({ jobs: [{ error: "printer_unavailable" }] });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await vi.advanceTimersByTimeAsync(9 * 60_000);
    expect(role(card, "print").disabled).toBe(false);
    expect(text(card, "message")).toContain("Durum şu an alınamıyor");
    const before = hass.calls.filter((m) => m.type === "home_print/job").length;
    expect(before).toBeGreaterThan(100);
    await vi.advanceTimersByTimeAsync(60_000 + 3000);
    expect(text(card, "message")).toBe("Durum bilinmiyor, yazıcıya bak.");
    const count = hass.calls.filter((m) => m.type === "home_print/job").length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(hass.calls.filter((m) => m.type === "home_print/job")).toHaveLength(count);
    expect(role(card, "print").disabled).toBe(false);
  });

  it("stops after three printer_error answers in a row", async () => {
    const hass = makeHass({
      jobs: [
        { error: "printer_error" },
        { job_id: 42, state: "processing", reasons: [] },
        { error: "printer_error" },
        { error: "printer_error" },
        { error: "printer_error" },
        { job_id: 42, state: "completed", reasons: [] },
      ],
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await vi.advanceTimersByTimeAsync(4 * 3000);
    expect(role(card, "print").disabled).toBe(true);
    expect(text(card, "message")).not.toBe("Durum alınamadı, yazıcıya bak.");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Durum alınamadı, yazıcıya bak.");
    const count = hass.calls.filter((m) => m.type === "home_print/job").length;
    expect(count).toBe(5);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(hass.calls.filter((m) => m.type === "home_print/job")).toHaveLength(count);
    expect(role(card, "print").disabled).toBe(false);
  });

  it("stops and restarts its timers on disconnect and reconnect", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    const count = (type) => hass.calls.filter((m) => m.type === type).length;
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await vi.advanceTimersByTimeAsync(3000);
    expect(count("home_print/job")).toBe(1);

    card.remove();
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(count("home_print/printers")).toBe(1);
    expect(count("home_print/job")).toBe(1);
    expect(vi.getTimerCount()).toBe(0);

    document.body.appendChild(card);
    await flush();
    expect(count("home_print/printers")).toBe(2);
    await vi.advanceTimersByTimeAsync(3000);
    expect(count("home_print/job")).toBe(2);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(count("home_print/printers")).toBe(3);
  });

  it("renders markup in file and entity names as text", async () => {
    const states = deskjetStates();
    states["sensor.deskjet_black_ink"].attributes = {
      color: "#123456",
      friendly_name: '<img src=x onerror="alert(1)">',
    };
    const history = [historyEntry({ file_name: "<b>son</b>.pdf", user: "<i>Ada</i>" })];
    const card = await mount(makeHass({ states, history }));
    const name = '<img src=x onerror="alert(1)">.pdf';
    await selectFile(card, makeFile(name, "application/pdf"));
    expect(role(card, "file-name").textContent).toBe(name);
    expect(role(card, "ink").textContent).toContain('<img src=x onerror="alert(1)">');
    role(card, "history-button").click();
    await flush();
    const item = role(card, "history-item");
    expect(item.textContent).toContain("<b>son</b>.pdf");
    expect(item.textContent).toContain("<i>Ada</i>");
    expect(card.shadowRoot.querySelector("i")).toBeNull();
    expect(card.shadowRoot.querySelector("img")).toBeNull();
    expect(card.shadowRoot.querySelector("b")).toBeNull();
  });

  it("shows the server's message verbatim", async () => {
    const hass = makeHass({
      upload: {
        status: 422,
        body: { error: "output_too_large", message: "Çıktı çok büyük oldu (en fazla 25 MB)." },
      },
    });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(text(card, "message")).toBe("Çıktı çok büyük oldu (en fazla 25 MB).");
    expect(role(card, "print").disabled).toBe(false);
  });

  it("shows the session text on 401", async () => {
    const hass = makeHass({ upload: { status: 401, body: { message: "Unauthorized" } } });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(text(card, "message")).toBe("Oturum süresi doldu, sayfayı yenile.");
  });

  it("shows its own text on a network error", async () => {
    const hass = makeHass({ upload: new TypeError("Failed to fetch") });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(text(card, "message")).toContain("Bağlantı");
  });

  it("keeps a long Turkish file name intact and ellipsised", async () => {
    const name = "çok_uzun_öğrenci_belgesi_2026_güz_dönemi.pdf";
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    await selectFile(card, makeFile(name, "application/pdf"));
    const nameEl = role(card, "file-name");
    expect(nameEl.textContent).toBe(name);
    const style = getComputedStyle(nameEl);
    expect(style.textOverflow).toBe("ellipsis");
    expect(style.overflow).toBe("hidden");
    expect(style.whiteSpace).toBe("nowrap");
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].body.get("file").name).toBe(name);
  });
});

describe("job paused or stopped", () => {
  const DUPLEX_TR =
    "Yazıcı bekliyor… Çift taraflı baskıda arka yüz öncesi mürekkebin kuruması beklenir.";
  const DUPLEX_EN =
    "The printer is pausing… With two-sided printing it waits for the ink to dry before the back side.";

  async function startJob(jobs, { language = "tr", duplex = true } = {}) {
    const hass = makeHass({ jobs, language });
    const card = await mount(hass);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    setInput(card, "duplex", duplex);
    await clickPrint(card);
    return { hass, card };
  }
  const isError = (card) => role(card, "message").classList.contains("error");

  it("shows a neutral duplex text for a two-sided stopped job without reasons, then Done", async () => {
    const { hass, card } = await startJob([
      { job_id: 42, state: "stopped", reasons: [] },
      { job_id: 42, state: "processing", reasons: [] },
      { job_id: 42, state: "completed", reasons: [] },
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe(DUPLEX_TR);
    expect(isError(card)).toBe(false);
    expect(role(card, "print").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazdırılıyor…");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Tamamlandı ✓");
    expect(hass.calls.filter((m) => m.type === "home_print/job")).toHaveLength(3);
  });

  it("has the English duplex text", async () => {
    const { card } = await startJob([{ job_id: 42, state: "stopped", reasons: ["none"] }], {
      language: "en",
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe(DUPLEX_EN);
    expect(isError(card)).toBe(false);
  });

  it("shows the short pause text for a one-sided stopped job", async () => {
    const { card } = await startJob([{ job_id: 42, state: "stopped", reasons: [] }], {
      duplex: false,
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazıcı bekliyor…");
    expect(isError(card)).toBe(false);
  });

  it("has the short English pause text", async () => {
    const { card } = await startJob([{ job_id: 42, state: "stopped", reasons: [] }], {
      language: "en",
      duplex: false,
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("The printer is pausing…");
  });

  it("treats a held job without reasons as a neutral pause, without dry-time wording", async () => {
    const { card } = await startJob([{ job_id: 42, state: "held", reasons: [] }]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazıcı bekliyor…");
    expect(isError(card)).toBe(false);
  });

  it("keeps the error style for a stopped job with a known problem, then clears it", async () => {
    const { card } = await startJob([
      { job_id: 42, state: "stopped", reasons: ["media-empty-error"] },
      { job_id: 42, state: "processing", reasons: [] },
      { job_id: 42, state: "completed", reasons: [] },
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toContain("Kâğıt bitti");
    expect(isError(card)).toBe(true);
    expect(role(card, "print").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(3000);
    expect(isError(card)).toBe(false);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Tamamlandı ✓");
    expect(isError(card)).toBe(false);
  });

  it("shows unmapped reasons in a muted secondary line and hides noise", async () => {
    const { card } = await startJob([
      {
        job_id: 42,
        state: "processing",
        reasons: ["com.hp.dry-time", "job-printing", "none", "job-incoming", "vendor-x"],
      },
      { job_id: 42, state: "completed", reasons: ["job-completed-successfully", "com.hp.dry-time"] },
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "detail")).toBe("com.hp.dry-time, vendor-x");
    expect(text(card, "message")).toBe("Yazdırılıyor…");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Tamamlandı ✓");
    expect(text(card, "detail")).toBe("");
  });

  it("does not repeat mapped reasons in the secondary line", async () => {
    const { card } = await startJob([
      { job_id: 42, state: "stopped", reasons: ["media-empty-error", "document-format-error"] },
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "detail")).toBe("document-format-error");
  });

  it("keeps unmapped reasons visible when the job aborts, until a new upload", async () => {
    const { hass, card } = await startJob([
      { job_id: 42, state: "aborted", reasons: ["document-format-error", "job-printing"] },
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Yazdırma yarıda kaldı.");
    expect(isError(card)).toBe(true);
    expect(text(card, "detail")).toBe("document-format-error");
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await clickPrint(card);
    expect(hass.fetchWithAuth).toHaveBeenCalledTimes(2);
    expect(text(card, "detail")).toBe("");
  });

  it("falls back to the printer default sides when the duplex row is hidden", async () => {
    const printer = deskjetPrinter({
      capabilities: { ...deskjetPrinter().capabilities, sides: ["one-sided"] },
    });
    const hass = makeHass({
      printers: [printer],
      jobs: [{ job_id: 42, state: "stopped", reasons: [] }],
    });
    const card = await mount(hass);
    expect(optVisible(card, "duplex")).toBe(false);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe(DUPLEX_TR);
  });

  it("clears the detail line on job_gone and on a printer_error stop", async () => {
    let { card } = await startJob([
      { job_id: 42, state: "processing", reasons: ["com.hp.dry-time"] },
      { error: "job_gone" },
    ]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "detail")).toBe("com.hp.dry-time");
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toContain("listesinde yok");
    expect(text(card, "detail")).toBe("");
    document.body.innerHTML = "";
    ({ card } = await startJob([
      { job_id: 42, state: "processing", reasons: ["com.hp.dry-time"] },
      { error: "printer_error" },
      { error: "printer_error" },
      { error: "printer_error" },
    ]));
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "detail")).toBe("com.hp.dry-time");
    await vi.advanceTimersByTimeAsync(3 * 3000);
    expect(text(card, "message")).toBe("Durum alınamadı, yazıcıya bak.");
    expect(text(card, "detail")).toBe("");
  });

  it("visibleRawReasons drops noise, mapped and duplicate keywords", () => {
    const f = HomePrintCard.helpers.visibleRawReasons;
    expect(f(["none", "job-printing", "job-incoming", "job-queued"])).toEqual([]);
    expect(
      f(["processing-to-stop-point", "job-data-insufficient", "job-completed-successfully"]),
    ).toEqual([]);
    expect(f(["com.hp.dry-time", "com.hp.dry-time", "x-y"])).toEqual(["com.hp.dry-time", "x-y"]);
    expect(f(["media-jam-error", "job-canceled-at-device", "odd"])).toEqual(["odd"]);
    expect(f(undefined)).toEqual([]);
  });

  it("jobLabel picks the pause text by state, reasons and sides", () => {
    const h = HomePrintCard.helpers;
    expect(h.jobLabel("en", { state: "stopped", reasons: [] })).toBe("The printer is pausing…");
    expect(h.jobLabel("en", { state: "stopped", reasons: [] }, { twoSided: true })).toBe(DUPLEX_EN);
    expect(h.jobLabel("tr", { state: "stopped", reasons: ["media-jam"] })).toBe(
      "Yazıcı durdu, yazıcıya bak. (Kâğıt sıkıştı)",
    );
    expect(h.isProblemState({ state: "stopped", reasons: [] }, "en")).toBe(false);
    expect(h.isProblemState({ state: "stopped", reasons: ["door-open"] }, "en")).toBe(true);
  });
});

describe("printer availability", () => {
  it("shows an unreachable printer without errors", async () => {
    const printer = deskjetPrinter({ available: false, state: null });
    const states = deskjetStates();
    states["sensor.deskjet_status"] = { state: "unavailable", attributes: {} };
    states["sensor.deskjet_black_ink"] = { state: "unavailable", attributes: {} };
    const card = await mount(makeHass({ printers: [printer], states }));
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    expect(text(card, "state")).toBe("Ulaşılamıyor");
    expect(role(card, "print").disabled).toBe(true);
  });

  it("shows a printer still waiting for setup as unreachable", async () => {
    const printer = deskjetPrinter({
      available: false,
      state: null,
      capabilities: null,
      defaults: { sides: "one-sided", color_mode: null },
      entities: { status: null, problem: null, last_job: null, markers: [] },
    });
    const card = await mount(makeHass({ printers: [printer], states: {} }));
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    expect(text(card, "state")).toBe("Ulaşılamıyor");
    expect(role(card, "print").disabled).toBe(true);
    expect(role(card, "notice").hidden).toBe(true);
  });

  it("says the printer may still be loading when none are listed", async () => {
    const card = await mount(makeHass({ printers: [] }));
    expect(text(card, "notice")).toContain("yükleniyor");
  });

  it("survives a failing printers call and missing entities", async () => {
    const card = await mount(
      makeHass({ printersError: { code: "unknown_command", message: "x" }, states: {} }),
    );
    expect(role(card, "print").disabled).toBe(true);
    expect(text(card, "notice")).toContain(
      "Böyle sürerse entegrasyonun kurulu olup olmadığına bak.",
    );
  });

  it("disables printing with an explanation when can_print is false", async () => {
    const card = await mount(makeHass({ printers: [deskjetPrinter({ can_print: false })] }));
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    expect(role(card, "print").disabled).toBe(true);
    expect(text(card, "notice")).toContain("yönetici");
  });
});

describe("several printers", () => {
  const two = () => [
    deskjetPrinter(),
    deskjetPrinter({
      entry_id: "laser",
      title: "Laser",
      capabilities: { ...deskjetPrinter().capabilities, sides: ["one-sided"] },
      defaults: { sides: "one-sided", color_mode: null },
    }),
  ];

  it("picks the first printer and switches with the picker", async () => {
    const hass = makeHass({ printers: two(), jobs: [{ job_id: 1, state: "processing" }] });
    const card = await mount(hass);
    const picker = role(card, "picker");
    expect(picker).toBeTruthy();
    expect(text(card, "title")).toContain("DeskJet 4670");
    expect(optVisible(card, "duplex")).toBe(true);
    picker.value = "laser";
    picker.dispatchEvent(new Event("change"));
    await flush();
    expect(text(card, "title")).toContain("Laser");
    expect(optVisible(card, "duplex")).toBe(false);
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][0]).toBe("/api/home_print/upload/laser");
  });

  it("uses the configured entry_id", async () => {
    const card = await mount(makeHass({ printers: two() }), { entry_id: "laser" });
    expect(text(card, "title")).toContain("Laser");
  });

  it("warns about an unknown entry_id", async () => {
    const hass = makeHass();
    const card = await mount(hass, { entry_id: "gone" });
    expect(text(card, "notice")).toContain("gone");
    expect(text(card, "notice")).toContain("yükleniyor");
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    expect(role(card, "print").disabled).toBe(true);
  });

  it("hides the picker for a single printer", async () => {
    const card = await mount(makeHass());
    expect(role(card, "picker")).toBeNull();
  });
});

describe("helpers", () => {
  const h = () => HomePrintCard.helpers;

  it("pickLanguage", () => {
    expect(h().pickLanguage({ locale: { language: "tr-TR" } })).toBe("tr");
    expect(h().pickLanguage({ language: "en" })).toBe("en");
    expect(h().pickLanguage({ locale: { language: "de" } })).toBe("en");
    expect(h().pickLanguage(undefined)).toBe("en");
  });

  it("t falls back to English and fills vars", () => {
    expect(h().t("en", "too_large", { mb: 25 })).toContain("25");
    expect(h().t("tr", "session_expired")).toBe("Oturum süresi doldu, sayfayı yenile.");
    expect(h().t("tr", "no_such_key")).toBe("no_such_key");
  });

  it("isWordFile", () => {
    expect(h().isWordFile(makeFile("a.DOCX", ""))).toBe(true);
    expect(h().isWordFile(makeFile("a.odt", ""))).toBe(true);
    expect(h().isWordFile(makeFile("a", "application/msword"))).toBe(true);
    expect(h().isWordFile(makeFile("a.pdf", "application/pdf"))).toBe(false);
  });

  it("validateFile", () => {
    const p = deskjetPrinter();
    expect(h().validateFile(makeFile("a.pdf", "application/pdf"), p)).toEqual({ ok: true });
    expect(h().validateFile(makeFile("a.PNG", ""), p)).toEqual({ ok: true });
    expect(h().validateFile(makeFile("a.doc", ""), p)).toEqual({ ok: false, key: "word_file" });
    expect(h().validateFile(makeFile("a.gif", "image/gif"), p)).toEqual({
      ok: false,
      key: "unsupported_type",
    });
    expect(h().validateFile(makeFile("a.pdf", "application/pdf", 26 * 1024 * 1024), p)).toEqual({
      ok: false,
      key: "too_large",
    });
  });

  it("buildForm omits empty options", () => {
    const form = h().buildForm(makeFile("a.pdf", "application/pdf"), {
      copies: 1,
      sides: "one-sided",
      color_mode: null,
      page_ranges: "",
    });
    expect([...form.keys()]).toEqual(["file", "copies", "sides"]);
  });

  it("jobLabel", () => {
    expect(h().jobLabel("tr", { state: "pending" })).toBe("Yazdırılıyor…");
    expect(h().jobLabel("en", { state: "completed" })).toBe("Done ✓");
    expect(h().jobLabel("en", { state: "canceled", reasons: ["job-canceled-by-user"] })).toBe(
      "The job was canceled.",
    );
    expect(h().jobLabel("en", { state: "canceled", reasons: ["job-canceled-at-device"] })).toBe(
      "The job was canceled. (Cancelled at the printer)",
    );
  });

  it("reasonLabel maps the reasons people can act on", () => {
    const cases = [
      ["media-empty-error", "Kâğıt bitti", "Out of paper"],
      ["media-needed-report", "Kâğıt bitti", "Out of paper"],
      ["media-jam-error", "Kâğıt sıkıştı", "Paper jam"],
      ["marker-supply-empty-warning", "Mürekkep bitti", "Out of ink"],
      ["toner-empty-error", "Mürekkep bitti", "Out of ink"],
      ["door-open-error", "Kapak açık", "Cover open"],
      ["cover-open", "Kapak açık", "Cover open"],
      ["job-canceled-at-device", "Yazıcıdan iptal edildi", "Cancelled at the printer"],
    ];
    for (const [reason, tr, en] of cases) {
      expect(h().reasonLabel("tr", reason), reason).toBe(tr);
      expect(h().reasonLabel("en", reason), reason).toBe(en);
    }
    expect(h().reasonLabel("tr", "job-printing")).toBeNull();
    expect(h().reasonLabel("tr", "marker-supply-low-warning")).toBeNull();
  });
});

describe("single file picker", () => {
  const IOS_UA =
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148";

  function fakeNavigator(props) {
    for (const [key, value] of Object.entries(props)) {
      Object.defineProperty(navigator, key, { value, configurable: true });
    }
    return () => {
      for (const key of Object.keys(props)) delete navigator[key];
    };
  }

  const spyClicks = (card) =>
    Object.fromEntries(
      ["input-file", "input-photo", "input-camera"].map((name) => [
        name,
        vi.spyOn(role(card, name), "click").mockImplementation(() => {}),
      ]),
    );

  it("has one pick button and no separate photo button or last-job line", async () => {
    const card = await mount(makeHass());
    expect(card.shadowRoot.querySelectorAll('[data-role="pick"]')).toHaveLength(1);
    expect(text(card, "pick")).toBe("Dosya seç");
    expect(role(card, "photo")).toBeNull();
    expect(role(card, "file")).toBeNull();
    expect(role(card, "last")).toBeNull();
    expect(card.shadowRoot.textContent).not.toContain("Son:");
    expect(role(card, "pick-menu").hidden).toBe(true);
  });

  it("sets accept and capture on the three inputs", async () => {
    const card = await mount(makeHass());
    const file = role(card, "input-file");
    const photo = role(card, "input-photo");
    const camera = role(card, "input-camera");
    for (const input of [file, photo, camera]) expect(input.type).toBe("file");
    expect(file.getAttribute("accept")).toBe(
      "application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png",
    );
    expect(file.hasAttribute("capture")).toBe(false);
    expect(photo.getAttribute("accept")).toBe("image/jpeg,image/png");
    expect(photo.hasAttribute("capture")).toBe(false);
    expect(camera.getAttribute("accept")).toBe("image/*");
    expect(camera.getAttribute("capture")).toBe("environment");
  });

  it("on iOS opens the single system picker and never its own menu", async () => {
    for (const nav of [
      { userAgent: IOS_UA },
      {
        userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
        platform: "MacIntel",
        maxTouchPoints: 5,
      },
    ]) {
      const restore = fakeNavigator(nav);
      try {
        const card = await mount(makeHass());
        const clicks = spyClicks(card);
        role(card, "pick").click();
        await flush();
        expect(clicks["input-file"]).toHaveBeenCalledTimes(1);
        expect(clicks["input-photo"]).not.toHaveBeenCalled();
        expect(clicks["input-camera"]).not.toHaveBeenCalled();
        expect(role(card, "pick-menu").hidden).toBe(true);
        expect(role(card, "pick").hasAttribute("aria-expanded")).toBe(false);
      } finally {
        restore();
        document.body.innerHTML = "";
      }
    }
  });

  it("elsewhere opens its own menu whose options click the right input", async () => {
    const restore = fakeNavigator({
      userAgent: "Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome/131.0 Mobile",
      platform: "Linux armv8l",
      maxTouchPoints: 5,
    });
    try {
      const card = await mount(makeHass());
      const clicks = spyClicks(card);
      const menu = role(card, "pick-menu");
      const labels = { file: "Dosyadan seç", photo: "Fotoğraf seç", camera: "Fotoğraf çek" };
      for (const option of ["file", "photo", "camera"]) {
        role(card, "pick").click();
        await flush();
        expect(menu.hidden).toBe(false);
        expect(role(card, "pick").getAttribute("aria-expanded")).toBe("true");
        expect(clicks["input-file"]).toHaveBeenCalledTimes(option === "file" ? 0 : 1);
        const button = $(card, `[data-option="${option}"]`);
        expect(button.textContent.trim()).toBe(labels[option]);
        expect(button.querySelector("svg")).toBeTruthy();
        button.click();
        await flush();
        expect(clicks[`input-${option}`]).toHaveBeenCalledTimes(1);
        expect(menu.hidden).toBe(true);
        expect(role(card, "pick").getAttribute("aria-expanded")).toBe("false");
      }
      // A second tap on the button closes an open menu.
      role(card, "pick").click();
      role(card, "pick").click();
      expect(menu.hidden).toBe(true);
    } finally {
      restore();
    }
  });

  it("has English menu labels", async () => {
    const card = await mount(makeHass({ language: "en" }));
    expect(text(card, "pick")).toBe("Choose file");
    expect($(card, '[data-option="file"]').textContent.trim()).toBe("From files");
    expect($(card, '[data-option="photo"]').textContent.trim()).toBe("Photo library");
    expect($(card, '[data-option="camera"]').textContent.trim()).toBe("Take photo");
  });

  it("isIOS follows the plan's rule", () => {
    const isIOS = HomePrintCard.helpers.isIOS;
    expect(isIOS({ userAgent: IOS_UA })).toBe(true);
    expect(isIOS({ userAgent: "iPad", platform: "iPad" })).toBe(true);
    expect(isIOS({ userAgent: "Mac", platform: "MacIntel", maxTouchPoints: 5 })).toBe(true);
    expect(isIOS({ userAgent: "Mac", platform: "MacIntel", maxTouchPoints: 0 })).toBe(false);
    expect(isIOS({ userAgent: "Android", platform: "Linux" })).toBe(false);
    expect(isIOS(undefined)).toBe(false);
  });
});

describe("history", () => {
  const entries = () => [
    historyEntry({ id: "1".repeat(32), file_name: "rapor.pdf", user: "Ada", pages: 3 }),
    historyEntry({
      id: "2".repeat(32),
      file_name: "foto.jpg",
      user: null,
      state: "aborted",
      pages: 1,
      mime: "image/jpeg",
      file: false,
    }),
    historyEntry({ id: "3".repeat(32), file_name: "yeni.pdf", state: "sent", pages: null }),
  ];
  const items = (card) => [...card.shadowRoot.querySelectorAll('[data-role="history-item"]')];
  const dialog = (card) => role(card, "history-dialog");

  async function openHistory(card) {
    role(card, "history-button").click();
    await flush();
  }

  it("has a clock button with a label in the header", async () => {
    const card = await mount(makeHass());
    const button = role(card, "history-button");
    expect(button.closest(".header")).toBeTruthy();
    expect(button.getAttribute("aria-label")).toBe("Geçmiş");
    expect(button.querySelector("svg path")).toBeTruthy();
    expect(dialog(card).open).toBe(false);
    document.body.innerHTML = "";
    const en = await mount(makeHass({ language: "en" }));
    expect(role(en, "history-button").getAttribute("aria-label")).toBe("History");
  });

  it("opens the popup, asks for the printer's history and lists it", async () => {
    const hass = makeHass({ history: entries() });
    const card = await mount(hass);
    await openHistory(card);
    expect(dialog(card).open).toBe(true);
    expect(hass.calls.filter((m) => m.type === "home_print/history")).toEqual([
      { type: "home_print/history", entry_id: "deskjet" },
    ]);
    const rows = items(card);
    expect(rows).toHaveLength(3);
    const time = HomePrintCard.helpers.formatHistoryTime("tr", "2026-11-16T15:52:00+00:00");
    expect(rows[0].textContent).toContain("rapor.pdf");
    expect(rows[0].textContent).toContain(time);
    expect(rows[0].textContent).toContain("Ada");
    expect(rows[0].textContent).toContain("3 sayfa");
    expect(rows[0].textContent).toContain("✓");
    expect(rows[0].textContent).not.toContain("dosya yok");
    expect(rows[1].textContent).toContain("✗");
    expect(rows[1].textContent).toContain("dosya yok");
    expect(rows[2].textContent).toContain("…");
    expect(rows[2].textContent).not.toContain("sayfa");
    const trash = rows[0].querySelector('[data-role="history-delete"]');
    expect(trash.getAttribute("aria-label")).toBe("Sil");
    expect(trash.querySelector("svg")).toBeTruthy();
  });

  it("deletes a row with the trash button and it stays gone after a reload", async () => {
    const hass = makeHass({ history: entries() });
    const card = await mount(hass);
    await openHistory(card);
    items(card)[0].querySelector('[data-role="history-delete"]').click();
    await flush();
    expect(hass.calls.filter((m) => m.type === "home_print/history/delete")).toEqual([
      { type: "home_print/history/delete", entry_id: "deskjet", history_id: "1".repeat(32) },
    ]);
    expect(items(card)).toHaveLength(2);
    expect(card.shadowRoot.textContent).not.toContain("rapor.pdf");
    expect(role(card, "preview-dialog").open).toBe(false);
    role(card, "history-close").click();
    await openHistory(card);
    expect(items(card)).toHaveLength(2);
    expect(items(card)[0].textContent).toContain("foto.jpg");
  });

  it("shows the empty text once the last row is deleted", async () => {
    const hass = makeHass({ history: [historyEntry()] });
    const card = await mount(hass);
    await openHistory(card);
    items(card)[0].querySelector('[data-role="history-delete"]').click();
    await flush();
    expect(items(card)).toHaveLength(0);
    expect(text(card, "history-status")).toBe("Henüz baskı yok.");
  });

  it("keeps the row and says so when deleting fails", async () => {
    const hass = makeHass({
      history: entries(),
      deleteError: { code: "unauthorized", message: "Administrator required" },
    });
    const card = await mount(hass);
    await openHistory(card);
    items(card)[0].querySelector('[data-role="history-delete"]').click();
    await flush();
    expect(items(card)).toHaveLength(3);
    expect(text(card, "history-status")).toBe("Kayıtları yalnızca yöneticiler silebilir.");
  });

  it("hides the trash button when this user can't print", async () => {
    const hass = makeHass({ history: entries(), printers: [deskjetPrinter({ can_print: false })] });
    const card = await mount(hass);
    await openHistory(card);
    expect(items(card)).toHaveLength(3);
    expect(role(card, "history-delete")).toBeNull();
  });

  it("closes with the X, a backdrop tap and Escape", async () => {
    const card = await mount(makeHass({ history: entries() }));
    await openHistory(card);
    role(card, "history-close").click();
    expect(dialog(card).open).toBe(false);

    await openHistory(card);
    // A tap inside the sheet does not close it.
    $(card, '[data-role="history-dialog"] .sheet').click();
    expect(dialog(card).open).toBe(true);
    dialog(card).click();
    expect(dialog(card).open).toBe(false);

    await openHistory(card);
    dialog(card).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(dialog(card).open).toBe(false);
    expect(role(card, "history-close").getAttribute("aria-label")).toBe("Kapat");
  });

  it("says when there are no prints yet", async () => {
    const card = await mount(makeHass({ history: [], language: "en" }));
    await openHistory(card);
    expect(items(card)).toHaveLength(0);
    expect(text(card, "history-status")).toBe("No prints yet.");
  });

  it("shows an error text when the history can't be read, without crashing", async () => {
    const hass = makeHass({ historyError: { code: "unknown_command", message: "x" } });
    const card = await mount(hass);
    await openHistory(card);
    expect(dialog(card).open).toBe(true);
    expect(text(card, "history-status")).toBe("Geçmiş alınamadı. Birazdan tekrar dene.");
    expect(role(card, "history-status").classList.contains("error")).toBe(true);
    expect(items(card)).toHaveLength(0);
    expect(text(card, "state")).toBe("Hazır");
  });

  it("ellipsises a long Turkish file name in a row", async () => {
    const name = "çok_uzun_öğrenci_belgesi_2026_güz_dönemi_ödev_teslim_formu_son_hali.pdf";
    const card = await mount(makeHass({ history: [historyEntry({ file_name: name })] }));
    await openHistory(card);
    const nameEl = items(card)[0].querySelector('[data-role="history-name"]');
    expect(nameEl.textContent).toBe(name);
    const style = getComputedStyle(nameEl);
    expect(style.textOverflow).toBe("ellipsis");
    expect(style.overflow).toBe("hidden");
    expect(style.whiteSpace).toBe("nowrap");
    expect(getComputedStyle(role(card, "history-list")).overflowY).toBe("auto");
  });

  it("reloads the open list after a successful upload", async () => {
    const hass = makeHass({
      history: entries(),
      jobs: [{ job_id: 42, state: "processing", reasons: [] }],
    });
    const card = await mount(hass);
    const count = () => hass.calls.filter((m) => m.type === "home_print/history").length;
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(count()).toBe(0);
    await openHistory(card);
    expect(count()).toBe(1);
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    // Let the first job end so a second upload is allowed.
    hass.callWS.mockImplementationOnce(async (msg) => {
      hass.calls.push(msg);
      throw { code: "job_gone", message: "gone" };
    });
    await vi.advanceTimersByTimeAsync(3000);
    const afterJob = count();
    await selectFile(card, makeFile("ikinci.pdf", "application/pdf"));
    await clickPrint(card);
    expect(count()).toBe(afterJob + 1);
  });

  it("reloads the open list when the followed job ends", async () => {
    const hass = makeHass({
      history: entries(),
      jobs: [
        { job_id: 42, state: "processing", reasons: [] },
        { job_id: 42, state: "completed", reasons: [] },
      ],
    });
    const card = await mount(hass);
    const count = () => hass.calls.filter((m) => m.type === "home_print/history").length;
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    await openHistory(card);
    await vi.advanceTimersByTimeAsync(3000);
    expect(count()).toBe(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(text(card, "message")).toBe("Tamamlandı ✓");
    expect(count()).toBe(2);
  });

  it("closes when the printer changes", async () => {
    const printers = [deskjetPrinter(), deskjetPrinter({ entry_id: "laser", title: "Laser" })];
    const card = await mount(makeHass({ printers, history: entries() }));
    await openHistory(card);
    const picker = role(card, "picker");
    picker.value = "laser";
    picker.dispatchEvent(new Event("change"));
    await flush();
    expect(dialog(card).open).toBe(false);
  });

  it("closes when the card is removed", async () => {
    const card = await mount(makeHass({ history: entries() }));
    await openHistory(card);
    card.remove();
    expect(dialog(card).open).toBe(false);
  });

  it("formatHistoryTime uses the language and local time", () => {
    const f = HomePrintCard.helpers.formatHistoryTime;
    const iso = "2026-11-16T15:52:00+00:00";
    const expected = new Intl.DateTimeFormat("tr", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
    expect(f("tr", iso)).toBe(expected);
    expect(f("en", iso)).not.toBe("");
    expect(f("tr", "not a date")).toBe("");
    expect(f("??", iso)).not.toBe("");
  });

  it("historyStateIcon", () => {
    const f = HomePrintCard.helpers.historyStateIcon;
    expect(f("completed")).toBe("✓");
    for (const state of ["aborted", "canceled", "error"]) expect(f(state)).toBe("✗");
    expect(f("sent")).toBe("…");
    expect(f(undefined)).toBe("…");
  });
});

describe("preview", () => {
  const PDF_ID = "1".repeat(32);
  const items = (card) => [...card.shadowRoot.querySelectorAll('[data-role="history-item"]')];
  const images = (card) => [...role(card, "preview-body").querySelectorAll("img")];
  const pages = (card) => [...role(card, "preview-body").querySelectorAll("[data-page]")];
  const signCalls = (hass) => hass.calls.filter((m) => m.type === "auth/sign_path");

  // A stand-in IntersectionObserver the tests drive by hand.
  let observers;
  let realObserver;
  class FakeObserver {
    constructor(callback, options) {
      this.callback = callback;
      this.options = options;
      this.targets = new Set();
      this.disconnected = false;
      observers.push(this);
    }
    observe(el) {
      this.targets.add(el);
    }
    unobserve(el) {
      this.targets.delete(el);
    }
    disconnect() {
      this.targets.clear();
      this.disconnected = true;
    }
  }
  const observer = () => observers[observers.length - 1];
  async function show(card, page) {
    const el = pages(card).find((p) => p.dataset.page === String(page));
    const io = observer();
    expect(io.targets.has(el), `page ${page} observed`).toBe(true);
    io.callback([{ target: el, isIntersecting: true }], io);
    await flush();
  }

  beforeEach(() => {
    observers = [];
    realObserver = window.IntersectionObserver;
    window.IntersectionObserver = FakeObserver;
  });
  afterEach(() => {
    window.IntersectionObserver = realObserver;
  });

  async function openPreview(hass, index = 0) {
    const card = await mount(hass);
    role(card, "history-button").click();
    await flush();
    items(card)[index].querySelector('[data-role="history-open"]').click();
    await flush();
    return card;
  }

  it("opens over the history with a placeholder per page and signs none up front", async () => {
    const hass = makeHass({ history: [historyEntry({ id: PDF_ID, pages: 3 })] });
    const card = await openPreview(hass);
    expect(role(card, "preview-dialog").open).toBe(true);
    expect(role(card, "history-dialog").open).toBe(true);
    expect(text(card, "preview-title")).toBe("rapor.pdf");
    expect(pages(card)).toHaveLength(3);
    expect(images(card)).toHaveLength(0);
    expect(signCalls(hass)).toHaveLength(0);
    expect(observer().options.root).toBe(role(card, "preview-body"));
    expect(observer().options.rootMargin).toContain("800px");
    expect(getComputedStyle(role(card, "preview-body")).overflowY).toBe("auto");
  });

  it("signs and loads a page only when it nears the viewport", async () => {
    const hass = makeHass({ history: [historyEntry({ id: PDF_ID, pages: 3 })] });
    const card = await openPreview(hass);
    await show(card, 1);
    await show(card, 2);
    expect(signCalls(hass).map((m) => m.path)).toEqual(
      [1, 2].map((n) => `/api/home_print/history/deskjet/${PDF_ID}/page/${n}`),
    );
    expect(signCalls(hass)[0].expires).toBe(300);
    const imgs = images(card);
    expect(imgs).toHaveLength(2);
    expect(imgs[1].getAttribute("src")).toBe(
      `/api/home_print/history/deskjet/${PDF_ID}/page/2?authSig=sig`,
    );
    expect(imgs[0].getAttribute("alt")).toBe("Sayfa 1");
    expect(observer().targets.has(pages(card)[0])).toBe(false);
    expect(observer().targets.has(pages(card)[2])).toBe(true);
  });

  it("signs a page seen after more than 240 s afresh", async () => {
    const hass = makeHass({ history: [historyEntry({ id: PDF_ID, pages: 2 })] });
    const card = await openPreview(hass);
    await show(card, 1);
    await vi.advanceTimersByTimeAsync(241_000);
    const before = signCalls(hass).length;
    await show(card, 2);
    expect(signCalls(hass)).toHaveLength(before + 1);
    expect(signCalls(hass).at(-1).path).toContain("/page/2");
  });

  it("re-signs when the signature got old before the image could load", async () => {
    const hass = makeHass({ history: [historyEntry({ id: PDF_ID, pages: 1 })] });
    let release;
    const original = hass.callWS.getMockImplementation();
    hass.callWS.mockImplementation(async (msg) => {
      const result = await original(msg);
      if (msg.type === "auth/sign_path" && !release) {
        await new Promise((resolve) => {
          release = resolve;
        });
      }
      return result;
    });
    const card = await openPreview(hass);
    await show(card, 1);
    await vi.advanceTimersByTimeAsync(241_000);
    release();
    await flush();
    expect(signCalls(hass)).toHaveLength(2);
    expect(images(card)).toHaveLength(1);
  });

  it("disconnects the observer when the preview closes", async () => {
    const hass = makeHass({ history: [historyEntry({ pages: 2 })] });
    const card = await openPreview(hass);
    const io = observer();
    role(card, "preview-close").click();
    expect(io.disconnected).toBe(true);
    items(card)[0].querySelector('[data-role="history-open"]').click();
    await flush();
    const second = observer();
    expect(second).not.toBe(io);
    card.remove();
    expect(second.disconnected).toBe(true);
  });

  it("returns to the history when closed", async () => {
    const hass = makeHass({ history: [historyEntry({ pages: 1 })] });
    const card = await openPreview(hass);
    role(card, "preview-close").click();
    expect(role(card, "preview-dialog").open).toBe(false);
    expect(role(card, "history-dialog").open).toBe(true);

    items(card)[0].querySelector('[data-role="history-open"]').click();
    await flush();
    role(card, "preview-dialog").dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    expect(role(card, "preview-dialog").open).toBe(false);
    expect(role(card, "history-dialog").open).toBe(true);

    items(card)[0].querySelector('[data-role="history-open"]').click();
    await flush();
    role(card, "preview-dialog").click();
    expect(role(card, "preview-dialog").open).toBe(false);
    expect(role(card, "history-dialog").open).toBe(true);
  });

  it("shows one page for a photo", async () => {
    const hass = makeHass({
      history: [historyEntry({ file_name: "foto.jpg", mime: "image/jpeg", pages: null })],
    });
    const card = await openPreview(hass);
    expect(pages(card)).toHaveLength(1);
    await show(card, 1);
    images(card)[0].dispatchEvent(new Event("load"));
    await flush();
    expect(pages(card)).toHaveLength(1);
    expect(signCalls(hass)).toHaveLength(1);
  });

  it("with an unknown page count adds pages until one fails to load", async () => {
    const hass = makeHass({ history: [historyEntry({ id: PDF_ID, pages: null })] });
    const card = await openPreview(hass);
    expect(pages(card)).toHaveLength(1);
    await show(card, 1);
    images(card)[0].dispatchEvent(new Event("load"));
    await flush();
    expect(pages(card)).toHaveLength(2);
    expect(signCalls(hass)).toHaveLength(1);
    await show(card, 2);
    expect(images(card)[1].getAttribute("src")).toContain("/page/2?");
    images(card)[1].dispatchEvent(new Event("error"));
    await flush();
    expect(pages(card)).toHaveLength(1);
    expect(signCalls(hass)).toHaveLength(2);
    expect(text(card, "preview-body")).toBe("");
  });

  it("loads pages one after another without IntersectionObserver", async () => {
    window.IntersectionObserver = undefined;
    const hass = makeHass({ history: [historyEntry({ id: PDF_ID, pages: 3 })] });
    const card = await openPreview(hass);
    expect(signCalls(hass)).toHaveLength(1);
    expect(images(card)).toHaveLength(1);
    images(card)[0].dispatchEvent(new Event("load"));
    await flush();
    expect(signCalls(hass)).toHaveLength(2);
    images(card)[1].dispatchEvent(new Event("load"));
    await flush();
    images(card)[2].dispatchEvent(new Event("load"));
    await flush();
    expect(signCalls(hass)).toHaveLength(3);
    expect(images(card)).toHaveLength(3);
  });

  it("says a file that is no longer kept can't be shown", async () => {
    const hass = makeHass({ history: [historyEntry({ file: false })] });
    const card = await openPreview(hass);
    expect(role(card, "preview-dialog").open).toBe(true);
    expect(text(card, "preview-body")).toBe("Bu dosya artık saklanmıyor.");
    expect(images(card)).toHaveLength(0);
    expect(signCalls(hass)).toHaveLength(0);
    document.body.innerHTML = "";
    const en = await openPreview(
      makeHass({ language: "en", history: [historyEntry({ file: false })] }),
    );
    expect(text(en, "preview-body")).toBe("This file is no longer kept.");
  });

  it("says when the preview can't be loaded", async () => {
    const hass = makeHass({
      history: [historyEntry({ pages: 2 })],
      signError: { code: "unknown_error", message: "x" },
    });
    const card = await openPreview(hass);
    await show(card, 1);
    expect(text(card, "preview-body")).toBe("Ön izleme yüklenemedi.");
    expect(images(card)).toHaveLength(0);
    expect(observer().disconnected).toBe(true);
  });

  it("puts a markup file name in the title as text", async () => {
    const hass = makeHass({ history: [historyEntry({ file_name: "<b>x</b>.pdf", pages: 1 })] });
    const card = await openPreview(hass);
    expect(text(card, "preview-title")).toBe("<b>x</b>.pdf");
    expect(card.shadowRoot.querySelector("b")).toBeNull();
  });
});

describe("fix round 1", () => {
  const items = (card) => [...card.shadowRoot.querySelectorAll('[data-role="history-item"]')];
  const ANDROID = {
    userAgent: "Mozilla/5.0 (Linux; Android 15; Pixel 9) Chrome/131.0 Mobile",
    platform: "Linux armv8l",
    maxTouchPoints: 5,
  };
  function fakeNavigator(props) {
    for (const [key, value] of Object.entries(props)) {
      Object.defineProperty(navigator, key, { value, configurable: true });
    }
    return () => {
      for (const key of Object.keys(props)) delete navigator[key];
    };
  }
  function fakeValue(input, initial) {
    let value = initial;
    Object.defineProperty(input, "value", {
      get: () => value,
      set: (next) => {
        value = next;
      },
      configurable: true,
    });
    return () => value;
  }

  it("stops the page behind from scrolling while a dialog is open", async () => {
    document.documentElement.style.overflow = "scroll";
    try {
      const card = await mount(makeHass({ history: [historyEntry({ pages: 1 })] }));
      role(card, "history-button").click();
      await flush();
      expect(document.documentElement.style.overflow).toBe("hidden");
      items(card)[0].querySelector('[data-role="history-open"]').click();
      await flush();
      role(card, "preview-close").click();
      expect(document.documentElement.style.overflow).toBe("hidden");
      role(card, "history-close").click();
      expect(document.documentElement.style.overflow).toBe("scroll");
      role(card, "history-button").click();
      await flush();
      card.remove();
      expect(document.documentElement.style.overflow).toBe("scroll");
    } finally {
      document.documentElement.style.overflow = "";
    }
  });

  it("lets the same file be picked again through another picker", async () => {
    const restore = fakeNavigator(ANDROID);
    try {
      const card = await mount(makeHass());
      const file = role(card, "input-file");
      const photo = role(card, "input-photo");
      vi.spyOn(file, "click").mockImplementation(() => {});
      const fileValue = fakeValue(file, "C:\\fakepath\\a.jpg");
      const photoValue = fakeValue(photo, "");
      // Picking through the photo input clears the file input...
      Object.defineProperty(photo, "files", {
        value: [makeFile("a.jpg", "image/jpeg")],
        configurable: true,
      });
      photo.value = "C:\\fakepath\\a.jpg";
      photo.dispatchEvent(new Event("change"));
      await flush();
      expect(fileValue()).toBe("");
      expect(photoValue()).toBe("C:\\fakepath\\a.jpg");
      // ...and opening a picker clears its own value first.
      file.value = "C:\\fakepath\\a.jpg";
      role(card, "pick").click();
      $(card, '[data-option="file"]').click();
      expect(fileValue()).toBe("");
    } finally {
      restore();
    }
  });

  it("does not bring a deleted row back from a reload already under way", async () => {
    const hass = makeHass({
      history: [historyEntry({ id: "1".repeat(32) }), historyEntry({ id: "2".repeat(32) })],
      jobs: [{ job_id: 42, state: "processing", reasons: [] }],
    });
    const card = await mount(hass);
    role(card, "history-button").click();
    await flush();
    const original = hass.callWS.getMockImplementation();
    let release;
    hass.callWS.mockImplementation(async (msg) => {
      const result = await original(msg);
      if (msg.type === "home_print/history") {
        await new Promise((resolve) => {
          release = resolve;
        });
      }
      return result;
    });
    await selectFile(card, makeFile("rapor.pdf", "application/pdf"));
    await clickPrint(card);
    expect(release).toBeTypeOf("function");
    items(card)[0].querySelector('[data-role="history-delete"]').click();
    await flush();
    expect(items(card)).toHaveLength(1);
    release();
    await flush();
    expect(items(card)).toHaveLength(1);
    expect(items(card)[0].textContent).toContain("rapor.pdf");
  });

  it("moves focus to the next trash button after a delete, else to close", async () => {
    const hass = makeHass({
      history: [historyEntry({ id: "1".repeat(32) }), historyEntry({ id: "2".repeat(32) })],
    });
    const card = await mount(hass);
    role(card, "history-button").click();
    await flush();
    items(card)[0].querySelector('[data-role="history-delete"]').click();
    await flush();
    const next = items(card)[0].querySelector('[data-role="history-delete"]');
    expect(card.shadowRoot.activeElement).toBe(next);
    next.click();
    await flush();
    expect(card.shadowRoot.activeElement).toBe(role(card, "history-close"));
  });

  it("has an accessible menu with focus and arrow keys", async () => {
    const restore = fakeNavigator(ANDROID);
    try {
      const card = await mount(makeHass());
      const pick = role(card, "pick");
      expect(pick.getAttribute("aria-haspopup")).toBe("menu");
      expect(pick.getAttribute("aria-expanded")).toBe("false");
      pick.click();
      const options = [...card.shadowRoot.querySelectorAll("[data-option]")];
      expect(card.shadowRoot.activeElement).toBe(options[0]);
      const key = (k) =>
        card.shadowRoot.activeElement.dispatchEvent(
          new KeyboardEvent("keydown", { key: k, bubbles: true }),
        );
      key("ArrowDown");
      expect(card.shadowRoot.activeElement).toBe(options[1]);
      key("ArrowDown");
      key("ArrowDown");
      expect(card.shadowRoot.activeElement).toBe(options[0]);
      key("ArrowUp");
      expect(card.shadowRoot.activeElement).toBe(options[2]);
      key("Escape");
      expect(role(card, "pick-menu").hidden).toBe(true);
      expect(card.shadowRoot.activeElement).toBe(pick);
    } finally {
      restore();
    }
  });
});

describe("final review", () => {
  const items = (card) => [...card.shadowRoot.querySelectorAll('[data-role="history-item"]')];

  it("does not offer a preview for a record that never had a file", async () => {
    const hass = makeHass({
      history: [
        historyEntry({ id: "1".repeat(32), file: false, mime: null, state: "error", pages: null }),
        historyEntry({ id: "2".repeat(32), file: false, mime: "application/pdf" }),
      ],
    });
    const card = await mount(hass);
    role(card, "history-button").click();
    await flush();
    const [never, gone] = items(card);
    expect(never.textContent).not.toContain("dosya yok");
    const open = never.querySelector('[data-role="history-open"]');
    expect(open.tagName).not.toBe("BUTTON");
    expect(open.classList.contains("static")).toBe(true);
    open.click();
    await flush();
    expect(role(card, "preview-dialog").open).toBe(false);
    expect(never.querySelector('[data-role="history-delete"]')).toBeTruthy();
    // A file that was kept and has expired still says so.
    expect(gone.textContent).toContain("dosya yok");
    gone.querySelector('[data-role="history-open"]').click();
    await flush();
    expect(role(card, "preview-dialog").open).toBe(true);
    expect(text(card, "preview-body")).toBe("Bu dosya artık saklanmıyor.");
  });

  it("closes the pick menu when focus leaves it", async () => {
    Object.defineProperty(navigator, "userAgent", { value: "Android", configurable: true });
    try {
      const outside = document.createElement("button");
      document.body.append(outside);
      const card = await mount(makeHass());
      const menu = role(card, "pick-menu");
      const first = $(card, '[data-option="file"]');
      role(card, "pick").click();
      expect(menu.hidden).toBe(false);
      // Moving within the menu, or back to the button, keeps it open.
      first.dispatchEvent(
        new FocusEvent("focusout", { bubbles: true, composed: true, relatedTarget: $(card, '[data-option="photo"]') }),
      );
      expect(menu.hidden).toBe(false);
      first.dispatchEvent(
        new FocusEvent("focusout", { bubbles: true, composed: true, relatedTarget: role(card, "pick") }),
      );
      expect(menu.hidden).toBe(false);
      // Tabbing on to anything else closes it.
      first.dispatchEvent(
        new FocusEvent("focusout", { bubbles: true, composed: true, relatedTarget: role(card, "copies") }),
      );
      expect(menu.hidden).toBe(true);
      role(card, "pick").click();
      role(card, "pick").dispatchEvent(
        new FocusEvent("focusout", { bubbles: true, composed: true, relatedTarget: outside }),
      );
      expect(menu.hidden).toBe(true);
    } finally {
      delete navigator.userAgent;
    }
  });
});

describe("scan", () => {
  const REC_ID = "c".repeat(32);
  const scanPrinter = (scanner = {}, overrides = {}) =>
    deskjetPrinter({ scanner: scannerBlock(scanner), ...overrides });
  const options = (card, name) =>
    [...role(card, name).querySelectorAll("option")].map((o) => o.value);
  const wsCalls = (hass, type) => hass.calls.filter((m) => m.type === type);
  const visible = (card, name) => Boolean(role(card, name)) && !role(card, name).hidden;

  async function openPanel(card) {
    role(card, "scan-toggle").click();
    await flush();
  }

  // Start a scan that the fake finishes on the first poll with `record`.
  async function scanToDone(record = scanRecord(), extra = {}) {
    const hass = makeHass({
      printers: [scanPrinter()],
      scanStates: [scanState({ state: "done", pages: record.pages, record })],
      scans: [record],
      ...extra,
    });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    return { hass, card };
  }

  it("scan toggle hidden without scanner", async () => {
    const card = await mount(makeHass());
    expect(visible(card, "scan-toggle")).toBe(false);
    expect(visible(card, "scan-panel")).toBe(false);
  });

  it("scan toggle opens panel with caps options", async () => {
    const card = await mount(makeHass({ printers: [scanPrinter()] }));
    const toggle = role(card, "scan-toggle");
    expect(visible(card, "scan-toggle")).toBe(true);
    expect(toggle.textContent.trim()).toBe("Tara");
    expect(toggle.querySelector("svg path")).toBeTruthy();
    // Right under the Print button.
    expect(role(card, "print").nextElementSibling).toBe(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(visible(card, "scan-panel")).toBe(false);
    await openPanel(card);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(visible(card, "scan-panel")).toBe(true);
    expect(options(card, "scan-source")).toEqual(["platen", "adf"]);
    expect(role(card, "scan-source").value).toBe("platen");
    expect(options(card, "scan-color")).toEqual(["color", "gray", "bw"]);
    expect(role(card, "scan-color").value).toBe("color");
    expect(options(card, "scan-resolution")).toEqual(["75", "150", "300", "600"]);
    expect(role(card, "scan-resolution").value).toBe("300");
    expect(options(card, "scan-format")).toEqual(["pdf", "jpeg"]);
    expect(text(card, "scan-start")).toBe("Taramayı başlat");
    await openPanel(card);
    expect(visible(card, "scan-panel")).toBe(false);

    // A single source needs no source choice.
    document.body.innerHTML = "";
    const single = await mount(
      makeHass({
        printers: [scanPrinter({ sources: { platen: scannerBlock().sources.platen } })],
      }),
    );
    await openPanel(single);
    expect($(single, '[data-scan="source"]').hidden).toBe(true);
  });

  it("source change refreshes resolutions", async () => {
    const hass = makeHass({ printers: [scanPrinter()] });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-color").value = "bw";
    setInput(card, "scan-source", "adf");
    await flush();
    expect(options(card, "scan-color")).toEqual(["color", "gray"]);
    expect(role(card, "scan-color").value).toBe("color");
    expect(options(card, "scan-resolution")).toEqual(["150", "300"]);
    expect(role(card, "scan-resolution").value).toBe("300");
    role(card, "scan-start").click();
    await flush();
    expect(wsCalls(hass, "home_print/scan/start")[0]).toMatchObject({
      source: "adf",
      color_mode: "color",
      resolution: 300,
    });
  });

  it("start sends ws and polls to done then shows result", async () => {
    const record = scanRecord({ pages: 3 });
    const hass = makeHass({
      printers: [scanPrinter()],
      scanStates: [
        scanState({ pages: 1 }),
        scanState({ state: "saving", pages: 3 }),
        scanState({ state: "done", pages: 3, record }),
      ],
    });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    role(card, "scan-start").click();
    await flush();
    expect(wsCalls(hass, "home_print/scan/start")).toEqual([
      {
        type: "home_print/scan/start",
        entry_id: "deskjet",
        source: "platen",
        color_mode: "color",
        resolution: 300,
        format: "pdf",
      },
    ]);
    expect(text(card, "scan-message")).toBe("Taranıyor…");
    expect(role(card, "scan-start").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(1499);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(wsCalls(hass, "home_print/scan/state")[0]).toEqual({
      type: "home_print/scan/state",
      entry_id: "deskjet",
      scan_id: "s1",
    });
    expect(text(card, "scan-message")).toBe("Taranıyor… (2. sayfa)");
    await vi.advanceTimersByTimeAsync(1500);
    expect(text(card, "scan-message")).toBe("Kaydediliyor…");
    expect(visible(card, "scan-result")).toBe(false);
    await vi.advanceTimersByTimeAsync(1500);
    expect(role(card, "scan-start").disabled).toBe(false);
    expect(visible(card, "scan-result")).toBe(true);
    expect(role(card, "scan-name").value).toBe(record.name);
    expect(role(card, "scan-img").getAttribute("src")).toBe(
      `/api/home_print/scans/deskjet/${REC_ID}/page/1?authSig=sig`,
    );
    expect(text(card, "scan-page-label")).toBe("Sayfa 1/3");
    expect(role(card, "scan-prev").disabled).toBe(true);
    role(card, "scan-next").click();
    await flush();
    expect(text(card, "scan-page-label")).toBe("Sayfa 2/3");
    expect(role(card, "scan-img").getAttribute("src")).toBe(
      `/api/home_print/scans/deskjet/${REC_ID}/page/2?authSig=sig`,
    );
    // Polling has stopped.
    const polls = wsCalls(hass, "home_print/scan/state").length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(polls);
  });

  it("busy error shown", async () => {
    const hass = makeHass({ printers: [scanPrinter()], scanStart: { error: "scanner_busy" } });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    expect(text(card, "scan-message")).toBe("Tarayıcı şu an meşgul.");
    expect(role(card, "scan-message").classList.contains("error")).toBe(true);
    expect(role(card, "scan-start").disabled).toBe(false);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(0);

    // An error the scan ends with, and an unknown code.
    const helpers = HomePrintCard.helpers;
    expect(helpers.scanErrorText("tr", "adf_empty")).toBe("Besleyicide kâğıt yok.");
    expect(helpers.scanErrorText("tr", "scanner_unavailable")).toBe("Tarayıcıya ulaşılamadı.");
    expect(helpers.scanErrorText("en", "scanner_busy")).toBe("The scanner is busy right now.");
    expect(helpers.scanErrorText("tr", "weird")).toBe(helpers.scanErrorText("tr", "scan_failed"));

    document.body.innerHTML = "";
    const hass2 = makeHass({
      printers: [scanPrinter()],
      scanStates: [scanState({ state: "error", error: "adf_empty" })],
    });
    const card2 = await mount(hass2);
    await openPanel(card2);
    role(card2, "scan-start").click();
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(text(card2, "scan-message")).toBe("Besleyicide kâğıt yok.");
    expect(role(card2, "scan-start").disabled).toBe(false);
  });

  it("download uses signed file path", async () => {
    const clicks = [];
    const spy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function () {
        clicks.push({ href: this.getAttribute("href"), download: this.hasAttribute("download") });
      });
    try {
      const { hass, card } = await scanToDone();
      role(card, "scan-download").click();
      await flush();
      const signs = wsCalls(hass, "auth/sign_path").map((m) => m.path);
      expect(signs).toContain(`/api/home_print/scans/deskjet/${REC_ID}/file`);
      expect(clicks).toEqual([
        { href: `/api/home_print/scans/deskjet/${REC_ID}/file?authSig=sig`, download: true },
      ]);
      // The temporary link does not stay behind.
      expect(card.shadowRoot.querySelector("a[download]")).toBe(null);
    } finally {
      spy.mockRestore();
    }
  });

  it("add page sends append_to and hidden for jpeg", async () => {
    const record = scanRecord({ color_mode: "gray", resolution: 150 });
    const { hass, card } = await scanToDone(record);
    expect(visible(card, "scan-add")).toBe(true);
    role(card, "scan-format").value = "jpeg";
    role(card, "scan-add").click();
    await flush();
    expect(wsCalls(hass, "home_print/scan/start")[1]).toEqual({
      type: "home_print/scan/start",
      entry_id: "deskjet",
      source: "platen",
      color_mode: "gray",
      resolution: 150,
      format: "pdf",
      append_to: REC_ID,
    });

    for (const other of [scanRecord({ mime: "image/jpeg" }), scanRecord({ source: "adf" })]) {
      document.body.innerHTML = "";
      const done = await scanToDone(other);
      expect(visible(done.card, "scan-result")).toBe(true);
      expect(visible(done.card, "scan-add")).toBe(false);
    }
  });

  it("rename on enter", async () => {
    const { hass, card } = await scanToDone();
    const input = role(card, "scan-name");
    input.value = "  fatura  ";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await flush();
    expect(wsCalls(hass, "home_print/scans/rename")).toEqual([
      { type: "home_print/scans/rename", entry_id: "deskjet", scan_record_id: REC_ID, name: "fatura" },
    ]);
    expect(input.value).toBe("fatura");
    input.dispatchEvent(new Event("blur"));
    await flush();
    expect(wsCalls(hass, "home_print/scans/rename")).toHaveLength(1);
    input.value = "makbuz";
    input.dispatchEvent(new Event("blur"));
    await flush();
    expect(wsCalls(hass, "home_print/scans/rename")).toHaveLength(2);
  });

  it("delete needs two taps", async () => {
    const { hass, card } = await scanToDone();
    const button = role(card, "scan-delete");
    expect(button.textContent.trim()).toBe("Sil");
    button.click();
    await flush();
    expect(wsCalls(hass, "home_print/scans/delete")).toHaveLength(0);
    expect(button.textContent.trim()).toBe("Emin misin?");
    await vi.advanceTimersByTimeAsync(4000);
    expect(button.textContent.trim()).toBe("Sil");
    button.click();
    await flush();
    button.click();
    await flush();
    expect(wsCalls(hass, "home_print/scans/delete")).toEqual([
      { type: "home_print/scans/delete", entry_id: "deskjet", scan_record_id: REC_ID },
    ]);
    expect(visible(card, "scan-result")).toBe(false);
  });

  it("resumes active scan on reconnect", async () => {
    const record = scanRecord();
    const hass = makeHass({
      printers: [scanPrinter({ active_scan_id: "s9" })],
      scanStates: [scanState({ scan_id: "s9", pages: 0 }), scanState({ scan_id: "s9", state: "done", pages: 1, record })],
    });
    const card = await mount(hass);
    expect(visible(card, "scan-panel")).toBe(true);
    expect(role(card, "scan-toggle").getAttribute("aria-expanded")).toBe("true");
    expect(role(card, "scan-start").disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(1500);
    expect(wsCalls(hass, "home_print/scan/state")[0]).toEqual({
      type: "home_print/scan/state",
      entry_id: "deskjet",
      scan_id: "s9",
    });
    await vi.advanceTimersByTimeAsync(1500);
    expect(visible(card, "scan-result")).toBe(true);
    // A printers list that still names the scan does not start it over.
    await vi.advanceTimersByTimeAsync(60_000);
    expect(visible(card, "scan-result")).toBe(true);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(2);
    // A finished last_scan alone does not open the panel.
    document.body.innerHTML = "";
    const quiet = await mount(
      makeHass({ printers: [scanPrinter({ last_scan: scanState({ state: "done", record }) })] }),
    );
    expect(visible(quiet, "scan-panel")).toBe(false);
  });

  it("history tabs switch to scans list", async () => {
    const hass = makeHass({
      printers: [scanPrinter()],
      history: [historyEntry()],
      scans: [scanRecord({ pages: 2, name: "fatura" }), scanRecord({ id: "d".repeat(32), name: "makbuz" })],
    });
    const card = await mount(hass);
    role(card, "history-button").click();
    await flush();
    expect(visible(card, "history-tabs")).toBe(true);
    expect(role(card, "history-tabs").getAttribute("role")).toBe("tablist");
    expect(role(card, "tab-prints").getAttribute("aria-selected")).toBe("true");
    expect(text(card, "tab-prints")).toBe("Baskılar");
    expect(text(card, "tab-scans")).toBe("Taramalar");
    expect(card.shadowRoot.querySelectorAll('[data-role="history-item"]')).toHaveLength(1);
    role(card, "tab-scans").click();
    await flush();
    expect(role(card, "tab-scans").getAttribute("aria-selected")).toBe("true");
    expect(wsCalls(hass, "home_print/scans")).toEqual([{ type: "home_print/scans", entry_id: "deskjet" }]);
    const rows = [...card.shadowRoot.querySelectorAll('[data-role="scan-item"]')];
    expect(rows).toHaveLength(2);
    expect(card.shadowRoot.querySelectorAll('[data-role="history-item"]')).toHaveLength(0);
    expect(rows[0].textContent).toContain("fatura");
    expect(rows[0].textContent).toContain("2 sayfa");
    expect(rows[0].textContent).toContain("Ada");
    expect(rows[0].querySelector('[data-role="scan-row-download"]')).toBeTruthy();
    // The row trash also asks once.
    const trash = rows[1].querySelector('[data-role="scan-row-delete"]');
    trash.click();
    await flush();
    expect(wsCalls(hass, "home_print/scans/delete")).toHaveLength(0);
    trash.click();
    await flush();
    expect(wsCalls(hass, "home_print/scans/delete")).toHaveLength(1);
    expect(card.shadowRoot.querySelectorAll('[data-role="scan-item"]')).toHaveLength(1);
    role(card, "tab-prints").click();
    await flush();
    expect(card.shadowRoot.querySelectorAll('[data-role="history-item"]')).toHaveLength(1);

    document.body.innerHTML = "";
    const plain = await mount(makeHass());
    role(plain, "history-button").click();
    await flush();
    expect(visible(plain, "history-tabs")).toBe(false);
  });

  it("scan row opens preview with scan page path", async () => {
    const realObserver = window.IntersectionObserver;
    window.IntersectionObserver = undefined;
    try {
      const hass = makeHass({ printers: [scanPrinter()], scans: [scanRecord({ pages: 2 })] });
      const card = await mount(hass);
      role(card, "history-button").click();
      await flush();
      role(card, "tab-scans").click();
      await flush();
      $(card, '[data-role="scan-open"]').click();
      await flush();
      expect(role(card, "preview-dialog").open).toBe(true);
      expect(text(card, "preview-title")).toBe("tarama_2026-11-16_1652");
      expect(role(card, "preview-body").querySelectorAll("[data-page]")).toHaveLength(2);
      const signs = wsCalls(hass, "auth/sign_path").map((m) => m.path);
      expect(signs).toEqual([`/api/home_print/scans/deskjet/${REC_ID}/page/1`]);
    } finally {
      window.IntersectionObserver = realObserver;
    }
  });

  it("admin_only disables scan toggle", async () => {
    const hass = makeHass({
      printers: [scanPrinter({ active_scan_id: "s9" }, { can_print: false })],
      scans: [scanRecord()],
    });
    const card = await mount(hass);
    expect(visible(card, "scan-toggle")).toBe(true);
    expect(role(card, "scan-toggle").disabled).toBe(true);
    expect(visible(card, "scan-panel")).toBe(false);
    await vi.advanceTimersByTimeAsync(3000);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(0);
    // Viewing stays open: the scans tab lists with download but no trash.
    role(card, "history-button").click();
    await flush();
    role(card, "tab-scans").click();
    await flush();
    const row = $(card, '[data-role="scan-item"]');
    expect(row.querySelector('[data-role="scan-row-download"]')).toBeTruthy();
    expect(row.querySelector('[data-role="scan-row-delete"]')).toBe(null);
  });

  it("disconnect stops scan polling and resumes on reconnect", async () => {
    const hass = makeHass({ printers: [scanPrinter()], scanStates: [scanState({ pages: 0 })] });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    card.remove();
    await vi.advanceTimersByTimeAsync(5000);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(0);
    document.body.appendChild(card);
    await vi.advanceTimersByTimeAsync(1500);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(1);
  });

  it("disconnect disarms a pending delete", async () => {
    const { card } = await scanToDone();
    const button = role(card, "scan-delete");
    button.click();
    expect(button.textContent.trim()).toBe("Emin misin?");
    card.remove();
    expect(button.textContent.trim()).toBe("Sil");
  });

  it("printer switch resets the panel", async () => {
    const other = scanPrinter({}, { entry_id: "other", title: "Other" });
    const hass = makeHass({ printers: [scanPrinter(), other], scanStates: [scanState()] });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    expect(role(card, "scan-start").disabled).toBe(true);
    setInput(card, "picker", "other");
    await flush();
    expect(visible(card, "scan-panel")).toBe(false);
    expect(role(card, "scan-toggle").getAttribute("aria-expanded")).toBe("false");
    await vi.advanceTimersByTimeAsync(5000);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(0);
    await openPanel(card);
    expect(role(card, "scan-start").disabled).toBe(false);
    expect(text(card, "scan-message")).toBe("");
  });

  it("fatal poll error stops polling", async () => {
    const hass = makeHass({ printers: [scanPrinter()], scanStates: [{ code: "not_found" }] });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(text(card, "scan-message")).toContain("Taramanın durumu alınamıyor");
    expect(role(card, "scan-message").classList.contains("error")).toBe(true);
    expect(role(card, "scan-start").disabled).toBe(false);
    await vi.advanceTimersByTimeAsync(5000);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(1);
  });

  it("start reply without scan_id is handled", async () => {
    const hass = makeHass({ printers: [scanPrinter()], scanStart: scanState({ scan_id: null }) });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    expect(text(card, "scan-message")).toBe("Tarama yapılamadı. Birazdan tekrar dene.");
    expect(role(card, "scan-start").disabled).toBe(false);
    await vi.advanceTimersByTimeAsync(5000);
    expect(wsCalls(hass, "home_print/scan/state")).toHaveLength(0);
  });

  it("done without record points to the Scans list", async () => {
    const hass = makeHass({
      printers: [scanPrinter()],
      scanStates: [scanState({ state: "done", pages: 1 })],
    });
    const card = await mount(hass);
    await openPanel(card);
    role(card, "scan-start").click();
    await flush();
    await vi.advanceTimersByTimeAsync(1500);
    expect(text(card, "scan-message")).toBe("Tarama kaydedildi. Geçmiş > Taramalar'da bulabilirsin.");
    expect(text(card, "scan-message")).not.toContain("✓");
    expect(visible(card, "scan-result")).toBe(false);
  });

  it("a resumed scan opens its result on the last page", async () => {
    const record = scanRecord({ pages: 3 });
    const hass = makeHass({
      printers: [scanPrinter({ active_scan_id: "s9" })],
      scanStates: [scanState({ scan_id: "s9", state: "done", pages: 3, record })],
    });
    const card = await mount(hass);
    await vi.advanceTimersByTimeAsync(1500);
    expect(text(card, "scan-page-label")).toBe("Sayfa 3/3");
  });

  it("an older rename reply doesn't undo a newer one", async () => {
    const { hass, card } = await scanToDone();
    const replies = [];
    const original = hass.callWS.getMockImplementation();
    hass.callWS.mockImplementation((msg) => {
      if (msg.type !== "home_print/scans/rename") return original(msg);
      hass.calls.push(msg);
      return new Promise((resolve) => replies.push({ msg, resolve }));
    });
    const input = role(card, "scan-name");
    const enter = () =>
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    input.value = "birinci";
    enter();
    input.value = "ikinci";
    enter();
    expect(replies).toHaveLength(2);
    // The newer one answers first, then the older one.
    replies[1].resolve({ entry: scanRecord({ name: "ikinci" }) });
    await flush();
    replies[0].resolve({ entry: scanRecord({ name: "birinci" }) });
    await flush();
    expect(input.value).toBe("ikinci");
    input.dispatchEvent(new Event("blur"));
    await flush();
    expect(replies).toHaveLength(2);
  });

  it("history tabs are linked to their panel", async () => {
    const card = await mount(makeHass({ printers: [scanPrinter()] }));
    role(card, "history-button").click();
    await flush();
    const panel = role(card, "history-panel");
    expect(panel.getAttribute("role")).toBe("tabpanel");
    for (const name of ["tab-prints", "tab-scans"]) {
      expect(role(card, name).getAttribute("aria-controls")).toBe(panel.id);
    }
    expect(panel.getAttribute("aria-labelledby")).toBe(role(card, "tab-prints").id);
    role(card, "tab-scans").click();
    await flush();
    expect(role(card, "tab-scans").getAttribute("aria-selected")).toBe("true");
    expect(role(card, "tab-prints").getAttribute("aria-selected")).toBe("false");
    expect(panel.getAttribute("aria-labelledby")).toBe(role(card, "tab-scans").id);

    document.body.innerHTML = "";
    const plain = await mount(makeHass());
    role(plain, "history-button").click();
    await flush();
    expect(role(plain, "history-panel").hasAttribute("role")).toBe(false);
  });

  it("has English scan texts", async () => {
    const card = await mount(makeHass({ language: "en", printers: [scanPrinter()] }));
    expect(role(card, "scan-toggle").textContent.trim()).toBe("Scan");
    await openPanel(card);
    expect(text(card, "scan-start")).toBe("Start scan");
    role(card, "history-button").click();
    await flush();
    expect(text(card, "tab-prints")).toBe("Prints");
    expect(text(card, "tab-scans")).toBe("Scans");
  });
});
