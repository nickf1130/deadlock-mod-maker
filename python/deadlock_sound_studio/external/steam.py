from __future__ import annotations

import os
import re
from pathlib import Path

DEADLOCK_APP_ID = "1422450"


def locate_steam_libraries() -> list[Path]:
    """Return every Steam library that can be found on this machine."""
    roots: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            registry_keys = (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            )
            for hive, key_name in registry_keys:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
                except OSError:
                    pass
        except ImportError:
            pass

    roots.extend(
        [
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            / "Steam",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam",
        ]
    )

    libraries: list[Path] = []
    for root in roots:
        steamapps = root / "steamapps"
        if steamapps.is_dir():
            libraries.append(steamapps)

        library_file = steamapps / "libraryfolders.vdf"
        if not library_file.is_file():
            continue
        text = library_file.read_text(encoding="utf-8", errors="ignore")
        for value in re.findall(r'"path"\s*"([^"]+)"', text):
            candidate = Path(value.replace("\\\\", "\\")) / "steamapps"
            if candidate.is_dir():
                libraries.append(candidate)

    return list(dict.fromkeys(path.resolve() for path in libraries))


def locate_deadlock() -> Path | None:
    """Find a Deadlock install containing the main game archive."""
    for library in locate_steam_libraries():
        manifest = library / f"appmanifest_{DEADLOCK_APP_ID}.acf"
        deadlock = library / "common" / "Deadlock"
        archive = deadlock / "game/citadel/pak01_dir.vpk"
        if archive.is_file() and (manifest.is_file() or deadlock.is_dir()):
            return deadlock.resolve()
    return None
