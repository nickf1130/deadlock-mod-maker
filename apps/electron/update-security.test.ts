import { describe, expect, it } from "vitest";
import {
  assertDownloadWithinBounds,
  expectedPortableAssetName,
  isSafeUpdateSize,
  isTrustedReleaseAssetUrl,
  MAX_UPDATE_BYTES,
  normalizeSha256Digest,
  verifyDownloadedUpdate
} from "./update-security.js";

describe("update download security", () => {
  it("accepts only the exact portable asset for the release version", () => {
    const asset = expectedPortableAssetName("1.2.3");
    expect(asset).toBe("DeadlockModMaker-1.2.3-portable.exe");
    expect(
      isTrustedReleaseAssetUrl(
        `https://github.com/nickf1130/deadlock-mod-maker/releases/download/v1.2.3/${asset}`,
        "1.2.3",
        asset
      )
    ).toBe(true);
    expect(
      isTrustedReleaseAssetUrl(
        `https://example.com/nickf1130/deadlock-mod-maker/releases/download/v1.2.3/${asset}`,
        "1.2.3",
        asset
      )
    ).toBe(false);
    expect(() => expectedPortableAssetName("../../unsafe")).toThrow(/unsafe version/i);
  });

  it("normalizes only GitHub-style SHA-256 digests", () => {
    const digest = "a".repeat(64);
    expect(normalizeSha256Digest(`sha256:${digest.toUpperCase()}`)).toBe(digest);
    expect(normalizeSha256Digest(digest)).toBeNull();
    expect(normalizeSha256Digest("sha256:not-a-digest")).toBeNull();
  });

  it("enforces the published size and a hard download limit", () => {
    expect(isSafeUpdateSize(120_000_000)).toBe(true);
    expect(isSafeUpdateSize(0)).toBe(false);
    expect(isSafeUpdateSize(MAX_UPDATE_BYTES + 1)).toBe(false);
    expect(() => assertDownloadWithinBounds(11, 10)).toThrow(/published by GitHub/i);
    expect(() =>
      assertDownloadWithinBounds(MAX_UPDATE_BYTES + 1, MAX_UPDATE_BYTES + 1)
    ).toThrow(/500 MiB/i);
  });

  it("rejects a download whose size or digest differs", () => {
    const expectedSha256 = "1".repeat(64);
    expect(() =>
      verifyDownloadedUpdate({
        actualBytes: 10,
        actualSha256: expectedSha256,
        expectedBytes: 10,
        expectedSha256
      })
    ).not.toThrow();
    expect(() =>
      verifyDownloadedUpdate({
        actualBytes: 9,
        actualSha256: expectedSha256,
        expectedBytes: 10,
        expectedSha256
      })
    ).toThrow(/size/i);
    expect(() =>
      verifyDownloadedUpdate({
        actualBytes: 10,
        actualSha256: "2".repeat(64),
        expectedBytes: 10,
        expectedSha256
      })
    ).toThrow(/SHA-256/i);
  });
});
