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

``comparison``
    "Can I combine these two mods?" Compares any two packages and reports the
    paths they share.

``cleanup``
    "Why is this mod still loading?" Moves packages a mod manager has lost
    track of out of the addons folder. The one module here that writes to the
    game folder, and even then it only ever moves a file into a backup.

No module here compiles anything.
"""

from .cleanup import BackupResult, MovedPackage, move_packages_to_backup
from .comparison import ComparedPackage, ComparisonReport, SharedPath, compare_mod_packages
from .conflicts import (
    Conflict,
    ConflictReport,
    InstalledPackage,
    ModConflict,
    ModManagerState,
    find_addon_conflicts,
    is_compiled_resource,
    read_mod_manager_state,
)
from .inspection import ModEntry, ModPackageReport, inspect_mod_package, suggest_project_name

__all__ = [
    "BackupResult",
    "MovedPackage",
    "move_packages_to_backup",
    "ComparedPackage",
    "ComparisonReport",
    "SharedPath",
    "compare_mod_packages",
    "Conflict",
    "ConflictReport",
    "InstalledPackage",
    "ModConflict",
    "ModManagerState",
    "ModEntry",
    "ModPackageReport",
    "find_addon_conflicts",
    "inspect_mod_package",
    "is_compiled_resource",
    "read_mod_manager_state",
    "suggest_project_name",
]
