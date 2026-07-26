import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pythonRoot = path.join(repositoryRoot, "python");
const environmentRoot = path.join(pythonRoot, ".venv-release");
const environmentPython = path.join(environmentRoot, "Scripts", "python.exe");
const requirementsLock = path.join(pythonRoot, "requirements.lock.txt");
const task = process.argv[2] ?? "sync";

function run(executable, argumentsList, workingDirectory = repositoryRoot) {
  const result = spawnSync(executable, argumentsList, {
    cwd: workingDirectory,
    env: process.env,
    stdio: "inherit",
    windowsHide: true
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function findBootstrapPython() {
  if (process.env.DSS_BUILD_PYTHON) return process.env.DSS_BUILD_PYTHON;
  return "python";
}

if (!["sync", "test", "build", "audit"].includes(task)) {
  throw new Error(`Unknown Python task: ${task}`);
}

// A release build always starts clean. This prevents unrelated packages from
// the developer's machine from being swept into the PyInstaller bundle.
if (task === "build" && existsSync(environmentRoot)) {
  if (path.dirname(environmentRoot) !== pythonRoot) {
    throw new Error("Refusing to clean a Python environment outside the Python workspace.");
  }
  rmSync(environmentRoot, { recursive: true, force: true });
}

if (!existsSync(environmentPython)) {
  run(findBootstrapPython(), ["-m", "venv", environmentRoot]);
}

run(environmentPython, [
  "-m",
  "pip",
  "install",
  "--disable-pip-version-check",
  "--require-hashes",
  "--requirement",
  requirementsLock
]);
run(environmentPython, ["-m", "pip", "check"]);

if (task === "test") {
  run(environmentPython, ["-m", "pytest", "tests"], pythonRoot);
}

if (task === "build") {
  run(environmentPython, [
    "-m",
    "PyInstaller",
    path.join(pythonRoot, "deadlock-sound-worker.spec"),
    "--noconfirm",
    "--clean",
    "--distpath",
    path.join(pythonRoot, "dist"),
    "--workpath",
    path.join(pythonRoot, "build")
  ]);
}

if (task === "audit") {
  run(environmentPython, [
    "-m",
    "pip",
    "install",
    "--disable-pip-version-check",
    "pip-audit==2.10.1"
  ]);
  run(environmentPython, [
    "-m",
    "pip_audit",
    "--requirement",
    requirementsLock
  ]);
}
