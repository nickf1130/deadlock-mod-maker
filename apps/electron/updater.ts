import { app, net } from "electron";
import { once } from "node:events";
import {
  createWriteStream,
  existsSync,
  mkdirSync,
  realpathSync,
  rmSync,
  statSync
} from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import {
  assertDownloadWithinBounds,
  expectedPortableAssetName,
  isSafeUpdateSize,
  isTrustedReleaseAssetUrl,
  normalizeSha256Digest,
  verifyDownloadedUpdate
} from "./update-security.js";
import { compareVersions } from "./version.js";

export const REPOSITORY_URL = "https://github.com/nickf1130/deadlock-mod-maker";
export const RELEASES_URL = `${REPOSITORY_URL}/releases`;
export const ISSUES_URL = `${REPOSITORY_URL}/issues`;
export const PROFILE_URL = "https://github.com/nickf1130";
const RELEASE_API =
  "https://api.github.com/repos/nickf1130/deadlock-mod-maker/releases/latest";

type GitHubAsset = {
  name?: unknown;
  size?: unknown;
  browser_download_url?: unknown;
  digest?: unknown;
};

type GitHubRelease = {
  tag_name?: unknown;
  name?: unknown;
  body?: unknown;
  html_url?: unknown;
  published_at?: unknown;
  assets?: unknown;
};

export type UpdateInfo = {
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
};

export async function checkForUpdates(): Promise<UpdateInfo> {
  const currentVersion = app.getVersion();
  const response = await net.fetch(RELEASE_API, {
    signal: AbortSignal.timeout(12_000),
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": `Deadlock-Mod-Maker/${currentVersion}`,
      "X-GitHub-Api-Version": "2022-11-28"
    }
  });
  if (response.status === 404) {
    return {
      currentVersion,
      latestVersion: null,
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
      status: "noReleases"
    };
  }
  if (!response.ok) {
    throw new Error(`GitHub release check failed with HTTP ${response.status}.`);
  }
  const release = (await response.json()) as GitHubRelease;
  const latestVersion =
    typeof release.tag_name === "string"
      ? release.tag_name.replace(/^v/i, "")
      : null;
  if (!latestVersion) throw new Error("The latest GitHub release has no valid version tag.");
  const expectedAssetName = expectedPortableAssetName(latestVersion);
  const assets = Array.isArray(release.assets)
    ? (release.assets as GitHubAsset[])
    : [];
  const asset = assets.find(
    (candidate) =>
      typeof candidate.name === "string" &&
      candidate.name.toLowerCase() === expectedAssetName.toLowerCase()
  );
  const assetName = typeof asset?.name === "string" ? asset.name : null;
  const assetUrl =
    typeof asset?.browser_download_url === "string"
      ? asset.browser_download_url
      : null;
  const assetSize = isSafeUpdateSize(asset?.size) ? asset.size : null;
  const assetDigest = normalizeSha256Digest(asset?.digest);
  const trustedAsset = Boolean(
    assetName &&
      assetUrl &&
      assetSize &&
      assetDigest &&
      isTrustedReleaseAssetUrl(assetUrl, latestVersion, assetName)
  );
  const portableExecutable = process.env.PORTABLE_EXECUTABLE_FILE;
  const available = compareVersions(latestVersion, currentVersion) > 0;
  return {
    currentVersion,
    latestVersion,
    available,
    releaseName:
      typeof release.name === "string" ? release.name : `Version ${latestVersion}`,
    releaseNotes: typeof release.body === "string" ? release.body.slice(0, 40_000) : "",
    publishedAt:
      typeof release.published_at === "string" ? release.published_at : null,
    releaseUrl:
      typeof release.html_url === "string" ? release.html_url : RELEASES_URL,
    assetName,
    assetUrl,
    assetSize,
    assetDigest,
    canInstall: Boolean(
      available &&
        trustedAsset &&
        portableExecutable &&
        path.isAbsolute(portableExecutable) &&
        existsSync(portableExecutable)
    ),
    status: available ? "available" : "current"
  };
}

