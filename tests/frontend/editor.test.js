import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { deskjetPrinter, makeHass } from "./fake-hass.js";

let errorSpy;

beforeAll(async () => {
  await import("../../custom_components/home_print/frontend/home-print-card.js");
});

beforeEach(() => {
  errorSpy = vi.spyOn(console, "error");
});

afterEach(() => {
  document.body.innerHTML = "";
  expect(errorSpy).not.toHaveBeenCalled();
  errorSpy.mockRestore();
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const two = () => [deskjetPrinter(), deskjetPrinter({ entry_id: "office", title: "Office" })];

async function mount(config, hass = makeHass({ printers: two() })) {
  const editor = document.createElement("home-print-card-editor");
  const events = [];
  editor.addEventListener("config-changed", (ev) => events.push(ev));
  editor.setConfig(config);
  document.body.appendChild(editor);
  editor.hass = hass;
  await flush();
  return { editor, events };
}

const role = (editor, name) => editor.shadowRoot.querySelector(`[data-role="${name}"]`);
const change = (el, ev = "change") => el.dispatchEvent(new Event(ev));

describe("home-print-card-editor", () => {
  it("is registered and returned by getConfigElement", () => {
    const card = customElements.get("home-print-card");
    expect(customElements.get("home-print-card-editor")).toBeTruthy();
    expect(card.getConfigElement().localName).toBe("home-print-card-editor");
  });

  it("lists printers plus an automatic option, and selects the configured one", async () => {
    const { editor } = await mount({ type: "custom:home-print-card", entry_id: "office" });
    const select = role(editor, "printer");
    expect([...select.options].map((o) => o.value)).toEqual(["", "deskjet", "office"]);
    expect(select.options[0].textContent).toBe("Otomatik (ilk yazıcı)");
    expect(select.options[2].textContent).toBe("Office");
    expect(select.value).toBe("office");
  });

  it("uses English labels for English hass", async () => {
    const { editor } = await mount({}, makeHass({ language: "en", printers: two() }));
    expect(role(editor, "printer").options[0].textContent).toBe("Automatic (first printer)");
  });

  it("keeps an unknown entry_id selected as not found", async () => {
    const { editor, events } = await mount({ entry_id: "gone" });
    const select = role(editor, "printer");
    expect(select.value).toBe("gone");
    expect(select.selectedOptions[0].textContent).toBe("gone (bulunamadı)");
    expect(events).toHaveLength(0);
  });

  it("writes entry_id on select and removes it for automatic", async () => {
    const { editor, events } = await mount({ type: "custom:home-print-card", title: "T" });
    const select = role(editor, "printer");
    select.value = "office";
    change(select);
    expect(events[0].detail.config).toEqual({
      type: "custom:home-print-card",
      title: "T",
      entry_id: "office",
    });
    expect(events[0].bubbles).toBe(true);
    expect(events[0].composed).toBe(true);
    select.value = "";
    change(select);
    expect(events[1].detail.config).toEqual({ type: "custom:home-print-card", title: "T" });
    expect("entry_id" in events[1].detail.config).toBe(false);
  });

  it("writes title and removes it when empty", async () => {
    const { editor, events } = await mount({ type: "custom:home-print-card" });
    const title = role(editor, "title");
    title.value = "Ofis";
    change(title, "input");
    expect(events.at(-1).detail.config.title).toBe("Ofis");
    title.value = "";
    change(title, "input");
    expect("title" in events.at(-1).detail.config).toBe(false);
  });

  it("writes show_ink false explicitly and removes it when true", async () => {
    const { editor, events } = await mount({ type: "custom:home-print-card" });
    const box = role(editor, "show_ink");
    expect(box.checked).toBe(true);
    box.checked = false;
    change(box);
    expect(events.at(-1).detail.config.show_ink).toBe(false);
    box.checked = true;
    change(box);
    expect("show_ink" in events.at(-1).detail.config).toBe(false);
  });

  it("reflects show_ink false and never mutates the incoming config", async () => {
    const config = Object.freeze({ type: "custom:home-print-card", show_ink: false });
    const { editor, events } = await mount(config);
    expect(role(editor, "show_ink").checked).toBe(false);
    const select = role(editor, "printer");
    select.value = "deskjet";
    change(select);
    expect(config).toEqual({ type: "custom:home-print-card", show_ink: false });
    expect(events[0].detail.config.show_ink).toBe(false);
  });

  it("still works when the printer list fails to load", async () => {
    const { editor } = await mount({}, makeHass({ printersError: new Error("x") }));
    expect([...role(editor, "printer").options].map((o) => o.value)).toEqual([""]);
  });

  it("keeps the option nodes when hass changes but the list does not", async () => {
    const hass = makeHass({ printers: two() });
    const { editor } = await mount({ entry_id: "office" }, hass);
    const select = role(editor, "printer");
    const before = [...select.options];
    editor.hass = { ...hass, states: { ...hass.states } };
    editor.setConfig({ entry_id: "office" });
    await flush();
    expect([...select.options]).toEqual(before);
    expect(select.options[2]).toBe(before[2]);
    expect(select.value).toBe("office");

    editor.hass = makeHass({ language: "en", printers: two() });
    await flush();
    expect(select.options[0]).not.toBe(before[0]);
    expect(select.options[0].textContent).toBe("Automatic (first printer)");
  });

  it("retries a failed printer load on a later hass, at most every 30 s", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date("2026-11-16T12:00:00Z"));
      const failing = makeHass({ printersError: new Error("x") });
      const { editor } = await mount({}, failing);
      const count = () => failing.callWS.mock.calls.length;
      expect(count()).toBe(1);
      editor.hass = failing;
      await flush();
      expect(count()).toBe(1);

      vi.setSystemTime(new Date("2026-11-16T12:00:31Z"));
      const working = makeHass({ printers: two() });
      editor.hass = working;
      await flush();
      expect(working.callWS).toHaveBeenCalledTimes(1);
      expect([...role(editor, "printer").options].map((o) => o.value)).toEqual([
        "",
        "deskjet",
        "office",
      ]);
      editor.hass = working;
      await flush();
      expect(working.callWS).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses touch targets of at least 44px", () => {
    const editor = document.createElement("home-print-card-editor");
    expect(editor.shadowRoot.innerHTML).toContain("min-height: 44px");
  });
});
