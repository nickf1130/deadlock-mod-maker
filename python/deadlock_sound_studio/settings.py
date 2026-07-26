from __future__ import annotations

import json
from pathlib import Path

from .models import Settings
from .paths import AppPaths


def load_settings(paths: AppPaths) -> Settings:
    if not paths.settings_file.exists():
        return Settings()
    return Settings.model_validate_json(paths.settings_file.read_text(encoding="utf-8"))


def save_settings(paths: AppPaths, settings: Settings) -> Settings:
    temporary = paths.settings_file.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings.model_dump(by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(paths.settings_file)
    return settings


def optional_existing(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.exists() else None
