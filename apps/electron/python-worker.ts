import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { app } from "electron";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import path from "node:path";
import readline from "node:readline";
import log from "electron-log/main";

export type BackendMethod =
  | "app.bootstrap"
  | "diagnostics.run"
  | "requirements.install"
  | "settings.save"
  | "projects.create"
  | "projects.list"
  | "projects.get"
  | "projects.delete"
  | "projects.confirmReplacement"
  | "projects.silenceReplacement"
  | "projects.updateReplacement"
  | "projects.replaceSource"
  | "projects.duplicateSettings"
  | "projects.removeReplacement"
  | "projects.reorderReplacement"
  | "projects.remapTarget"
  | "projects.conflicts"
  | "projects.compatibility"
  | "sounds.index"
  | "sounds.indexHistory"
  | "sounds.search"
  | "sounds.preview"
  | "visuals.search"
  | "visuals.preview"
  | "visuals.inspectSource"
  | "projects.confirmVisualReplacement"
  | "projects.updateVisualReplacement"
  | "projects.removeVisualReplacement"
  | "audio.inspect"
  | "audio.previewProcessed"
  | "batch.previewCsv"
  | "batch.previewFolder"
  | "batch.confirm"
  | "batch.rollback"
  | "build.start"
  | "build.cancel"
  | "build.validateExport"
  | "export.createZip"
  | "export.createCompatibilityCopy"
  | "packages.inspect"
  | "packages.combine"
  | "packages.extract"
  | "mods.inspect"
  | "mods.addonConflicts"
  | "mods.compare";

export const BACKEND_ALLOWLIST = new Set<BackendMethod>([
  "app.bootstrap",
  "diagnostics.run",
  "requirements.install",
  "settings.save",
  "projects.create",
  "projects.list",
  "projects.get",
  "projects.delete",
  "projects.confirmReplacement",
  "projects.silenceReplacement",
  "projects.updateReplacement",
  "projects.replaceSource",
  "projects.duplicateSettings",
  "projects.removeReplacement",
  "projects.reorderReplacement",
  "projects.remapTarget",
  "projects.conflicts",
  "projects.compatibility",
  "sounds.index",
  "sounds.indexHistory",
  "sounds.search",
  "sounds.preview",
  "visuals.search",
  "visuals.preview",
  "visuals.inspectSource",
  "projects.confirmVisualReplacement",
  "projects.updateVisualReplacement",
  "projects.removeVisualReplacement",
  "audio.inspect",
  "audio.previewProcessed",
  "batch.previewCsv",
  "batch.previewFolder",
  "batch.confirm",
  "batch.rollback",
  "build.start",
  "build.cancel",
  "build.validateExport",
  "export.createZip",
  "export.createCompatibilityCopy",
  "packages.inspect",
  "packages.combine",
  "packages.extract",
  "mods.inspect",
  "mods.addonConflicts",
  "mods.compare"
]);

const LONG_RUNNING_METHODS = new Set<BackendMethod>([
  "build.start",
  "sounds.index",
  "app.bootstrap",
  "requirements.install",
  "packages.combine",
  "packages.extract"
]);

function requestTimeout(method: BackendMethod): number {
  if (LONG_RUNNING_METHODS.has(method)) {
    return 30 * 60_000;
  }
  return 60_000;
}

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timeout: NodeJS.Timeout;
};

type ProtocolMessage = {
  id?: string;
  ok?: boolean;
  result?: unknown;
  error?: { code?: string; message?: string; details?: unknown };
  event?: string;
  [key: string]: unknown;
};

export class PythonWorker {
  private child: ChildProcessWithoutNullStreams | null = null;
  private pending = new Map<string, PendingRequest>();
  private restartCount = 0;
  private stopping = false;

  constructor(
    private readonly appRoot: string,
    private readonly onEvent: (event: ProtocolMessage) => void,
    private readonly sourceRoot: string = appRoot
  ) {}

