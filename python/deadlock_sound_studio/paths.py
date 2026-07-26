from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .errors import validation_error
from .models import PortablePaths


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    tools: Path
    data: Path
    cache: Path
    projects: Path
    exports: Path
    logs: Path
    backups: Path

    @classmethod
    def resolve(cls) -> AppPaths:
        explicit = os.environ.get("DSS_APP_ROOT")
        root = Path(sys.executable).resolve().parent
        if explicit:
            root = Path(explicit)
        return cls.from_root(root)

    @classmethod
    def from_root(cls, root: Path) -> AppPaths:
        resolved = root.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        instance = cls(
            root=resolved,
            tools=resolved / "tools",
            data=resolved / "data",
            cache=resolved / "cache",
            projects=resolved / "projects",
            exports=resolved / "exports",
            logs=resolved / "logs",
            backups=resolved / "backups",
        )
        # The settings and database are required as soon as the app starts.
        # Every other folder is created by the feature that actually uses it.
        # This keeps a fresh portable install from filling up with empty folders.
        instance.data.mkdir(parents=True, exist_ok=True)
        return instance

    @property
    def database(self) -> Path:
        return self.data / "deadlock-sound-studio.sqlite3"

    @property
    def settings_file(self) -> Path:
        return self.data / "settings.json"

    def project(self, project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise validation_error("Invalid project identifier", projectId=project_id)
        return self.projects / project_id

    def public(self) -> PortablePaths:
        return PortablePaths(**{name: str(getattr(self, name)) for name in PortablePaths.model_fields})


def ensure_within(path: Path, roots: tuple[Path, ...], *, must_exist: bool = True) -> Path:
    candidate = path.expanduser()
    if must_exist:
        candidate = candidate.resolve(strict=True)
    else:
        candidate = candidate.resolve(strict=False)
    for root in roots:
        resolved_root = root.resolve(strict=True)
        try:
            candidate.relative_to(resolved_root)
            return candidate
        except ValueError:
            continue
    raise validation_error("Path is outside approved roots", path=str(candidate))


def normalize_addon_name(value: str) -> str:
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-" for character in value):
        raise validation_error("Addon names may contain only letters, numbers, spaces, dashes, and underscores")
    normalized = re.sub(r"[_ -]+", "_", value.strip().lower()).strip("_")
    if not normalized or len(normalized) > 64 or not normalized[0].isalpha():
        raise validation_error("Addon name must be 1–64 characters and begin with a letter")
    return normalized


def normalize_internal_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ":" in normalized or "\x00" in normalized:
        raise validation_error("Invalid internal asset path", path=value)
    path = PurePosixPath(normalized)
    if any(part in ("", ".", "..") for part in path.parts):
        raise validation_error("Internal path contains an unsafe segment", path=value)
    if any(character in normalized for character in ('"', "<", ">")):
        raise validation_error("Internal path contains unsupported characters", path=value)
    return path.as_posix()


def source_path_for_compiled(value: str) -> str:
    normalized = normalize_internal_path(value)
    if not normalized.lower().endswith(".vsnd_c"):
        raise validation_error("Target must be a compiled .vsnd_c sound", path=value)
    return normalized[: -len(".vsnd_c")] + ".wav"
