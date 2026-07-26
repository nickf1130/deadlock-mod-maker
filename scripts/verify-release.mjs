import {
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync
} from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { listPackage } from "@electron/asar";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const releaseRoot = path.join(repositoryRoot, "release");
const packageMetadata = JSON.parse(
  readFileSync(path.join(repositoryRoot, "package.json"), "utf8")
);
const artifactName = `DeadlockModMaker-${packageMetadata.version}-portable.exe`;
const artifactPath = path.join(releaseRoot, artifactName);
const resourceRoot = path.join(releaseRoot, "win-unpacked", "resources");
const asarPath = path.join(resourceRoot, "app.asar");

function requireRelease(condition, message) {
  if (!condition) throw new Error(`Release verification failed: ${message}`);
}

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(target) : [target];
  });
}

requireRelease(existsSync(artifactPath), `${artifactName} is missing`);
requireRelease(statSync(artifactPath).size > 50 * 1024 * 1024, "portable executable is unexpectedly small");
requireRelease(
  existsSync(
    path.join(
      resourceRoot,
      "backend",
      "deadlock-sound-worker",
      "deadlock-sound-worker.exe"
    )
  ),
  "packaged Python worker is missing"
);
requireRelease(existsSync(asarPath), "app.asar is missing");
for (const relativePath of [
  "LICENSE.md",
  "THIRD_PARTY_NOTICES.md",
  path.join("licenses", "OFL-1.1.txt"),
  path.join("licenses", "JavaScript-licenses.txt"),
  path.join("licenses", "Python-licenses.txt")
]) {
  requireRelease(
    existsSync(path.join(resourceRoot, relativePath)),
    `packaged notice is missing: ${relativePath}`
  );
}

const developmentFile = /\.(?:map|test\.js)$/i;
const packagedDevelopmentFiles = [
  ...walk(resourceRoot).filter(
    (filename) => filename !== asarPath && developmentFile.test(filename)
  ),
  ...listPackage(asarPath).filter((filename) => developmentFile.test(filename))
];
requireRelease(
  packagedDevelopmentFiles.length === 0,
  `development files were packaged: ${packagedDevelopmentFiles.join(", ")}`
);

const sha256 = createHash("sha256")
  .update(readFileSync(artifactPath))
  .digest("hex");
const checksumPath = `${artifactPath}.sha256`;
writeFileSync(checksumPath, `${sha256}  ${artifactName}\n`, "utf8");

console.log(`Release verified: ${artifactName}`);
console.log(`SHA-256: ${sha256}`);
console.log(`Checksum file: ${path.basename(checksumPath)}`);