  start(): void {
    if (this.child) {
      return;
    }
    const command = this.resolveCommand();
    log.info("Starting Python worker", command.executable, command.args);
    const child = spawn(command.executable, command.args, {
      cwd: command.cwd,
      env: {
        ...process.env,
        DSS_APP_ROOT: this.appRoot,
        PYTHONUNBUFFERED: "1",
        PYTHONUTF8: "1"
      },
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"]
    });
    this.child = child;

    const lines = readline.createInterface({ input: child.stdout });
    lines.on("line", (line) => this.handleLine(line));
    child.stderr.on("data", (chunk: Buffer) => {
      const value = chunk.toString("utf8").trimEnd();
      if (value) {
        log.info(`[python] ${value}`);
      }
    });
    child.once("error", (error) => this.handleExit(error));
    child.once("exit", (code, signal) => {
      this.handleExit(new Error(`Python worker exited (${code ?? "null"}, ${signal ?? "no signal"})`));
    });
  }

  async call(method: BackendMethod, params: Record<string, unknown> = {}): Promise<unknown> {
    if (!BACKEND_ALLOWLIST.has(method)) {
      throw new Error(`Backend method is not permitted: ${method}`);
    }
    if (!this.child) {
      this.start();
    }
    const child = this.child;
    if (!child || child.killed || !child.stdin.writable) {
      throw new Error("Python worker is not available");
    }
    const id = randomUUID();
    const timeoutMs = requestTimeout(method);
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Backend request timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timeout });
      child.stdin.write(`${JSON.stringify({ id, method, params })}\n`, "utf8", (error) => {
        if (error) {
          clearTimeout(timeout);
          this.pending.delete(id);
          reject(error);
        }
      });
    });
  }

  stop(): void {
    this.stopping = true;
    if (this.child && !this.child.killed) {
      this.child.kill();
    }
    this.child = null;
    this.rejectPending(new Error("Application is shutting down"));
  }

  private resolveCommand(): { executable: string; args: string[]; cwd: string } {
    if (!app.isPackaged) {
      const pythonRoot = path.join(this.sourceRoot, "python");
      let executable = process.env.DSS_PYTHON;
      if (!executable) {
        executable = "python3";
        if (process.platform === "win32") {
          executable = "python";
        }
      }
      return {
        executable,
        args: ["-m", "deadlock_sound_studio"],
        cwd: pythonRoot
      };
    }
    const workerRoot = path.join(process.resourcesPath, "backend", "deadlock-sound-worker");
    const executable = path.join(workerRoot, "deadlock-sound-worker.exe");
    if (!existsSync(executable)) {
      throw new Error(`Packaged Python worker is missing: ${executable}`);
    }
    return { executable, args: [], cwd: workerRoot };
  }

  private handleLine(line: string): void {
    let message: ProtocolMessage;
    try {
      message = JSON.parse(line) as ProtocolMessage;
    } catch {
      log.error("Python worker wrote non-protocol stdout", line);
      return;
    }
    if (message.event) {
      this.onEvent(message);
      return;
    }
    if (!message.id) {
      return;
    }
    const pending = this.pending.get(message.id);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timeout);
    this.pending.delete(message.id);
    if (message.ok) {
      pending.resolve(message.result);
    } else {
      const error = new Error(message.error?.message ?? "Backend request failed");
      Object.assign(error, { code: message.error?.code, details: message.error?.details });
      pending.reject(error);
    }
  }

  private handleExit(error: Error): void {
    if (!this.child) {
      return;
    }
    this.child = null;
    this.rejectPending(error);
    log.error(error.message);
    if (!this.stopping && this.restartCount < 1) {
      this.restartCount += 1;
      setTimeout(() => this.start(), 500);
    }
  }

  private rejectPending(error: Error): void {
    for (const request of this.pending.values()) {
      clearTimeout(request.timeout);
      request.reject(error);
    }
    this.pending.clear();
  }
}
