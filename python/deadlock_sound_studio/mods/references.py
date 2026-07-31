"""Read which other resources a compiled Source 2 file points at.

A compiled model does not contain its textures. It refers to materials by path,
and those materials refer to textures by path. Those paths are stored as plain
null-terminated strings inside the compiled file, which is enough to answer a
question the path list alone cannot:

    "This mod replaces the hero model. Does its model still point at the
    materials that other mod supplies?"

If it does not, the two mods will not conflict *and* will not both apply - the
second one simply stops being referenced. That is invisible to a comparison
that only looks at which paths each package contains.

This is deliberately a reader, not a parser. Source 2's compiled format is
undocumented and version-dependent, so rather than decode block headers this
module pulls out the printable strings and keeps the ones shaped like resource
paths. That cannot mis-parse a structure it never claims to understand; the
cost is that a reference stored some other way would be missed, so absence is
reported as "none found", never as proof.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# Source references drop the compiled "_c" suffix: a .vmdl_c points at
# "…/thing.vmat", and the game resolves that to "…/thing.vmat_c" on disk.
REFERENCE_SUFFIXES = ("vmat", "vtex", "vmdl", "vpcf", "vsnd", "vsndevts")

# A resource path: lower-case-ish, slash separated, ending in a known suffix.
# Anchored at both ends because these come from whole null-terminated strings,
# so a partial match means it was not a path in the first place.
RESOURCE_PATH = re.compile(
    r"^[A-Za-z0-9_\-./]+\.(?:" + "|".join(REFERENCE_SUFFIXES) + r")$"
)

# Compiled resources are mostly binary; strings inside them are short.
MAX_STRING_LENGTH = 250


def extract_references(data: bytes) -> list[str]:
    """Return the resource paths mentioned inside a compiled resource.

    Paths are returned without the ``_c`` suffix, exactly as they appear in the
    file, sorted and de-duplicated.
    """
    found: set[str] = set()
    for chunk in data.split(b"\0"):
        if not chunk or len(chunk) > MAX_STRING_LENGTH:
            continue
        try:
            text = chunk.decode("ascii")
        except UnicodeDecodeError:
            continue
        # A bare filename with no directory is ambiguous, and every reference
        # the engine stores is rooted, so require a separator.
        if "/" not in text:
            continue
        if RESOURCE_PATH.match(text):
            found.add(text)
    return sorted(found)


def compiled_path(reference: str) -> str:
    """Turn a stored reference into the path it resolves to inside a VPK.

    ``models/x/materials/body.vmat`` becomes ``models/x/materials/body.vmat_c``.
    """
    return reference if reference.endswith("_c") else f"{reference}_c"


def references_materials(data: bytes) -> list[str]:
    """Compiled material paths a model points at."""
    return [
        compiled_path(reference)
        for reference in extract_references(data)
        if PurePosixPath(reference).suffix == ".vmat"
    ]
