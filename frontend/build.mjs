// Bundles frontend/src/ into the single file Home Assistant loads:
// custom_components/home_print/frontend/home-print-card.js
//
//   npm run build          write the bundle
//   npm run build:check    fail if the committed bundle is out of date (CI)

import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const entry = resolve(root, "frontend/src/index.js");
const outfile = resolve(root, "custom_components/home_print/frontend/home-print-card.js");

const banner = `/* Home Print dashboard card.
 *
 * Built from frontend/src/ with \`npm run build\`: edit those files, not this one.
 *
 * It lists printers through the \`home_print/printers\` WebSocket command,
 * uploads files to \`/api/home_print/upload/<entry_id>\` with
 * \`hass.fetchWithAuth\` and follows the job with \`home_print/job\`. A clock
 * button opens the print history (\`home_print/history\`,
 * \`home_print/history/delete\`) and a page preview served by
 * \`/api/home_print/history/<entry_id>/<id>/page/<n>\`.
 *
 * A printer with a scanner splits the card body into Print and Scan tabs; the
 * Scan tab starts \`home_print/scan/start\`, polls \`home_print/scan/state\`
 * (stopped with \`home_print/scan/cancel\`) and shows the result. The history
 * dialog then has a second tab listing \`home_print/scans\`.
 */`;

const result = await build({
  entryPoints: [entry],
  bundle: true,
  format: "esm",
  target: "es2022",
  charset: "utf8",
  legalComments: "none",
  banner: { js: banner },
  write: false,
  logLevel: "warning",
});
const output = result.outputFiles[0].text;

if (process.argv.includes("--check")) {
  const current = await readFile(outfile, "utf8").catch(() => "");
  if (current !== output) {
    console.error(
      "home-print-card.js is out of date with frontend/src/. Run `npm run build` and commit it.",
    );
    process.exit(1);
  }
  console.log("home-print-card.js is up to date.");
} else {
  await writeFile(outfile, output);
  console.log(`wrote ${outfile}`);
}
