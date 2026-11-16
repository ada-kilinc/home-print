import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { deskjetPrinter, deskjetStates, makeHass } from "./fake-hass.js";

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

async function selectFile(card, file, input = role(card, "file")) {
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
    expect(text(card, "last")).toContain("rapor.pdf");
    expect(text(card, "last")).toContain("✓");
    expect(text(card, "last")).toContain("Ada");

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
    expect(role(card, "file").value).toBe("");
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

  it("has a photo button that only accepts JPEG and PNG and uploads", async () => {
    const hass = makeHass({ jobs: [{ job_id: 42, state: "processing", reasons: [] }] });
    const card = await mount(hass);
    const file = role(card, "file");
    const photo = role(card, "photo");
    expect(file.getAttribute("accept")).toBe(
      "application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png",
    );
    expect(photo.type).toBe("file");
    expect(photo.getAttribute("accept")).toBe("image/jpeg,image/png");
    expect(photo.closest("label").textContent.trim()).toBe("Fotoğraf seç");
    await selectFile(card, makeFile("IMG_0001.JPG", "image/jpeg"), photo);
    expect(text(card, "file-name")).toBe("IMG_0001.JPG");
    await clickPrint(card);
    expect(hass.fetchWithAuth.mock.calls[0][1].body.get("file").name).toBe("IMG_0001.JPG");
    expect(photo.value).toBe("");
  });

  it("checks a photo like any other file", async () => {
    const hass = makeHass();
    const card = await mount(hass);
    await selectFile(card, makeFile("big.png", "image/png", 26 * 1024 * 1024), role(card, "photo"));
    expect(text(card, "message")).toContain("25");
    await clickPrint(card);
    expect(hass.fetchWithAuth).not.toHaveBeenCalled();
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
    states["sensor.deskjet_last_job"].state = "<b>son</b>.pdf";
    const card = await mount(makeHass({ states }));
    const name = '<img src=x onerror="alert(1)">.pdf';
    await selectFile(card, makeFile(name, "application/pdf"));
    expect(role(card, "file-name").textContent).toBe(name);
    expect(role(card, "ink").textContent).toContain('<img src=x onerror="alert(1)">');
    expect(text(card, "last")).toContain("<b>son</b>.pdf");
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
