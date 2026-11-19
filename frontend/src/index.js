// Registers the card and its editor with Home Assistant.

import { HomePrintCard } from "./card.js";
import { CARD_TYPE, EDITOR_TYPE } from "./constants.js";
import { HomePrintCardEditor } from "./editor.js";
import {
  buildForm,
  formatHistoryTime,
  historyStateIcon,
  isIOS,
  isProblemState,
  isWordFile,
  jobLabel,
  reasonLabel,
  scanErrorText,
  scanFilePath,
  scanPagePath,
  usesPickMenu,
  validateFile,
  visibleRawReasons,
} from "./helpers.js";
import { pickLanguage, t } from "./i18n.js";

HomePrintCard.helpers = Object.freeze({
  pickLanguage,
  t,
  isWordFile,
  validateFile,
  buildForm,
  jobLabel,
  reasonLabel,
  visibleRawReasons,
  isProblemState,
  isIOS,
  usesPickMenu,
  formatHistoryTime,
  historyStateIcon,
  scanErrorText,
  scanPagePath,
  scanFilePath,
});

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, HomePrintCard);
}

if (!customElements.get(EDITOR_TYPE)) {
  customElements.define(EDITOR_TYPE, HomePrintCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: "Home Print",
    description:
      "Yazıcıya dosya gönder ve durumu izle. / Send files to a printer and monitor its status.",
  });
}
