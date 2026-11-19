// The card's CSS.

export const STYLE = `
  :host { display: block; }
  ha-card { display: block; overflow: hidden; }
  .card {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    box-sizing: border-box;
    min-width: 0;
  }
  [hidden] { display: none !important; }
  .header { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .header-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .who {
    flex: 0 1 auto;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    min-height: 44px;
    padding: 0;
    border: none;
    border-radius: 8px;
    background: none;
    font: inherit;
    color: inherit;
    text-align: start;
  }
  button.who { cursor: pointer; padding: 0 4px; margin: 0 -4px; }
  button.who:hover { background: var(--secondary-background-color, rgba(127, 127, 127, 0.12)); }
  .who svg { display: block; color: var(--secondary-text-color); }
  .who-icon, .chevron { flex: none; }
  .title {
    font-size: 1.2em;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .state {
    margin-left: auto;
    flex: none;
    color: var(--secondary-text-color);
    white-space: nowrap;
  }
  .printer-list {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    overflow: hidden;
  }
  .printer-option {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    padding: 0 16px;
    cursor: pointer;
    min-width: 0;
    outline: none;
  }
  .printer-option + .printer-option { border-top: 1px solid var(--divider-color); }
  .printer-option:hover, .printer-option:focus-visible {
    background: var(--secondary-background-color, rgba(127, 127, 127, 0.12));
  }
  .printer-option .check { width: 24px; flex: none; color: var(--primary-color); }
  .printer-option .check svg { display: block; }
  .printer-option[aria-selected="false"] .check svg { visibility: hidden; }
  .printer-option .name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .printer-option .status { flex: none; color: var(--secondary-text-color); white-space: nowrap; }
  svg { width: 24px; height: 24px; flex: none; fill: currentColor; }
  .icon-button {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    padding: 0;
    border: none;
    border-radius: 50%;
    background: none;
    color: var(--secondary-text-color);
    cursor: pointer;
  }
  .icon-button:hover { color: var(--primary-text-color); }
  .icon-button:disabled { opacity: 0.4; cursor: default; }
  select, input[type="number"], input[type="text"] {
    min-height: 44px;
    box-sizing: border-box;
    font: inherit;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    padding: 0 8px;
    max-width: 100%;
  }
  .notice {
    color: var(--error-color);
    border: 1px solid var(--error-color);
    border-radius: 8px;
    padding: 8px 12px;
  }
  .notice.info { color: var(--secondary-text-color); border-color: var(--divider-color); }
  .ink { display: flex; flex-wrap: wrap; gap: 8px 16px; }
  .marker { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .bar {
    width: 64px;
    height: 10px;
    border-radius: 5px;
    background: var(--divider-color);
    overflow: hidden;
    flex: none;
  }
  .bar-fill { height: 100%; }
  .pct { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .print-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .file-row {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  /* Choose file and Copies share one row, even on a ~300 px card. */
  .file-row .option[data-opt="copies"] { margin-left: auto; }
  .file-row .option input[type="number"] { width: 56px; }
  .file-info { flex: 1 1 100%; display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .file-button {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid var(--primary-color);
    font: inherit;
    color: var(--primary-color);
    background: none;
    cursor: pointer;
  }
  .hidden-input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    pointer-events: none;
  }
  .pick-menu {
    flex: 1 1 100%;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    overflow: hidden;
  }
  .pick-menu button {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 48px;
    padding: 0 16px;
    border: none;
    background: none;
    font: inherit;
    text-align: start;
    color: var(--primary-text-color);
    cursor: pointer;
  }
  .pick-menu button + button { border-top: 1px solid var(--divider-color); }
  .pick-menu button svg { color: var(--secondary-text-color); }
  .file-name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .file-size { flex: none; color: var(--secondary-text-color); }
  .options { display: flex; flex-wrap: wrap; gap: 8px 16px; min-width: 0; }
  .option { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; }
  .option input[type="checkbox"] { width: 24px; height: 24px; margin: 10px; accent-color: var(--primary-color); }
  .option input[type="number"] { width: 72px; }
  .pages { display: flex; align-items: center; gap: 8px; }
  .pages input { flex: 1 1 auto; min-width: 0; }
  .print {
    min-height: 48px;
    width: 100%;
    border: none;
    border-radius: 8px;
    font: inherit;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-primary-color);
    background: var(--primary-color);
    cursor: pointer;
  }
  .print:disabled { opacity: 0.5; cursor: default; }
  .message { min-height: 1.2em; overflow-wrap: anywhere; }
  .message.error { color: var(--error-color); }
  .detail {
    color: var(--secondary-text-color);
    font-size: 0.85em;
    overflow-wrap: anywhere;
  }

  /* Dialogs: showModal() puts them in the top layer, so a dashboard layout
     that contains fixed elements can't trap them inside the card. */
  dialog {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    max-width: none;
    max-height: none;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--primary-text-color);
    box-sizing: border-box;
    overscroll-behavior: contain;
  }
  dialog[open] { display: flex; align-items: flex-end; justify-content: center; }
  dialog::backdrop { background: var(--mdc-dialog-scrim-color, rgba(0, 0, 0, 0.32)); }
  .sheet {
    display: flex;
    flex-direction: column;
    width: 100%;
    max-height: 85vh;
    max-height: 85dvh;
    min-width: 0;
    box-sizing: border-box;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.2);
    padding-bottom: env(safe-area-inset-bottom, 0);
  }
  @media (min-width: 600px) {
    dialog[open] { align-items: center; }
    .sheet { max-width: 480px; border-radius: 16px; }
  }
  .sheet-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 8px 8px 16px;
    border-bottom: 1px solid var(--divider-color);
    min-width: 0;
  }
  .sheet-title {
    flex: 1 1 auto;
    min-width: 0;
    font-size: 1.1em;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sheet-status { padding: 12px 16px; color: var(--secondary-text-color); overflow-wrap: anywhere; }
  .sheet-status.error { color: var(--error-color); }
  .history-list {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    min-height: 0;
  }
  .history-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding-right: 8px;
    border-bottom: 1px solid var(--divider-color);
    min-width: 0;
  }
  .history-open {
    flex: 1 1 auto;
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    min-height: 56px;
    padding: 8px 8px 8px 16px;
    border: none;
    background: none;
    font: inherit;
    text-align: start;
    color: inherit;
    cursor: pointer;
  }
  .history-open.static { cursor: default; }
  .history-mark { flex: none; width: 1.5em; text-align: center; font-weight: 500; }
  .history-mark.ok { color: var(--success-color, var(--primary-color)); }
  .history-mark.bad { color: var(--error-color); }
  .history-mark.busy { color: var(--secondary-text-color); }
  .history-text { flex: 1 1 auto; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .history-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .history-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 8px;
    color: var(--secondary-text-color);
    font-size: 0.85em;
  }
  .tag {
    padding: 0 6px;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    font-size: 0.9em;
  }
  .preview-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
    overflow-y: auto;
    overscroll-behavior: contain;
    min-height: 0;
  }
  .page {
    width: 100%;
    aspect-ratio: 210 / 297;
    flex: none;
    background: var(--secondary-background-color);
  }
  .page.loaded { aspect-ratio: auto; background: none; }
  .preview-body img {
    display: block;
    width: 100%;
    height: auto;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  }
  .preview-body .sheet-status { padding: 0; }

  /* Scanning */
  .scan-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .scan-fields {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 8px 12px;
  }
  .scan-field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    color: var(--secondary-text-color);
    font-size: 0.9em;
  }
  .scan-field select { width: 100%; font-size: 1rem; }
  .scan-result { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .scan-page {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 8px;
    border-radius: 8px;
    background: var(--secondary-background-color);
  }
  .scan-page img {
    display: block;
    max-width: 100%;
    max-height: 240px;
    background: #fff;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.25);
  }
  .scan-page .sheet-status { padding: 8px; }
  .scan-nav { display: flex; align-items: center; justify-content: center; gap: 8px; }
  .scan-name { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .scan-name input { flex: 1 1 auto; min-width: 0; }
  .scan-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .file-button:disabled { opacity: 0.5; cursor: default; }
  .file-button.danger { color: var(--error-color); border-color: var(--error-color); }
  .icon-button.armed {
    width: auto;
    padding: 0 8px;
    border-radius: 8px;
    color: var(--error-color);
    white-space: nowrap;
  }
  .history-panel { display: flex; flex-direction: column; min-height: 0; }
  .tabs { display: flex; border-bottom: 1px solid var(--divider-color); }
  .tab {
    flex: 1 1 0;
    min-height: 48px;
    border: none;
    border-bottom: 2px solid transparent;
    background: none;
    font: inherit;
    font-weight: 500;
    color: var(--secondary-text-color);
    cursor: pointer;
  }
  .tab[aria-selected="true"] { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .tab:disabled { opacity: 0.5; cursor: default; }
  .history-mark svg { color: var(--secondary-text-color); vertical-align: middle; }
`;
