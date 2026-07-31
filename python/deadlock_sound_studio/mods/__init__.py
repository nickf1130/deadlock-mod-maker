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

No module here compiles anything or writes to the game folder.
"""

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
