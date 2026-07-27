/**
 * Fails the build if any file has drifted from the version in package.json.
 *
 * The list of files lives in version-sources.mjs and is shared with
 * scripts/set-version.mjs, so a file can never be checked but not updated.
 * To bump the version, run `npm run set-version 1.1.0`.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { versionSources } from "./version-sources.mjs";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = JSON.parse(
  readFileSync(path.join(repositoryRoot, "package.json"), "utf8")
);

for (const source of versionSources(packageJson.name)) {
  const text = readFileSync(path.join(repositoryRoot, source.file), "utf8");
  const value = source.pattern.exec(text)?.[1];
  if (value !== packageJson.version) {
    throw new Error(
      `Version verification failed: ${source.file} has ${value ?? "no version"}, ` +
        `expected ${packageJson.version}. Run \`npm run set-version ${packageJson.version}\` to fix.`
    );
  }
}

console.log(`Application version ${packageJson.version} is consistent.`);
