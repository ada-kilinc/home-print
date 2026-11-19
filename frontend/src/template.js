// The card's HTML.

import { ACCEPT, CAMERA_ACCEPT, PHOTO_ACCEPT } from "./constants.js";
import { t } from "./i18n.js";
import { svg } from "./icons.js";
import { STYLE } from "./styles.js";

export const TEMPLATE = `
  <style>${STYLE}</style>
  <ha-card>
    <div class="card">
      <div class="header">
        <div class="header-row">
          <span class="who" data-role="who">
            <span class="who-icon" data-role="who-icon">${svg("printer")}</span>
            <span class="title" data-role="title"></span>
          </span>
          <button type="button" class="who" data-role="switcher" aria-haspopup="listbox" aria-expanded="false" aria-controls="printer-list" hidden>
            <span class="chevron">${svg("unfold")}</span>
          </button>
          <span class="state" data-role="state"></span>
          <button type="button" class="icon-button" data-role="history-button" data-aria="history">
            ${svg("history")}
          </button>
        </div>
        <ul class="printer-list" id="printer-list" data-role="printer-list" role="listbox" hidden></ul>
      </div>
      <div class="update" data-role="update" role="status" hidden>
        <span class="update-text" data-role="update-text"></span>
        <button type="button" class="file-button" data-role="update-reload" data-t="update_reload"></button>
        <button type="button" class="file-button" data-role="update-restart" data-t="update_restart" hidden></button>
      </div>
      <div class="notice" data-role="notice" role="alert" hidden></div>
      <div class="tabs" role="tablist" data-role="body-tabs" hidden>
        <button type="button" role="tab" class="tab" id="body-tab-print" data-role="body-tab-print" data-body-tab="print" data-t="tab_print" aria-controls="print-panel" aria-selected="true"></button>
        <button type="button" role="tab" class="tab" id="body-tab-scan" data-role="body-tab-scan" data-body-tab="scan" data-t="tab_scan" aria-controls="scan-panel" aria-selected="false" tabindex="-1"></button>
      </div>
      <div class="print-panel" id="print-panel" data-role="print-panel">
      <div class="ink" data-role="ink"></div>
      <div class="file-row" data-role="file-row">
        <button type="button" class="file-button" data-role="pick">
          ${svg("paperclip")}<span data-t="choose_file"></span>
        </button>
        <label class="option" data-opt="copies">
          <span data-t="copies"></span>
          <input type="number" data-role="copies" min="1" value="1" inputmode="numeric" />
        </label>
        <span class="file-info" data-role="file-info" hidden>
          <span class="file-name" data-role="file-name"></span>
          <span class="file-size" data-role="file-size"></span>
        </span>
        <div class="pick-menu" data-role="pick-menu" role="menu" hidden>
          <button type="button" role="menuitem" data-option="file">
            ${svg("paperclip")}<span data-t="pick_file"></span>
          </button>
          <button type="button" role="menuitem" data-option="photo">
            ${svg("images")}<span data-t="pick_photo"></span>
          </button>
          <button type="button" role="menuitem" data-option="camera">
            ${svg("camera")}<span data-t="pick_camera"></span>
          </button>
        </div>
        <input type="file" class="hidden-input" data-role="input-file" accept="${ACCEPT}" tabindex="-1" aria-hidden="true" />
        <input type="file" class="hidden-input" data-role="input-photo" accept="${PHOTO_ACCEPT}" tabindex="-1" aria-hidden="true" />
        <input type="file" class="hidden-input" data-role="input-camera" accept="${CAMERA_ACCEPT}" capture="environment" tabindex="-1" aria-hidden="true" />
      </div>
      <div class="options" data-role="options">
        <label class="option" data-opt="duplex">
          <span data-t="duplex"></span>
          <input type="checkbox" data-role="duplex" />
        </label>
        <label class="option" data-opt="color">
          <span data-t="color"></span>
          <input type="checkbox" data-role="color" />
        </label>
      </div>
      <label class="pages" data-opt="pages">
        <span data-t="pages"></span>
        <input type="text" data-role="pages" autocomplete="off" />
      </label>
      <button type="button" class="print" data-role="print" data-t="print"></button>
      <div class="message" data-role="message" aria-live="polite"></div>
      <div class="detail" data-role="detail" hidden></div>
      </div>
      <div class="scan-panel" id="scan-panel" data-role="scan-panel" hidden>
        <div class="scan-fields">
          <label class="scan-field" data-scan="source">
            <span data-t="scan_source"></span><select data-role="scan-source"></select>
          </label>
          <label class="scan-field" data-scan="color">
            <span data-t="scan_color"></span><select data-role="scan-color"></select>
          </label>
          <label class="scan-field" data-scan="resolution">
            <span data-t="scan_resolution"></span><select data-role="scan-resolution"></select>
          </label>
          <label class="scan-field" data-scan="format">
            <span data-t="scan_format"></span><select data-role="scan-format"></select>
          </label>
        </div>
        <button type="button" class="print" data-role="scan-start" data-t="scan_start"></button>
        <button type="button" class="file-button" data-role="scan-cancel" hidden>
          <span data-t="scan_cancel"></span>
        </button>
        <div class="message" data-role="scan-message" aria-live="polite"></div>
        <div class="scan-result" data-role="scan-result" hidden>
          <div class="scan-page" data-role="scan-page"></div>
          <div class="scan-nav" data-role="scan-nav">
            <button type="button" class="icon-button" data-role="scan-prev" data-aria="scan_prev">
              ${svg("chevron_left")}
            </button>
            <span data-role="scan-page-label"></span>
            <button type="button" class="icon-button" data-role="scan-next" data-aria="scan_next">
              ${svg("chevron_right")}
            </button>
          </div>
          <label class="scan-name">
            <span data-t="scan_name"></span>
            <input type="text" data-role="scan-name" autocomplete="off" maxlength="80" />
          </label>
          <div class="scan-actions">
            <button type="button" class="file-button" data-role="scan-download">
              ${svg("download")}<span data-t="scan_download"></span>
            </button>
            <button type="button" class="file-button" data-role="scan-crop">
              ${svg("crop")}<span data-t="crop"></span>
            </button>
            <button type="button" class="file-button" data-role="scan-add">
              ${svg("file_plus")}<span data-t="scan_add_page"></span>
            </button>
            <button type="button" class="file-button danger" data-role="scan-delete">
              ${svg("delete")}<span data-t="delete"></span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </ha-card>
  <dialog data-role="history-dialog" aria-labelledby="history-title">
    <div class="sheet">
      <div class="sheet-head">
        <span class="sheet-title" id="history-title" data-t="history"></span>
        <button type="button" class="icon-button" data-role="history-close" data-aria="close">
          ${svg("close")}
        </button>
      </div>
      <div class="tabs" role="tablist" data-role="history-tabs" hidden>
        <button type="button" role="tab" class="tab" id="tab-prints" data-role="tab-prints" data-tab="prints" data-t="tab_prints" aria-controls="history-panel" aria-selected="true"></button>
        <button type="button" role="tab" class="tab" id="tab-scans" data-role="tab-scans" data-tab="scans" data-t="tab_scans" aria-controls="history-panel" aria-selected="false"></button>
      </div>
      <div class="history-panel" id="history-panel" data-role="history-panel">
        <div class="sheet-status" data-role="history-status" role="status"></div>
        <ul class="history-list" data-role="history-list"></ul>
      </div>
    </div>
  </dialog>
  <dialog data-role="preview-dialog" aria-labelledby="preview-title">
    <div class="sheet">
      <div class="sheet-head">
        <span class="sheet-title" id="preview-title" data-role="preview-title"></span>
        <button type="button" class="icon-button" data-role="preview-close" data-aria="close">
          ${svg("close")}
        </button>
      </div>
      <div class="preview-body" data-role="preview-body"></div>
    </div>
  </dialog>
  <dialog data-role="crop-dialog" aria-labelledby="crop-title">
    <div class="sheet">
      <div class="sheet-head">
        <span class="sheet-title" id="crop-title" data-role="crop-title"></span>
        <button type="button" class="icon-button" data-role="crop-close" data-aria="close">
          ${svg("close")}
        </button>
      </div>
      <div class="crop-body">
        <div class="crop-stage" data-role="crop-stage">
          <div class="crop-frame" data-role="crop-frame" tabindex="0" data-aria="crop_frame" hidden>
            <button type="button" class="crop-handle" data-corner="nw" data-aria="crop_corner_nw"></button>
            <button type="button" class="crop-handle" data-corner="ne" data-aria="crop_corner_ne"></button>
            <button type="button" class="crop-handle" data-corner="sw" data-aria="crop_corner_sw"></button>
            <button type="button" class="crop-handle" data-corner="se" data-aria="crop_corner_se"></button>
          </div>
        </div>
        <div class="sheet-status" data-role="crop-status" role="status"></div>
        <div class="crop-actions">
          <button type="button" class="file-button" data-role="crop-full" data-t="crop_full"></button>
          <button type="button" class="file-button" data-role="crop-cancel" data-t="crop_cancel"></button>
          <button type="button" class="print" data-role="crop-save" data-t="crop_save"></button>
        </div>
      </div>
    </div>
  </dialog>
`;
