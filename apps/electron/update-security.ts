export const MAX_UPDATE_BYTES = 500 * 1024 * 1024;

const SAFE_VERSION = /^[0-9][0-9A-Za-z.+-]{0,63}$/;
const SHA256_DIGEST = /^sha256:([0-9a-f]{64})$/i;

export function expectedPortableAssetName(version: string): string {
  if (!SAFE_VERSION.test(version)) {
    throw new Error("The GitHub release has an unsafe version tag.");
  }
  return `DeadlockModMaker-${version}-portable.exe`;
}

export function normalizeSha256Digest(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = SHA256_DIGEST.exec(value.trim());
  if (!match) {
    return null;
  }
  return match[1].toLowerCase();
}

export function isTrustedReleaseAssetUrl(
  value: unknown,
  version: string,
  assetName: string
): value is string {
  if (typeof value !== "string") {
    return false;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.hostname.toLowerCase() !== "github.com") {
      return false;
    }
    const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
    if (
      parts.length !== 6 ||
      parts[0].toLowerCase() !== "nickf1130" ||
      parts[1].toLowerCase() !== "deadlock-mod-maker" ||
      parts[2] !== "releases" ||
      parts[3] !== "download" ||
      parts[5].toLowerCase() !== assetName.toLowerCase()
    ) {
      return false;
    }
    const tag = parts[4].replace(/^v/i, "");
    return tag.toLowerCase() === version.toLowerCase();
  } catch {
    return false;
  }
}

export function isSafeUpdateSize(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value > 0 &&
    value <= MAX_UPDATE_BYTES
  );
}

export function assertDownloadWithinBounds(
  downloadedBytes: number,
  expectedBytes: number
): void {
  if (downloadedBytes > MAX_UPDATE_BYTES) {
    throw new Error("The update download exceeded the 500 MiB safety limit.");
  }
  if (downloadedBytes > expectedBytes) {
    throw new Error("The update download exceeded the size published by GitHub.");
  }
}

export function verifyDownloadedUpdate(input: {
  actualBytes: number;
  actualSha256: string;
  expectedBytes: number;
  expectedSha256: string;
}): void {
  if (input.actualBytes !== input.expectedBytes) {
    throw new Error("The downloaded update size does not match the GitHub release.");
  }
  if (input.actualSha256.toLowerCase() !== input.expectedSha256.toLowerCase()) {
    throw new Error("The downloaded update failed SHA-256 verification.");
  }
}
