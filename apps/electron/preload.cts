import { contextBridge, ipcRenderer, webUtils } from "electron";
import type { BackendMethod } from "./python-worker.js" with { "resolution-mode": "import" };

export type StudioApi = {
  backend: <T>(method: BackendMethod, params?: Record<string, unknown>) => Promise<T>;
  selectAudio: () => Promise<string | null>;
  selectVisual: (kind: "texture" | "material") => Promise<string | null>;
  selectFolder: () => Promise<string | null>;
  selectCsv: () => Promise<string | null>;
  selectPackages: () => Promise<string[]>;
  selectPackageOutput: () => Promise<string | null>;
  selectExecutable: (kind: string) => Promise<string | null>;
  selectFfmpeg: () => Promise<{ ffmpeg: string; ffprobe: string } | null>;
  openDownload: (kind: "ffmpeg" | "source2Viewer") => Promise<void>;
  appInfo: () => Promise<{
    name: string;
    version: string;
    platform: string;
    architecture: string;
    electronVersion: string;
    chromiumVersion: string;
    portable: boolean;
    dataRoot: string;
    repositoryUrl: string;
  }>;
  checkForUpdates: () => Promise<{
    currentVersion: string;
    latestVersion: string | null;
    available: boolean;
    releaseName: string | null;
    releaseNotes: string;
    publishedAt: string | null;
    releaseUrl: string;
    assetName: string | null;
    assetUrl: string | null;
    assetSize: number | null;
    assetDigest: string | null;
    canInstall: boolean;
    status: "available" | "current" | "noReleases";
  }>;
  installUpdate: () => Promise<{ downloadedPath: string; sha256: string }>;
  openExternal: (
    kind: "repository" | "profile" | "releases" | "issues"
  ) => Promise<void>;
  openLicenses: () => Promise<void>;
  openPath: (path: string) => Promise<void>;
  mediaUrl: (path: string) => Promise<string>;
  droppedFilePath: (file: File) => Promise<string>;
  onBackendEvent: (listener: (event: Record<string, unknown>) => void) => () => void;
  platform: string;
};

const api: StudioApi = {
  backend: (method, params = {}) => ipcRenderer.invoke("backend:call", method, params),
  selectAudio: () => ipcRenderer.invoke("dialog:audio"),
  selectVisual: (kind) => ipcRenderer.invoke("dialog:visual", kind),
  selectFolder: () => ipcRenderer.invoke("dialog:folder"),
  selectCsv: () => ipcRenderer.invoke("dialog:csv"),
  selectPackages: () => ipcRenderer.invoke("dialog:packages"),
  selectPackageOutput: () => ipcRenderer.invoke("dialog:packageOutput"),
  selectExecutable: (kind) => ipcRenderer.invoke("dialog:executable", kind),
  selectFfmpeg: () => ipcRenderer.invoke("dialog:ffmpeg"),
  openDownload: (kind) => ipcRenderer.invoke("download:open", kind),
  appInfo: () => ipcRenderer.invoke("app:info"),
  checkForUpdates: () => ipcRenderer.invoke("updates:check"),
  installUpdate: () => ipcRenderer.invoke("updates:install"),
  openExternal: (kind) => ipcRenderer.invoke("external:open", kind),
  openLicenses: () => ipcRenderer.invoke("licenses:open"),
  openPath: (targetPath) => ipcRenderer.invoke("path:open", targetPath),
  mediaUrl: (targetPath) => ipcRenderer.invoke("media:url", targetPath),
  droppedFilePath: (file) => ipcRenderer.invoke("drop:approve", webUtils.getPathForFile(file)),
  onBackendEvent: (listener) => {
    const handler = (_event: Electron.IpcRendererEvent, payload: Record<string, unknown>) => listener(payload);
    ipcRenderer.on("backend:event", handler);
    return () => ipcRenderer.removeListener("backend:event", handler);
  },
  platform: process.platform
};

contextBridge.exposeInMainWorld("studio", api);
