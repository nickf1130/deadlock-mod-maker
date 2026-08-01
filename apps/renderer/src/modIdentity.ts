import type { AddonConflictReport } from "./types";

/**
 * How one mod should be named on screen.
 *
 * A mod has two names and they serve different readers. `title` is the one a
 * person recognises — the title Deadlock Mod Manager shows. `detail` is the
 * bookkeeping: which .vpk files it owns, or why no better name exists.
 *
 * Keeping them apart is the whole point. Flattened into a single string they
 * become "QOL Lock (pak01_dir.vpk, pak06_dir.vpk)", where the half that
 * matters least is the half that takes up the most room.
 */
export type ModIdentity = {
  title: string;
  detail: string;
};

/**
 * Work out what to call the mod behind `modId`.
 *
 * Four cases, in the order they are worth distinguishing:
 *
 * 1. The manager knows its title — use it, and list its packages as detail.
 * 2. The manager tracks the files but has no title for them. Usually a mod
 *    removed from the site after it was installed.
 * 3. The manager is running but has never heard of this file. Worth saying
 *    outright, because it means the game is loading something the manager
 *    cannot switch off.
 * 4. No manager at all — the filename is the only name there is, and nothing
 *    more needs saying.
 */
export function identifyMod(modId: string, report: AddonConflictReport): ModIdentity {
  const packages = report.packages.filter((installed) => installed.modId === modId);
  const filenames = packages.map((installed) => installed.filename);
  const listed = filenames.join(", ");

  const name = packages.find((installed) => installed.modName)?.modName;
  if (name) {
    return { title: name, detail: listed };
  }
  if (!report.usesModManager || filenames.length === 0) {
    return { title: listed || modId, detail: "" };
  }
  if (packages.every((installed) => !installed.tracked)) {
    return { title: listed, detail: "Not tracked by Deadlock Mod Manager" };
  }
  return { title: listed, detail: "No name in the mod manager's catalogue" };
}
