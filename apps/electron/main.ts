import { app, BrowserWindow, dialog, ipcMain, Menu, net, protocol, shell } from "electron";
import type { BrowserWindowConstructorOptions } from "electron";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, realpathSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import log from "electron-log/main";
import { BACKEND_ALLOWLIST, BackendMethod, PythonWorker } from "./python-worker.js";
import {
  checkForUpdates,
  downloadAndApplyUpdate,
  ISSUES_URL,
  PROFILE_URL,
  RELEASES_URL,
  REPOSITORY_URL,
  type UpdateInfo
} from "./updater.js";

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(moduleDirectory, "..");
const isDevelopment = Boolean(process.env.VITE_DEV_SERVER_URL);

function resolveAppRoot(): string {
  if (!app.isPackaged && process.env.DSS_TEST_APP_ROOT) {
    return path.resolve(process.env.DSS_TEST_APP_ROOT);
  }
  if (isDevelopment) {
    return projectRoot;
  }
  if (process.env.PORTABLE_EXECUTABLE_DIR) {
    return path.resolve(process.env.PORTABLE_EXECUTABLE_DIR);
  }
  return path.resolve(path.dirname(process.execPath));
}

const appRoot = resolveAppRoot();
const electronProfileRoot = path.join(appRoot, "data", "electron-profile");
mkdirSync(electronProfileRoot, { recursive: true });
app.setPath("userData", electronProfileRoot);
log.transports.file.level = "error";
log.transports.file.resolvePathFn = () => path.join(appRoot, "logs", "main.log");

const mediaTokens = new Map<string, string>();
const approvedSelections = new Set<string>();
const approvedOutputs = new Set<string>();
let mainWindow: BrowserWindow | null = null;
let worker: PythonWorker | null = null;
let latestUpdate: UpdateInfo | null = null;
const hasSingleInstanceLock = app.requestSingleInstanceLock();
const uiSmoke = process.env.DSS_UI_SMOKE === "1";
const downloadPages = {
  ffmpeg: "https://www.ffmpeg.org/download.html",
  source2Viewer: "https://github.com/ValveResourceFormat/ValveResourceFormat/releases"
} as const;
const externalPages = {
  repository: REPOSITORY_URL,
  profile: PROFILE_URL,
  releases: RELEASES_URL,
  issues: ISSUES_URL
} as const;

protocol.registerSchemesAsPrivileged([
  {
    scheme: "studio-media",
    privileges: {
      secure: true,
      standard: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true
    }
  }
]);

function createWindow(): void {
  // Packaged builds take their icon from the executable itself, which
  // electron-builder stamps from build/icon.png. Development runs have no such
  // executable, so point the window at the source image directly.
  const developmentIcon = path.join(projectRoot, "build", "icon.png");
  const windowOptions: BrowserWindowConstructorOptions = {
    title: "Deadlock Mod Maker",
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: "#0a0a0a",
    show: false,
    webPreferences: {
      preload: path.join(moduleDirectory, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false
    }
  };
  if (!app.isPackaged && existsSync(developmentIcon)) {
    windowOptions.icon = developmentIcon;
  }
  mainWindow = new BrowserWindow(windowOptions);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.once("ready-to-show", () => {
    if (!uiSmoke) {
      mainWindow?.show();
    }
  });
  mainWindow.webContents.on(
    "did-fail-load",
    (_event, errorCode, errorDescription, validatedURL, isMainFrame) => {
      if (isMainFrame) {
        log.error("Renderer failed to load", {
          errorCode,
          errorDescription,
          validatedURL
        });
      }
    }
  );
  mainWindow.webContents.on("console-message", (details) => {
    let write = log.info;
    if (details.level === "error") {
      write = log.error;
    } else if (details.level === "warning") {
      write = log.warn;
    }
    write.call(log, `[renderer] ${details.message}`, {
      line: details.lineNumber,
      sourceId: details.sourceId
    });
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    log.error("Renderer process exited", details);
  });
  mainWindow.webContents.on("did-finish-load", () => {
    void mainWindow?.webContents
      .executeJavaScript(
        `({
          href: location.href,
          title: document.title,
          hasRoot: Boolean(document.getElementById("root")),
          rootChildren: document.getElementById("root")?.childElementCount ?? -1,
          studioApi: typeof window.studio
        })`,
        true
      )
      .then((snapshot) => log.info("Renderer startup snapshot", snapshot))
      .catch((error) => log.error("Could not inspect renderer startup", error));
    if (uiSmoke && mainWindow) {
      void captureUiSmoke(mainWindow);
    }
  });
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const allowedDev = isDevelopment && url.startsWith(process.env.VITE_DEV_SERVER_URL ?? "");
    const allowedFile = !isDevelopment && url.startsWith("file:");
    if (!allowedDev && !allowedFile) {
      event.preventDefault();
    }
  });
  if (isDevelopment) {
    void mainWindow
      .loadURL(process.env.VITE_DEV_SERVER_URL!)
      .catch((error) => log.error("Failed to load development renderer", error));
  } else {
    void mainWindow
      .loadFile(path.join(projectRoot, "dist", "index.html"))
      .catch((error) => log.error("Failed to load packaged renderer", error));
  }
}

