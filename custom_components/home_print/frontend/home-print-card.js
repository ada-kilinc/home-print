/* Home Print dashboard card (skeleton; filled in by a later task). */
class HomePrintCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
  }

  getCardSize() {
    return 3;
  }
}

if (!customElements.get("home-print-card")) {
  customElements.define("home-print-card", HomePrintCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "home-print-card",
  name: "Home Print",
  description:
    "Yazıcıya dosya gönder ve durumu izle. / Send files to a printer and monitor its status.",
});
