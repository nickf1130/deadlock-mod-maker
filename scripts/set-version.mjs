/**
 * Sets the application version everywhere in one go.
 *
 *   npm run set-version 1.1.0
 *
 * Updates package.json and every file listed in version-sources.mjs, then
 * verifies the result. Nothing is written unless all files can be updated, so a
 * typo cannot leave the repository half-bumped.
 *
 * This does not commit or tag anything. If you want the npm behaviour of a
 * commit plus a git tag, use `npm version 1.1.0` instead - the "version"
 * lifecycle script in package.json runs this file for you.
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { versionSources } from "./version-sources.mjs";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageJsonPath = path.join(repositoryRoot, "package.json");

// Accepts 1.2.3 and 1.2.3-beta.1, which is what electron-builder and PyPI both
// understand. Anything looser tends to break one of them.
const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

function fail(message) {
  console.error(`set-version: ${message}`);
  process.exit(1);
}

const requested = process.argv[2];
if (!requested) {
  const current = JSON.parse(readFileSync(packageJsonPath, "utf8")).version;
  fail(`no version given. Current version is ${current}.\n  usage: npm run set-version 1.1.0`);
}
if (!SEMVER.test(requested)) {
  fail(`"${requested}" is not a valid version. Use MAJOR.MINOR.PATCH, for example 1.1.0.`);
}

const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"));
const previous = packageJson.version;

// Note: package.json matching the requested version does not mean there is
// nothing to do. A file further down the list can still have drifted - that is
// exactly the case verify-version.mjs tells you to run this command for. So
// every file is rewritten and "nothing to do" is decided at the end, from
// whether any file actually changed.

// Work out every edit first, then write. A file that does not contain the
// expected pattern is a mistake worth stopping for: silently skipping it would
// reintroduce exactly the drift this script exists to prevent.
const edits = [];
for (const source of versionSources(packageJson.name)) {
  const filePath = path.join(repositoryRoot, source.file);
  const text = readFileSync(filePath, "utf8");
  if (!source.pattern.test(text)) {
    fail(`could not find a version to replace in ${source.file}`);
  }
  const updated = source.replace(text, requested);
  if (source.pattern.exec(updated)?.[1] !== requested) {
    fail(`replacing the version in ${source.file} did not produce ${requested}`);
  }
  edits.push({ filePath, text: updated, file: source.file, changed: updated !== text });
}

// package.json is edited textually rather than via JSON.stringify so the rest
// of the file keeps its existing formatting.
const packageJsonText = readFileSync(packageJsonPath, "utf8");
const packageJsonUpdated = packageJsonText.replace(
  /^(\s*"version":\s*")[^"]+(")/m,
  `$1${requested}$2`
);
if (JSON.parse(packageJsonUpdated).version !== requested) {
  fail("could not update the version in package.json");
}
edits.unshift({
  filePath: packageJsonPath,
  text: packageJsonUpdated,
  file: "package.json",
  changed: packageJsonUpdated !== packageJsonText
});

const changed = edits.filter((edit) => edit.changed);
if (changed.length === 0) {
  console.log(`Every file already reports ${requested}. Nothing to do.`);
  process.exit(0);
}

for (const edit of changed) {
  writeFileSync(edit.filePath, edit.text);
}

console.log(
  previous === requested
    ? `Re-synced ${requested} across files that had drifted`
    : `Version ${previous} -> ${requested}`
);
for (const edit of changed) {
  console.log(`  updated ${edit.file}`);
}
console.log("\nRun `npm run build` to produce artifacts with the new version.");
