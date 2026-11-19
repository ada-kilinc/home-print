// Printer switcher in the header.

import { writeStored } from "./helpers.js";
import { t } from "./i18n.js";
import { svgIcon } from "./icons.js";

export class SwitcherPart {
  _selectPrinter(entryId) {
    if (!entryId) return;
    const changed = entryId !== this._printer()?.entry_id;
    this._pickedId = entryId;
    writeStored(this._storageKey, entryId);
    this._update();
    // A fresh list, so a scan running on that printer is picked up at once.
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
    const multi = printers.length > 1 || (unknown && printers.length > 0);
    const who = this._role("who");
    const button = this._role("switcher");
    // With a choice the icon and name sit in the button, before the chevron;
    // a single printer gets them in a plain span, with nothing to press.
    const home = multi ? button : who;
    if (this._role("title").parentNode !== home) {
      home.prepend(this._role("who-icon"), this._role("title"));
    }
    who.hidden = multi;
    button.hidden = !multi;
    // A scanner without a printer gets the scanner icon.
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
      p.entry_id === current,
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
}
