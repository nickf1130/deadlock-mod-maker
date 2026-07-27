"""Reading mod packages that already exist, rather than building new ones.

The rest of the application turns source files into a mod. This package goes the
other way: it reads finished ``.vpk`` files - ones downloaded from a mod site or
already sitting in the game's addons folder - and explains what they contain.

Two questions are answered here:

``inspection``
    "What does this mod replace, and will it still work?" Compares a package
    against the indexed game archive.

``conflicts``
    "Do my installed mods fight each other?" Compares installed packages
    against each other.

Neither module compiles anything or writes to the game folder.
"""

from .conflicts import Conflict, ConflictReport, InstalledPackage, find_addon_conflicts
from .inspection import ModEntry, ModPackageReport, inspect_mod_package, suggest_project_name

__all__ = [
    "Conflict",
    "ConflictReport",
    "InstalledPackage",
    "ModEntry",
    "ModPackageReport",
    "find_addon_conflicts",
    "inspect_mod_package",
    "suggest_project_name",
]
