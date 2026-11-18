# Troubleshooting

## The card doesn't show up

**Symptoms:** a Home Print card on a dashboard shows *Custom element doesn't exist: home-print-card*, or **Home Print** is missing from the **Add card** list. The printer and its sensors may still work.

The browser couldn't load the card's file. Work through these steps in order and stop as soon as the card is back.

1. **Restart Home Assistant fully.** After installing or updating through HACS, the card is only registered on the next start. Use **Settings → System → ⋮ (top right) → Restart Home Assistant**; reloading the integration is not enough.

2. **Reload the page without the cache.** Browsers keep the old card file:
   - Desktop browser: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> (Windows/Linux) or <kbd>Cmd</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> (macOS).
   - Companion app: close the app completely and open it again. If that doesn't help and your app has it, use **Settings → Companion app → Debugging → Reset frontend cache**.

3. **Check that Home Assistant serves the card.** Open this address in a browser (use your own Home Assistant address):

   ```
   http://<your-home-assistant>:8123/home_print_static/home-print-card.js
   ```

   - **You see JavaScript code:** the file is fine; go back to step 2 (it's the cache).
   - **You see `404: Not Found`:** the card file is missing from the installation. Continue with step 4.

4. **Download Home Print again.** In **HACS**, open **Home Print → ⋮ (top right) → Redownload**, pick the latest version and confirm. Then restart Home Assistant (step 1) and reload the page (step 2). The address from step 3 should now show code.

5. **Add the card again.** If you had removed it: **Edit dashboard → Add card → Home Print**. If you kept it, it shows up again by itself.

**Still not working?** Look in **Settings → System → Logs** for lines mentioning `home_print` and [open an issue](https://github.com/ada-kilinc/home-print/issues/new) with them, your Home Print version (HACS) and your Home Assistant version.

### Why it happens

Updates since 0.3.5 are installed from a single release archive, so a half-finished download can't leave the card file behind any more. The most common causes left are a missing restart after an update and a browser holding on to the old file.
