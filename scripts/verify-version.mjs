import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packageVersion = JSON.parse(
  readFileSync(path.join(repositoryRoot, "package.json"), "utf8")
).version;
const sources = [
  {
    file: "python/pyproject.toml",
    pattern: /^version = "([^"]+)"$/m
  },
  {
    file: "python/deadlock_sound_studio/__init__.py",
    pattern: /^__version__ = "([^"]+)"$/m
  },
  {
    file: "python/deadlock_sound_studio/requirements.py",
    pattern: /^USER_AGENT = "Deadlock-Mod-Maker\/([^"]+)"$/m
  }
];

for (const source of sources) {
  const text = readFileSync(path.join(repositoryRoot, source.file), "utf8");
  const value = source.pattern.exec(text)?.[1];
  if (value !== packageVersion) {
    throw new Error(
      `Version verification failed: ${source.file} has ${value ?? "no version"}, expected ${packageVersion}`
    );
  }
}

console.log(`Application version ${packageVersion} is consistent.`);
