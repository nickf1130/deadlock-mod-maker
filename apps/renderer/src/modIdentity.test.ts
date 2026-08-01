import { describe, expect, it } from "vitest";
import { identifyMod } from "./modIdentity";
import type { AddonConflictReport, InstalledPackage } from "./types";

function pkg(changes: Partial<InstalledPackage>): InstalledPackage {
  return {
    path: `C:/addons/${changes.filename ?? "pak01_dir.vpk"}`,
    filename: "pak01_dir.vpk",
    entryCount: 1,
    sizeBytes: 1024,
    modId: "650634",
    modName: null,
    enabled: true,
    tracked: true,
    error: null,
    ...changes
  };
}

function report(
  packages: InstalledPackage[],
  usesModManager = true
): AddonConflictReport {
  return { packages, usesModManager } as AddonConflictReport;
}

describe("identifyMod", () => {
  it("puts the manager's title first and its files second", () => {
    const packages = [
      pkg({ filename: "pak01_dir.vpk", modName: "QOL Lock" }),
      pkg({ filename: "pak06_dir.vpk", modName: "QOL Lock" })
    ];

    // Previously this was one 39-character string, "QOL Lock (pak01_dir.vpk,
    // pak06_dir.vpk)", where the filenames took most of the width.
    expect(identifyMod("650634", report(packages))).toEqual({
      title: "QOL Lock",
      detail: "pak01_dir.vpk, pak06_dir.vpk"
    });
  });

  it("says outright when the manager has never heard of a file", () => {
    const packages = [
      pkg({ filename: "pak69_dir.vpk", modId: "pak69_dir.vpk", tracked: false })
    ];

    expect(identifyMod("pak69_dir.vpk", report(packages))).toEqual({
      title: "pak69_dir.vpk",
      detail: "Not tracked by Deadlock Mod Manager"
    });
  });

  it("distinguishes a tracked file the catalogue has no title for", () => {
    // The manager still owns this one; it just cannot name it. Reporting that
    // as untracked would send the player looking for a file to delete.
    const packages = [pkg({ filename: "pak07_dir.vpk", modId: "81508" })];

    expect(identifyMod("81508", report(packages))).toEqual({
      title: "pak07_dir.vpk",
      detail: "No name in the mod manager's catalogue"
    });
  });

  it("adds no commentary when there is no manager to comment on", () => {
    const packages = [
      pkg({ filename: "pak01_dir.vpk", modId: "pak01_dir.vpk", tracked: true })
    ];

    expect(identifyMod("pak01_dir.vpk", report(packages, false))).toEqual({
      title: "pak01_dir.vpk",
      detail: ""
    });
  });
});