async function captureUiSmoke(window: BrowserWindow): Promise<void> {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline && !window.isDestroyed()) {
    const ready = await window.webContents.executeJavaScript(
      `Boolean(document.querySelector(".app-shell"))`,
      true
    );
    if (ready) {
      await new Promise((resolve) => setTimeout(resolve, 1_000));
      const image = await window.webContents.capturePage();
      const outputDirectory = path.join(appRoot, "cache");
      mkdirSync(outputDirectory, { recursive: true });
      const output = path.join(outputDirectory, "ui-smoke.png");
      writeFileSync(output, image.toPNG());
      log.info("UI smoke capture complete", { output });
      const openedSounds = await window.webContents.executeJavaScript(
          `(() => {
            const button = [...document.querySelectorAll(".sidebar nav button")]
              .find((candidate) => candidate.textContent?.trim() === "Sounds");
            if (!(button instanceof HTMLElement)) {
              return false;
            }
            button.click();
            return true;
          })()`,
        true
      );
      if (openedSounds) {
        const soundsDeadline = Date.now() + 8_000;
        while (Date.now() < soundsDeadline) {
          const settled = await window.webContents.executeJavaScript(
            `Boolean(document.querySelector(".search-row")) &&
             !document.querySelector(".sound-list > .activity-bar.is-active")`,
            true
          );
          if (settled) {
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 200));
        }
        await new Promise((resolve) => setTimeout(resolve, 300));
        const activeNavigation = await window.webContents.executeJavaScript(
          `document.querySelector(".sidebar nav button.active")?.textContent?.trim() ?? null`,
          true
        );
        log.info("Sounds smoke navigation state", { activeNavigation });
        const soundsImage = await window.webContents.capturePage();
        const soundsOutput = path.join(outputDirectory, "ui-smoke-sounds.png");
        writeFileSync(soundsOutput, soundsImage.toPNG());
        log.info("Sounds UI smoke capture complete", { output: soundsOutput });
        await window.webContents.executeJavaScript(
          `(() => {
            const button = [...document.querySelectorAll(".sidebar nav button")]
              .find((candidate) => candidate.textContent?.trim() === "Overview");
            if (button instanceof HTMLElement) {
              button.click();
            }
          })()`,
          true
        );
        await new Promise((resolve) => setTimeout(resolve, 300));
        const overviewImage = await window.webContents.capturePage();
        const overviewOutput = path.join(outputDirectory, "ui-smoke-overview.png");
        writeFileSync(overviewOutput, overviewImage.toPNG());
        log.info("Overview UI smoke capture complete", { output: overviewOutput });
      }
      app.quit();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  log.error("UI smoke capture timed out before the application shell rendered");
  worker?.stop();
  app.exit(1);
}

function canonicalExisting(targetPath: string): string {
  if (typeof targetPath !== "string" || !path.isAbsolute(targetPath) || !existsSync(targetPath)) {
    throw new Error("Path must identify an existing absolute file or directory");
  }
  return realpathSync.native(targetPath);
}

