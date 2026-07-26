import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = path.join(repositoryRoot, "dist-electron");

if (path.dirname(outputDirectory) !== repositoryRoot) {
  throw new Error("Refusing to clean an Electron output folder outside the repository.");
}
if (existsSync(outputDirectory)) {
  rmSync(outputDirectory, { recursive: true, force: true });
}
