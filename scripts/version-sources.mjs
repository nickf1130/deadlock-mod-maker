/**
 * Every file that repeats the application version.
 *
 * package.json is the single source of truth. Everything listed here is a copy
 * that has to be kept in step with it, which is why the list lives in one place
 * and is shared by both scripts that care about it:
 *
 *   scripts/set-version.mjs     writes the version into all of them
 *   scripts/verify-version.mjs  fails the build if any of them drifts
 *
 * To add a new file, append one entry with a `pattern` whose first capture
 * group is the version, and a `replace` that rebuilds the same text with a new
 * version. Both scripts pick it up automatically.
 */

/** Escapes a string so it can be dropped into a regular expression literally. */
function escapeForRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function versionSources(packageName) {
  return [
    {
      file: "package-lock.json",
      // The lock file mentions "version" hundreds of times, once per dependency.
      // Anchoring to the package name pins it to the two entries that describe
      // this application: the root object and packages[""].
      pattern: new RegExp(
        `"name": "${escapeForRegExp(packageName)}",\\s*"version": "([^"]+)"`
      ),
      replace: (text, version) =>
        text.replace(
          new RegExp(
            `("name": "${escapeForRegExp(packageName)}",\\s*"version": ")[^"]+(")`,
            "g"
          ),
          `$1${version}$2`
        )
    },
    {
      file: "python/pyproject.toml",
      pattern: /^version = "([^"]+)"$/m,
      replace: (text, version) =>
        text.replace(/^version = "[^"]+"$/m, `version = "${version}"`)
    },
    {
      file: "python/deadlock_sound_studio/__init__.py",
      pattern: /^__version__ = "([^"]+)"$/m,
      replace: (text, version) =>
        text.replace(/^__version__ = "[^"]+"$/m, `__version__ = "${version}"`)
    },
    {
      file: "python/deadlock_sound_studio/requirements.py",
      pattern: /^USER_AGENT = "Deadlock-Mod-Maker\/([^"]+)"$/m,
      replace: (text, version) =>
        text.replace(
          /^USER_AGENT = "Deadlock-Mod-Maker\/[^"]+"$/m,
          `USER_AGENT = "Deadlock-Mod-Maker/${version}"`
        )
    }
  ];
}