function quotePowerShell(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

export async function downloadAndApplyUpdate(
  update: UpdateInfo,
  appRoot: string,
  progress: (payload: Record<string, unknown>) => void
): Promise<{ downloadedPath: string; sha256: string }> {
  if (
    !update.available ||
    !update.canInstall ||
    !update.latestVersion ||
    !update.assetName ||
    !update.assetUrl ||
    !update.assetDigest ||
    !update.assetSize
  ) {
    throw new Error(
      "Automatic installation requires a newer portable GitHub release with a published SHA-256 digest."
    );
  }
  const expectedAssetName = expectedPortableAssetName(update.latestVersion);
  if (update.assetName.toLowerCase() !== expectedAssetName.toLowerCase()) {
    throw new Error("The GitHub release asset does not match the release version.");
  }
  if (!isSafeUpdateSize(update.assetSize)) {
    throw new Error("The GitHub release asset has an invalid size.");
  }
  if (
    !isTrustedReleaseAssetUrl(
      update.assetUrl,
      update.latestVersion,
      update.assetName
    )
  ) {
    throw new Error("The GitHub release asset URL is not trusted.");
  }
  const oldExecutable = process.env.PORTABLE_EXECUTABLE_FILE;
  if (!oldExecutable || !path.isAbsolute(oldExecutable) || !existsSync(oldExecutable)) {
    throw new Error("The running portable executable could not be identified.");
  }
  const oldCanonical = realpathSync.native(oldExecutable);
  const destinationDirectory = path.dirname(oldCanonical);
  const updateRoot = path.resolve(appRoot, "updates");
  mkdirSync(updateRoot, { recursive: true });
  const partial = path.join(updateRoot, `${update.assetName}.${process.pid}.download`);
  const finalPath = path.join(destinationDirectory, path.basename(update.assetName));
  if (existsSync(partial)) rmSync(partial, { force: true });

  progress({
    event: "update.progress",
    stage: "connecting",
    message: `Connecting to GitHub for ${update.assetName}…`,
    downloadedBytes: 0,
    totalBytes: update.assetSize ?? 0
  });
  const response = await net.fetch(update.assetUrl, {
    signal: AbortSignal.timeout(10 * 60_000),
    headers: {
      Accept: "application/octet-stream",
      "User-Agent": `Deadlock-Mod-Maker/${app.getVersion()}`
    },
    redirect: "follow"
  });
  if (!response.ok || !response.body) {
    throw new Error(`Update download failed with HTTP ${response.status}.`);
  }
  const totalBytes =
    Number.parseInt(response.headers.get("content-length") ?? "", 10) ||
    update.assetSize;
  if (!isSafeUpdateSize(totalBytes) || totalBytes !== update.assetSize) {
    throw new Error("The update response size does not match the GitHub release.");
  }
  const crypto = await import("node:crypto");
  const hasher = crypto.createHash("sha256");
  const writer = createWriteStream(partial, { flags: "wx" });
  const reader = response.body.getReader();
  let downloadedBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = Buffer.from(value);
      hasher.update(chunk);
      downloadedBytes += chunk.length;
      assertDownloadWithinBounds(downloadedBytes, update.assetSize);
      if (!writer.write(chunk)) await once(writer, "drain");
      progress({
        event: "update.progress",
        stage: "downloading",
        message: `Downloading ${update.assetName}…`,
        downloadedBytes,
        totalBytes
      });
    }
    const finished = once(writer, "finish");
    writer.end();
    await finished;
  } catch (error) {
    writer.destroy();
    if (existsSync(partial)) rmSync(partial, { force: true });
    throw error;
  }
  if (!existsSync(partial)) {
    throw new Error("The downloaded update is missing.");
  }
  const sha256 = hasher.digest("hex");
  try {
    verifyDownloadedUpdate({
      actualBytes: statSync(partial).size,
      actualSha256: sha256,
      expectedBytes: update.assetSize,
      expectedSha256: update.assetDigest
    });
  } catch (error) {
    rmSync(partial, { force: true });
    throw error;
  }
  progress({
    event: "update.progress",
    stage: "ready",
    message: "Update downloaded. Restarting Deadlock Mod Maker…",
    downloadedBytes,
    totalBytes
  });

  const logPath = path.join(updateRoot, "last-update.log");
  const command = `
$ErrorActionPreference = "Stop"
$oldPid = ${process.pid}
$oldPath = ${quotePowerShell(oldCanonical)}
$downloadPath = ${quotePowerShell(partial)}
$newPath = ${quotePowerShell(finalPath)}
$logPath = ${quotePowerShell(logPath)}
try {
  Wait-Process -Id $oldPid -ErrorAction SilentlyContinue
  Move-Item -LiteralPath $downloadPath -Destination $newPath -Force
  Start-Process -FilePath $newPath
  if ($oldPath -ne $newPath) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
      if (-not (Test-Path -LiteralPath $oldPath)) { break }
      try { Remove-Item -LiteralPath $oldPath -Force -ErrorAction Stop; break }
      catch { Start-Sleep -Seconds 1 }
    }
  }
  Add-Content -LiteralPath $logPath -Value ("Update applied at " + (Get-Date).ToString("o"))
} catch {
  Add-Content -LiteralPath $logPath -Value ("Update failed: " + $_.Exception.Message)
  if (Test-Path -LiteralPath $newPath) { Start-Process -FilePath $newPath }
}
`;
  const encoded = Buffer.from(command, "utf16le").toString("base64");
  const helper = spawn(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
    { detached: true, windowsHide: true, stdio: "ignore" }
  );
  helper.unref();
  setTimeout(() => app.quit(), 250);
  return { downloadedPath: partial, sha256 };
}