function isWithin(child: string, parent: string): boolean {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function isApprovedPath(targetPath: string): boolean {
  if (approvedSelections.has(targetPath)) {
    return true;
  }
  const approvedRoots = ["tools", "cache", "projects", "exports", "logs"].map((folder) =>
    path.resolve(appRoot, folder)
  );
  return approvedRoots.some((root) => existsSync(root) && isWithin(targetPath, realpathSync.native(root)));
}

function approveSelection(targetPath: string): string {
  const canonical = canonicalExisting(targetPath);
  approvedSelections.add(canonical);
  return canonical;
}

function canonicalOutput(targetPath: string): string {
  if (typeof targetPath !== "string" || !path.isAbsolute(targetPath)) {
    throw new Error("Output path must be absolute");
  }
  if (![".vpk", ".pak"].includes(path.extname(targetPath).toLowerCase())) {
    throw new Error("Output file must end in .vpk or .pak");
  }
  const parent = canonicalExisting(path.dirname(targetPath));
  if (!statSync(parent).isDirectory()) {
    throw new Error("Output folder does not exist");
  }
  return path.join(parent, path.basename(targetPath));
}

function registerIpc(): void {
  ipcMain.handle("app:info", () => ({
    name: app.getName(),
    version: app.getVersion(),
    platform: process.platform,
    architecture: process.arch,
    electronVersion: process.versions.electron,
    chromiumVersion: process.versions.chrome,
    portable: Boolean(process.env.PORTABLE_EXECUTABLE_FILE),
    dataRoot: appRoot,
    repositoryUrl: REPOSITORY_URL
  }));

  ipcMain.handle("updates:check", async () => {
    if (process.env.DSS_FAKE_UPDATE_CHECK === "1") {
      return {
        currentVersion: app.getVersion(),
        latestVersion: "9.9.9",
        available: true,
        releaseName: "Deadlock Mod Maker 9.9.9 Test Release",
        releaseNotes: "A deterministic update prompt used by the desktop integration test.",
        publishedAt: "2099-01-01T00:00:00Z",
        releaseUrl: RELEASES_URL,
        assetName: null,
        assetUrl: null,
        assetSize: null,
        assetDigest: null,
        canInstall: false,
        status: "available"
      } satisfies UpdateInfo;
    }
    if (process.env.DSS_SKIP_UPDATE_CHECK === "1") {
      return {
        currentVersion: app.getVersion(),
        latestVersion: app.getVersion(),
        available: false,
        releaseName: null,
        releaseNotes: "",
        publishedAt: null,
        releaseUrl: RELEASES_URL,
        assetName: null,
        assetUrl: null,
        assetSize: null,
        assetDigest: null,
        canInstall: false,
        status: "current"
      } satisfies UpdateInfo;
    }
    latestUpdate = await checkForUpdates();
    return latestUpdate;
  });

  ipcMain.handle("updates:install", async () => {
    const update = latestUpdate ?? (await checkForUpdates());
    latestUpdate = update;
    return downloadAndApplyUpdate(update, appRoot, (event) =>
      mainWindow?.webContents.send("backend:event", event)
    );
  });

  ipcMain.handle(
    "external:open",
    async (_event, kind: keyof typeof externalPages) => {
      const url = externalPages[kind];
      if (!url) {
        throw new Error("Unsupported external destination");
      }
      await shell.openExternal(url);
    }
  );

  ipcMain.handle("licenses:open", async () => {
    let noticePath = path.join(projectRoot, "THIRD_PARTY_NOTICES.md");
    if (app.isPackaged) {
      noticePath = path.join(process.resourcesPath, "THIRD_PARTY_NOTICES.md");
    }
    if (!existsSync(noticePath)) {
      throw new Error("Third-party notices are missing");
    }
    const error = await shell.openPath(noticePath);
    if (error) {
      throw new Error(error);
    }
  });

  ipcMain.handle("drop:approve", (_event, targetPath: string) => {
    const canonical = canonicalExisting(targetPath);
    if (!statSync(canonical).isFile() || ![".wav", ".mp3"].includes(path.extname(canonical).toLowerCase())) {
      throw new Error("Dropped files must be MP3 or WAV audio");
    }
    return approveSelection(canonical);
  });

  ipcMain.handle(
    "backend:call",
    async (_event, method: BackendMethod, params: Record<string, unknown>) => {
      if (!BACKEND_ALLOWLIST.has(method)) {
        throw new Error("Backend method is not permitted");
      }
      const pathKeysByMethod: Partial<Record<BackendMethod, string[]>> = {
        "audio.inspect": ["path"],
        "audio.previewProcessed": ["path"],
        "projects.confirmReplacement": ["sourcePath"],
        "projects.replaceSource": ["sourcePath"],
        "visuals.inspectSource": ["path"],
        "projects.confirmVisualReplacement": ["sourcePath"],
        "batch.previewCsv": ["path"],
        "batch.previewFolder": ["path"],
        "batch.confirm": ["path"]
      };
      for (const key of pathKeysByMethod[method] ?? []) {
        const value = params?.[key];
        if (typeof value !== "string") {
          throw new Error(`Missing approved path: ${key}`);
        }
        const canonical = canonicalExisting(value);
        if (!approvedSelections.has(canonical)) {
          throw new Error(`Path was not selected by the user: ${key}`);
        }
        params[key] = canonical;
      }
      if (method === "packages.inspect" || method === "packages.combine") {
        const values = params?.paths;
        if (!Array.isArray(values) || values.length === 0) {
          throw new Error("Choose at least one package file");
        }
        params.paths = values.map((value) => {
          if (typeof value !== "string") {
            throw new Error("Package path must be a string");
          }
          const canonical = canonicalExisting(value);
          if (!approvedSelections.has(canonical)) {
            throw new Error("Package path was not selected by the user");
          }
          if (!statSync(canonical).isFile() || ![".vpk", ".pak"].includes(path.extname(canonical).toLowerCase())) {
            throw new Error("Package inputs must be .vpk or .pak files");
          }
          return canonical;
        });
      }
      if (method === "packages.combine") {
        const outputValue = params?.outputPath;
        if (typeof outputValue !== "string") {
          throw new Error("Missing approved output path");
        }
        const output = canonicalOutput(outputValue);
        if (!approvedOutputs.has(output)) {
          throw new Error("Output path was not selected by the user");
        }
        params.outputPath = output;
      }
      if (method === "settings.save") {
        for (const [key, value] of Object.entries(params ?? {})) {
          if (key.endsWith("Override") && value !== null && value !== "") {
            if (typeof value !== "string" || !isApprovedPath(canonicalExisting(value))) {
              throw new Error(`Tool path was not selected by the user: ${key}`);
            }
          }
        }
      }
      const result = await worker?.call(method, params ?? {});
      if (method === "app.bootstrap" && result && typeof result === "object") {
        const settings = (result as { settings?: Record<string, unknown> }).settings;
        for (const value of Object.values(settings ?? {})) {
          if (typeof value === "string" && path.isAbsolute(value) && existsSync(value)) {
            approvedSelections.add(realpathSync.native(value));
          }
        }
      }
      if (method === "requirements.install" && result && typeof result === "object") {
        const settings = (result as { settings?: Record<string, unknown> }).settings;
        for (const value of Object.values(settings ?? {})) {
          if (typeof value === "string" && path.isAbsolute(value) && existsSync(value)) {
            approvedSelections.add(realpathSync.native(value));
          }
        }
      }
      if (method === "packages.combine" && result && typeof result === "object") {
        const outputPath = (result as { outputPath?: unknown }).outputPath;
        if (typeof outputPath === "string" && existsSync(outputPath)) {
          approvedSelections.add(realpathSync.native(outputPath));
        }
      }
      return result;
    }
  );

  ipcMain.handle("dialog:audio", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose replacement audio",
      properties: ["openFile"],
      filters: [{ name: "Audio", extensions: ["wav", "mp3"] }]
    });
    if (result.canceled) {
      return null;
    }
    return approveSelection(result.filePaths[0]);
  });

  ipcMain.handle("dialog:visual", async (_event, kind: string) => {
    if (kind !== "texture" && kind !== "material") {
      throw new Error("Unsupported visual resource type");
    }
    let title = "Choose replacement material";
    let filter = { name: "Source 2 material", extensions: ["vmat"] };
    if (kind === "texture") {
      title = "Choose replacement texture";
      filter = { name: "Texture source", extensions: ["png", "tga", "psd"] };
    }
    const result = await dialog.showOpenDialog({
      title,
      properties: ["openFile"],
      filters: [filter]
    });
    if (result.canceled) {
      return null;
    }
    return approveSelection(result.filePaths[0]);
  });

  ipcMain.handle("dialog:folder", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose folder",
      properties: ["openDirectory"]
    });
    if (result.canceled) {
      return null;
    }
    return approveSelection(result.filePaths[0]);
  });

  ipcMain.handle("dialog:csv", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose mapping file",
      properties: ["openFile"],
      filters: [{ name: "Mappings", extensions: ["csv", "xlsx"] }]
    });
    if (result.canceled) {
      return null;
    }
    return approveSelection(result.filePaths[0]);
  });

  ipcMain.handle("dialog:packages", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose Valve package files",
      properties: ["openFile", "multiSelections"],
      filters: [{ name: "Valve packages", extensions: ["vpk", "pak"] }]
    });
    if (result.canceled) {
      return [];
    }
    return result.filePaths.map(approveSelection);
  });

  ipcMain.handle("dialog:packageOutput", async () => {
    const result = await dialog.showSaveDialog({
      title: "Save combined package",
      defaultPath: "combined_mod.vpk",
      filters: [{ name: "Valve package", extensions: ["vpk", "pak"] }],
      properties: ["showOverwriteConfirmation", "createDirectory"]
    });
    if (result.canceled || !result.filePath) {
      return null;
    }
    const output = canonicalOutput(result.filePath);
    approvedOutputs.add(output);
    return output;
  });

  ipcMain.handle("dialog:executable", async (_event, kind: string) => {
    const labels: Record<string, string> = {
      source2Viewer: "Choose Source2Viewer.exe",
      source2ViewerCli: "Choose Source2Viewer-CLI.exe"
    };
    if (kind !== "source2Viewer" && kind !== "source2ViewerCli") {
      throw new Error("Unsupported executable selection");
    }
    const result = await dialog.showOpenDialog({
      title: labels[kind] ?? "Choose tool",
      properties: ["openFile"],
      filters: [{ name: "Executable", extensions: ["exe"] }]
    });
    if (result.canceled) {
      return null;
    }
    const selected = canonicalExisting(result.filePaths[0]);
    if (
      kind === "source2ViewerCli" &&
      path.basename(selected).toLowerCase() !== "source2viewer-cli.exe"
    ) {
      throw new Error("Choose Source2Viewer-CLI.exe");
    }
    return approveSelection(selected);
  });

  ipcMain.handle("dialog:ffmpeg", async () => {
    const result = await dialog.showOpenDialog({
      title: "Choose ffmpeg.exe or ffprobe.exe",
      properties: ["openFile"],
      filters: [{ name: "FFmpeg executable", extensions: ["exe"] }]
    });
    if (result.canceled) {
      return null;
    }

    const selected = canonicalExisting(result.filePaths[0]);
    if (!statSync(selected).isFile()) {
      throw new Error("Choose an FFmpeg executable file");
    }
    const selectedName = path.basename(selected).toLowerCase();
    if (selectedName !== "ffmpeg.exe" && selectedName !== "ffprobe.exe") {
      throw new Error("Choose ffmpeg.exe or ffprobe.exe from the extracted FFmpeg bin folder");
    }

    const binaryDirectory = path.dirname(selected);
    const ffmpeg = path.join(binaryDirectory, "ffmpeg.exe");
    const ffprobe = path.join(binaryDirectory, "ffprobe.exe");
    if (!existsSync(ffmpeg) || !existsSync(ffprobe)) {
      throw new Error(
        "This folder must contain both ffmpeg.exe and ffprobe.exe. Extract the complete FFmpeg download first."
      );
    }
    return {
      ffmpeg: approveSelection(ffmpeg),
      ffprobe: approveSelection(ffprobe)
    };
  });

  ipcMain.handle("download:open", async (_event, kind: keyof typeof downloadPages) => {
    const url = downloadPages[kind];
    if (!url) {
      throw new Error("Unsupported download destination");
    }
    await shell.openExternal(url);
  });

  ipcMain.handle("path:open", async (_event, targetPath: string) => {
    const canonical = canonicalExisting(targetPath);
    if (!isApprovedPath(canonical)) {
      throw new Error("This path has not been approved");
    }
    let error: string | void;
    if (statSync(canonical).isDirectory()) {
      error = await shell.openPath(canonical);
    } else {
      error = await shell.showItemInFolder(canonical);
    }
    if (typeof error === "string" && error) {
      throw new Error(error);
    }
  });

  ipcMain.handle("media:url", (_event, targetPath: string) => {
    const canonical = canonicalExisting(targetPath);
    if (!isApprovedPath(canonical) || !statSync(canonical).isFile()) {
      throw new Error("Media path is not approved");
    }
    const token = randomUUID();
    mediaTokens.set(token, canonical);
    return `studio-media://local/${token}`;
  });
}

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
  });

  void app.whenReady().then(() => {
    log.initialize();
    Menu.setApplicationMenu(null);
    protocol.handle("studio-media", (request) => {
      const token = new URL(request.url).pathname.slice(1);
      const targetPath = mediaTokens.get(token);
      if (!targetPath) {
        return new Response("Not found", { status: 404 });
      }
      return net.fetch(pathToFileURL(targetPath).toString());
    });
    worker = new PythonWorker(
      appRoot,
      (event) => mainWindow?.webContents.send("backend:event", event),
      projectRoot
    );
    worker.start();
    registerIpc();
    createWindow();
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });

  app.on("before-quit", () => worker?.stop());
}
