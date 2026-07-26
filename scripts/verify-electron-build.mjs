import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function requireBuild(condition, message) {
  if (!condition) {
    throw new Error(`Electron build verification failed: ${message}`);
  }
}

const root = resolve(import.meta.dirname, "..");
const preloadPath = resolve(root, "dist-electron", "preload.cjs");
const mainPath = resolve(root, "dist-electron", "main.js");
const indexPath = resolve(root, "dist", "index.html");

requireBuild(existsSync(preloadPath), "dist-electron/preload.cjs is missing");
requireBuild(existsSync(mainPath), "dist-electron/main.js is missing");
requireBuild(existsSync(indexPath), "dist/index.html is missing");

const preload = readFileSync(preloadPath, "utf8");
const main = readFileSync(mainPath, "utf8");
const index = readFileSync(indexPath, "utf8");

requireBuild(
  preload.includes('require("electron")'),
  "sandboxed preload is not CommonJS"
);
requireBuild(
  !/^\s*import\s/m.test(preload),
  "sandboxed preload still contains an ESM import"
);
requireBuild(
  main.includes('"preload.cjs"'),
  "BrowserWindow does not reference the CommonJS preload"
);

const assetPaths = [...index.matchAll(/(?:src|href)="\.\/([^"]+)"/g)].map(
  (match) => match[1]
);
requireBuild(assetPaths.length >= 2, "renderer assets are not linked from index.html");
for (const relativePath of assetPaths) {
  requireBuild(
    existsSync(resolve(root, "dist", relativePath)),
    `renderer asset is missing: ${relativePath}`
  );
}

console.log("Electron startup artifacts verified.");
