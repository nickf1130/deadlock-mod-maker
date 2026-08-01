from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..audio import inspect_audio, process_audio, silence_processing, write_silence
from ..batch import (
    preview_folder,
    preview_mapping_file,
    resolve_folder,
    resolve_mapping_file,
)
from ..build import BuildJob, create_compatibility_copy, create_zip
from ..database import Database
from ..diagnostics import run_diagnostics
from ..errors import StudioError, capability_error, validation_error
from ..external.process import CancellationToken
from ..indexing import index_archive
from ..mods import (
    compare_mod_packages,
    find_addon_conflicts,
    inspect_mod_package,
    move_packages_to_backup,
)
from ..models import (
    LoopSettings,
    ProcessingSettings,
    Settings,
    VisualResourceKind,
)
from ..packages import RenameRule, combine_packages, extract_package, inspect_packages
from ..paths import AppPaths, normalize_internal_path
from ..projects import ProjectService, detect_conflicts
from ..requirements import install_missing_requirements
from ..settings import load_settings, save_settings
from ..source_viewer import (
    export_package_sound,
    export_sound_preview,
    export_visual_preview,
)
from ..updates import relocation_score
from ..visuals import inspect_visual_source
from ..vpk import list_vpk


def _optional_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(value)


def _package_cache_key(package: Path) -> str:
    """Identify a mod file by where it is and when it last changed.

    Reinstalling or updating a mod rewrites the .vpk, and the previews taken
    from the old one are then wrong. Folding the modification time into the key
    retires them without needing to hunt them down.
    """
    digest = hashlib.sha1(
        f"{package.resolve()}|{package.stat().st_mtime_ns}".encode("utf-8")
    )
    return digest.hexdigest()[:16]


def _path_cache_key(internal_path: str) -> str:
    """A filesystem-safe folder name for an archive-internal path."""
    return hashlib.sha1(internal_path.casefold().encode("utf-8")).hexdigest()[:16]


class ParamsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ProjectIdParams(ParamsModel):
    project_id: str = Field(alias="projectId")


class CreateProjectParams(ParamsModel):
    display_name: str = Field(alias="displayName", min_length=1, max_length=80)
    description: str = ""
    author: str = ""


class SearchParams(ParamsModel):
    query: str = ""
    category: str | None = None
    scope: Literal["all", "heroes", "general"] = "all"
    limit: int = Field(default=250, ge=1, le=1000)


class AssetParams(ParamsModel):
    asset_id: str = Field(alias="assetId")


# Browsing takes the same filters as searching, so the tree and the counts on
# it always describe the same set of files the search box would return.
class FolderListParams(ParamsModel):
    category: str | None = None
    scope: Literal["all", "heroes", "general"] = "all"


class BrowseFolderParams(ParamsModel):
    # Empty means the root, where the top-level folders live.
    folder: str = ""
    category: str | None = None
    scope: Literal["all", "heroes", "general"] = "all"


class VisualFolderListParams(ParamsModel):
    kind: Literal["texture", "material"] | None = None


class BrowseVisualFolderParams(ParamsModel):
    folder: str = ""
    kind: Literal["texture", "material"] | None = None


class VisualSearchParams(ParamsModel):
    query: str = ""
    kind: Literal["texture", "material"] | None = None
    limit: int = Field(default=250, ge=1, le=1000)


class VisualInspectParams(ParamsModel):
    path: str
    kind: VisualResourceKind


class ConfirmVisualParams(ParamsModel):
    project_id: str = Field(alias="projectId")
    asset_id: str = Field(alias="assetId")
    source_path: str = Field(alias="sourcePath")


class AudioInspectParams(ParamsModel):
    path: str


class PreviewProcessedParams(ParamsModel):
    path: str
    processing: ProcessingSettings


class SilenceParams(ParamsModel):
    project_id: str = Field(alias="projectId")
    asset_id: str = Field(alias="assetId")


class ConfirmParams(ParamsModel):
    project_id: str = Field(alias="projectId")
    asset_id: str = Field(alias="assetId")
    source_path: str = Field(alias="sourcePath")
    processing: ProcessingSettings
    looping: LoopSettings


class UpdateItemParams(ParamsModel):
    project_id: str = Field(alias="projectId")
    item_id: str = Field(alias="itemId")
    changes: dict[str, Any]


class DuplicateSettingsParams(ProjectIdParams):
    source_item_id: str = Field(alias="sourceItemId")
    target_item_id: str = Field(alias="targetItemId")


class RemoveItemParams(ParamsModel):
    project_id: str = Field(alias="projectId")
    item_id: str = Field(alias="itemId")


class ReplaceSourceParams(RemoveItemParams):
    source_path: str = Field(alias="sourcePath")


class ReorderItemParams(RemoveItemParams):
    new_index: int = Field(alias="newIndex", ge=0)


class RemapItemParams(RemoveItemParams):
    asset_id: str = Field(alias="assetId")


class HistoryParams(ParamsModel):
    limit: int = Field(default=20, ge=1, le=100)


class MappingFileParams(ParamsModel):
    path: str


class BatchRowSettingsParams(ParamsModel):
    processing: ProcessingSettings
    looping: LoopSettings


class BatchConfirmParams(ProjectIdParams):
    path: str
    kind: Literal["file", "folder"]
    row_numbers: list[int] = Field(alias="rowNumbers")
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    looping: LoopSettings = Field(default_factory=LoopSettings)
    row_settings: dict[int, BatchRowSettingsParams] = Field(
        default_factory=dict, alias="rowSettings"
    )


class BatchRollbackParams(ProjectIdParams):
    transaction_id: str = Field(alias="transactionId")


class BuildParams(ProjectIdParams):
    job_id: str = Field(alias="jobId")
    retry_failed_only: bool = Field(default=False, alias="retryFailedOnly")


class CancelParams(ParamsModel):
    job_id: str = Field(alias="jobId")


class CreateZipParams(ProjectIdParams):
    version: str


class PackagePathsParams(ParamsModel):
    paths: list[str] = Field(min_length=1, max_length=50)


class RenameRuleParams(ParamsModel):
    package: str
    source: str
    target: str


class CombinePackagesParams(PackagePathsParams):
    output_path: str = Field(alias="outputPath")
    # Optional redirects, used when two mods supply the same thing at
    # different paths. See packages.RenameRule.
    renames: list[RenameRuleParams] = Field(default_factory=list)


class ExtractPackageParams(ParamsModel):
    path: str
    output_path: str = Field(alias="outputPath")
    internal_paths: list[str] = Field(alias="internalPaths", min_length=1)


class ModPackageParams(ParamsModel):
    path: str


class CompareModsParams(ParamsModel):
    paths: list[str] = Field(min_length=2, max_length=10)


class AddonConflictParams(ParamsModel):
    # Omitted by the UI in the normal case, where the addons folder is derived
    # from the Deadlock installation the user already selected in Diagnostics.
    directory: str | None = None


class ModSoundPreviewParams(ParamsModel):
    """One sound inside one mod package."""

    path: str
    internal_path: str = Field(alias="internalPath")


class BackupPackagesParams(ParamsModel):
    paths: list[str] = Field(min_length=1, max_length=50)


class BackendRouter:
    def __init__(self, paths: AppPaths, emit_event):
        self.paths = paths
        self.emit_event = emit_event
        self.database = Database(paths)
        self.projects = ProjectService(paths, self.database)
        self.jobs: dict[str, CancellationToken] = {}
        self.handlers = {
            "app.bootstrap": self.bootstrap,
            "diagnostics.run": self.diagnostics,
            "requirements.install": self.install_requirements,
            "settings.save": self.save_settings,
            "projects.create": self.create_project,
            "projects.list": self.list_projects,
            "projects.get": self.get_project,
            "projects.delete": self.delete_project,
            "projects.confirmReplacement": self.confirm_replacement,
            "projects.silenceReplacement": self.silence_replacement,
            "projects.updateReplacement": self.update_replacement,
            "projects.replaceSource": self.replace_source,
            "projects.duplicateSettings": self.duplicate_settings,
            "projects.removeReplacement": self.remove_replacement,
            "projects.reorderReplacement": self.reorder_replacement,
            "projects.remapTarget": self.remap_target,
            "projects.conflicts": self.project_conflicts,
            "projects.compatibility": self.project_compatibility,
            "projects.confirmVisualReplacement": self.confirm_visual_replacement,
            "projects.updateVisualReplacement": self.update_visual_replacement,
            "projects.removeVisualReplacement": self.remove_visual_replacement,
            "sounds.index": self.index_sounds,
            "sounds.indexHistory": self.index_history,
            "sounds.search": self.search_sounds,
            "sounds.folders": self.sound_folders,
            "sounds.browse": self.browse_sounds,
            "sounds.preview": self.preview_sound,
            "visuals.search": self.search_visuals,
            "visuals.folders": self.visual_folders,
            "visuals.browse": self.browse_visuals,
            "visuals.preview": self.preview_visual,
            "visuals.inspectSource": self.inspect_visual_source,
            "audio.inspect": self.inspect_audio,
            "audio.previewProcessed": self.preview_processed,
            "batch.previewCsv": self.preview_csv,
            "batch.previewFolder": self.preview_folder,
            "batch.confirm": self.confirm_batch,
            "batch.rollback": self.rollback_batch,
            "build.start": self.start_build,
            "build.cancel": self.cancel_build,
            "build.validateExport": self.validate_export,
            "export.createZip": self.create_zip,
            "export.createCompatibilityCopy": self.create_compatibility_copy,
            "packages.inspect": self.inspect_packages,
            "packages.combine": self.combine_packages,
            "packages.extract": self.extract_package,
            "mods.inspect": self.inspect_mod,
            "mods.addonConflicts": self.addon_conflicts,
            "mods.previewSound": self.preview_mod_sound,
            "mods.backupPackages": self.backup_packages,
            "mods.compare": self.compare_mods,
        }

    def close(self) -> None:
        self.database.close()

    def dispatch(self, method: str, raw_params: dict[str, Any]) -> Any:
        handler = self.handlers.get(method)
        if not handler:
            raise StudioError("METHOD_NOT_ALLOWED", f"Unknown backend method: {method}")
        return handler(raw_params)

    def _diagnostics(self, *, emit_progress: bool = False):
        """Run tool discovery only for operations that actually need tools."""
        progress = None
        if emit_progress:
            progress = self.emit_event
        return run_diagnostics(
            self.paths,
            load_settings(self.paths),
            progress,
        )

    def bootstrap(self, raw: dict[str, Any]) -> dict[str, Any]:
        ParamsModel.model_validate(raw)
        self.projects.clear_exported_build_artifacts()
        settings = load_settings(self.paths)
        diagnostics = self._diagnostics(emit_progress=True)
        sound_count = self.database.count_assets()
        visual_count = self.database.count_visual_assets()
        auto_index: dict[str, Any] = {
            "attempted": False,
            "indexed": 0,
            "visualIndexed": 0,
            "warning": None,
        }
        archive = diagnostics.resolved.deadlock_archive
        if (
            settings.setup_completed
            and (sound_count == 0 or visual_count == 0)
            and diagnostics.can_index
            and archive
        ):
            auto_index["attempted"] = True
            self.emit_event(
                {
                    "event": "index.progress",
                    "stage": "readingArchive",
                    "message": "Building the first-run resource catalog…",
                }
            )
            try:
                result = index_archive(self.database, Path(archive))
                sound_count = result.indexed
                visual_count = result.visual_indexed
                auto_index["indexed"] = result.indexed
                auto_index["visualIndexed"] = result.visual_indexed
                self.emit_event(
                    {
                        "event": "index.progress",
                        "stage": "complete",
                        "message": (
                            f"Indexed {result.indexed} sounds and "
                            f"{result.visual_indexed} visual resources."
                        ),
                    }
                )
            except Exception as error:
                auto_index["warning"] = str(error)
                self.emit_event(
                    {
                        "event": "index.progress",
                        "stage": "failed",
                        "message": str(error),
                    }
                )
        return {
            "paths": self.paths.public().model_dump(by_alias=True),
            "settings": settings.model_dump(by_alias=True),
            "diagnostics": diagnostics.model_dump(by_alias=True),
            "projects": [
                project.model_dump(by_alias=True) for project in self.projects.list()
            ],
            "soundCount": sound_count,
            "visualCount": visual_count,
            "gameFingerprint": self._current_game_fingerprint(),
            "autoIndex": auto_index,
        }

    def _current_game_fingerprint(self) -> str:
        """Fingerprint of the most recently indexed game archive, if any."""
        history = self.database.index_history(limit=1)
        if not history:
            return ""
        return str(history[0].get("archiveFingerprint") or "")

    def diagnostics(self, raw: dict[str, Any]) -> dict[str, Any]:
        ParamsModel.model_validate(raw)
        return run_diagnostics(
            self.paths,
            load_settings(self.paths),
            self.emit_event,
        ).model_dump(by_alias=True)

    def install_requirements(self, raw: dict[str, Any]) -> dict[str, object]:
        ParamsModel.model_validate(raw)
        return install_missing_requirements(
            self.paths,
            load_settings(self.paths),
            self.emit_event,
        )

    def save_settings(self, raw: dict[str, Any]) -> dict[str, Any]:
        settings = Settings.model_validate(raw)
        save_settings(self.paths, settings)
        return run_diagnostics(self.paths, settings, self.emit_event).model_dump(
            by_alias=True
        )

    def create_project(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = CreateProjectParams.model_validate(raw)
        return self.projects.create(
            params.display_name, params.description, params.author
        ).model_dump(by_alias=True)

    def list_projects(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        ParamsModel.model_validate(raw)
        return [
            value.model_dump(by_alias=True) for value in self.projects.list()
        ]

    def get_project(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ProjectIdParams.model_validate(raw)
        return self.projects.load(params.project_id).model_dump(by_alias=True)

    def delete_project(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ProjectIdParams.model_validate(raw)
        backup_path = self.projects.delete(params.project_id)
        return {"projectId": params.project_id, "backupPath": str(backup_path)}

    def confirm_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ConfirmParams.model_validate(raw)
        diagnostics = self._diagnostics()
        ffprobe = diagnostics.resolved.ffprobe
        return self.projects.confirm_replacement(
            params.project_id,
            params.asset_id,
            Path(params.source_path),
            params.processing,
            params.looping,
            _optional_path(ffprobe),
        ).model_dump(by_alias=True)

    def silence_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Replace a sound with silence, so it stops playing in game.

        Generates the silent source itself rather than asking for a file, then
        confirms it through the ordinary replacement path so the build,
        validation and conflict rules all still apply.
        """
        params = SilenceParams.model_validate(raw)
        asset = self.database.get_asset(params.asset_id)
        if not asset:
            raise StudioError("ASSET_NOT_FOUND", "The indexed target sound no longer exists.")

        # Written under the app's cache; confirm_replacement copies it into the
        # project, so this copy is only needed for the length of the call.
        source = self.paths.cache / "silence" / f"{params.asset_id}.wav"
        write_silence(source, sample_rate=asset.sample_rate, channels=asset.channels)
        try:
            manifest = self.projects.confirm_replacement(
                params.project_id,
                params.asset_id,
                source,
                silence_processing(asset.sample_rate, asset.channels),
                LoopSettings(),
                _optional_path(self._diagnostics().resolved.ffprobe),
            )
        finally:
            source.unlink(missing_ok=True)
        return manifest.model_dump(by_alias=True)

    def confirm_visual_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ConfirmVisualParams.model_validate(raw)
        return self.projects.confirm_visual_replacement(
            params.project_id, params.asset_id, Path(params.source_path)
        ).model_dump(by_alias=True)

    def update_visual_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = UpdateItemParams.model_validate(raw)
        if set(params.changes) != {"enabled"}:
            raise StudioError(
                "INVALID_REQUEST", "Only enabled can be changed on a visual replacement."
            )
        return self.projects.update_visual_replacement(
            params.project_id,
            params.item_id,
            enabled=bool(params.changes["enabled"]),
        ).model_dump(by_alias=True)

    def remove_visual_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = RemoveItemParams.model_validate(raw)
        return self.projects.remove_visual_replacement(
            params.project_id, params.item_id
        ).model_dump(by_alias=True)

    def update_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = UpdateItemParams.model_validate(raw)
        changes: dict[str, Any] = {}
        if "enabled" in params.changes:
            changes["enabled"] = bool(params.changes["enabled"])
        if "processing" in params.changes:
            changes["processing"] = ProcessingSettings.model_validate(
                params.changes["processing"]
            ).model_dump()
        if "looping" in params.changes:
            changes["looping"] = LoopSettings.model_validate(
                params.changes["looping"]
            ).model_dump()
        return self.projects.update_replacement(
            params.project_id, params.item_id, changes
        ).model_dump(by_alias=True)

    def replace_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ReplaceSourceParams.model_validate(raw)
        diagnostics = self._diagnostics()
        ffprobe = diagnostics.resolved.ffprobe
        return self.projects.replace_source(
            params.project_id,
            params.item_id,
            Path(params.source_path),
            _optional_path(ffprobe),
        ).model_dump(by_alias=True)

    def duplicate_settings(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = DuplicateSettingsParams.model_validate(raw)
        return self.projects.duplicate_settings(
            params.project_id,
            params.source_item_id,
            params.target_item_id,
        ).model_dump(by_alias=True)

    def remove_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = RemoveItemParams.model_validate(raw)
        return self.projects.remove_replacement(
            params.project_id, params.item_id
        ).model_dump(by_alias=True)

    def reorder_replacement(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ReorderItemParams.model_validate(raw)
        return self.projects.reorder_replacement(
            params.project_id, params.item_id, params.new_index
        ).model_dump(by_alias=True)

    def remap_target(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = RemapItemParams.model_validate(raw)
        return self.projects.remap_target(
            params.project_id, params.item_id, params.asset_id
        ).model_dump(by_alias=True)

    def project_conflicts(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = ProjectIdParams.model_validate(raw)
        manifest = self.projects.load(params.project_id)
        return [
            conflict.model_dump(by_alias=True)
            for conflict in detect_conflicts(
                manifest.target_assets + manifest.visual_assets
            )
        ]

    def project_compatibility(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ProjectIdParams.model_validate(raw)
        manifest = self.projects.load(params.project_id)
        rows: list[dict[str, Any]] = []
        counts = {"exactMatch": 0, "changedAsset": 0, "missing": 0}
        for item in manifest.target_assets:
            current = self.database.get_asset_by_path(item.target.internal_path)
            if current:
                exact = bool(
                    item.target.asset_fingerprint
                    and current.asset_fingerprint == item.target.asset_fingerprint
                )
                if not item.target.asset_fingerprint:
                    exact = current.archive_fingerprint == item.target.archive_fingerprint
                status = "changedAsset"
                if exact:
                    status = "exactMatch"
                # The path still exists, so the fix is to re-point the item at
                # whatever now lives there. Offering it as a candidate lets the
                # UI repair changed and relocated assets through one code path.
                candidates: list[dict[str, Any]] = []
                if not exact:
                    candidates.append(
                        {"asset": current.model_dump(by_alias=True), "score": 1.0}
                    )
            else:
                status = "missing"
                scored = sorted(
                    (
                        (relocation_score(item.target, candidate), candidate)
                        for candidate in self.database.get_assets_by_filename(
                            item.target.filename
                        )
                        if candidate.internal_path.casefold()
                        != item.target.internal_path.casefold()
                    ),
                    key=lambda value: value[0],
                    reverse=True,
                )
                candidates = [
                    {
                        "asset": candidate.model_dump(by_alias=True),
                        "score": score,
                    }
                    for score, candidate in scored[:3]
                    if score > 0
                ]
            counts[status] += 1
            rows.append(
                {
                    "itemId": item.id,
                    "targetPath": item.target.internal_path,
                    "status": status,
                    "candidates": candidates,
                }
            )
        return {
            "projectId": manifest.id,
            "projectFingerprint": manifest.game_fingerprint,
            "counts": counts,
            "rows": rows,
            "checked": len(rows),
        }

    def index_sounds(self, raw: dict[str, Any]) -> dict[str, Any]:
        ParamsModel.model_validate(raw)
        diagnostics = self._diagnostics()
        archive = diagnostics.resolved.deadlock_archive
        if not archive:
            raise capability_error("A valid Deadlock pak01_dir.vpk is required for indexing.")
        result = index_archive(self.database, Path(archive))
        return result.model_dump(by_alias=True)

    def index_history(self, raw: dict[str, Any]) -> list[dict[str, object]]:
        params = HistoryParams.model_validate(raw)
        return self.database.index_history(params.limit)

    def search_sounds(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = SearchParams.model_validate(raw)
        return [
            asset.model_dump(by_alias=True)
            for asset in self.database.search_assets(
                params.query, params.category, params.limit, scope=params.scope
            )
        ]

    def sound_folders(self, raw: dict[str, Any]) -> list[dict[str, object]]:
        params = FolderListParams.model_validate(raw)
        return self.database.list_sound_folders(params.category, scope=params.scope)

    def browse_sounds(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = BrowseFolderParams.model_validate(raw)
        return [
            asset.model_dump(by_alias=True)
            for asset in self.database.sound_assets_in_folder(
                params.folder, params.category, scope=params.scope
            )
        ]

    def visual_folders(self, raw: dict[str, Any]) -> list[dict[str, object]]:
        params = VisualFolderListParams.model_validate(raw)
        return self.database.list_visual_folders(params.kind)

    def browse_visuals(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = BrowseVisualFolderParams.model_validate(raw)
        return [
            asset.model_dump(by_alias=True)
            for asset in self.database.visual_assets_in_folder(params.folder, params.kind)
        ]

    def search_visuals(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = VisualSearchParams.model_validate(raw)
        return [
            asset.model_dump(by_alias=True)
            for asset in self.database.search_visual_assets(
                params.query, params.kind, params.limit
            )
        ]

    def inspect_visual_source(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = VisualInspectParams.model_validate(raw)
        return inspect_visual_source(
            self.paths, Path(params.path), params.kind
        ).model_dump(by_alias=True)

    def preview_visual(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = AssetParams.model_validate(raw)
        asset = self.database.get_visual_asset(params.asset_id)
        if not asset:
            raise StudioError(
                "ASSET_NOT_FOUND", "Visual resource is not in the current index."
            )
        diagnostics = self._diagnostics()
        cli = diagnostics.resolved.source2_viewer_cli
        exported = export_visual_preview(
            _optional_path(cli),
            self.paths,
            asset,
        )
        metadata = inspect_visual_source(self.paths, exported, asset.kind)
        return metadata.model_dump(by_alias=True)

    def preview_sound(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = AssetParams.model_validate(raw)
        asset = self.database.get_asset(params.asset_id)
        if not asset:
            raise StudioError("ASSET_NOT_FOUND", "Sound is not in the current index.")
        diagnostics = self._diagnostics()
        cli = diagnostics.resolved.source2_viewer_cli
        preview = export_sound_preview(
            _optional_path(cli),
            self.paths,
            asset,
        )
        ffprobe = diagnostics.resolved.ffprobe
        metadata = inspect_audio(preview, _optional_path(ffprobe))
        metadata.preview_path = str(preview)
        return metadata.model_dump(by_alias=True)

    def inspect_audio(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = AudioInspectParams.model_validate(raw)
        diagnostics = self._diagnostics()
        ffprobe = diagnostics.resolved.ffprobe
        return inspect_audio(
            Path(params.path),
            _optional_path(ffprobe),
        ).model_dump(by_alias=True)

    def preview_processed(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = PreviewProcessedParams.model_validate(raw)
        diagnostics = self._diagnostics()
        resolved = diagnostics.resolved
        output = self.paths.cache / "replacement-previews" / f"{uuid.uuid4()}.wav"
        return process_audio(
            Path(params.path),
            output,
            params.processing,
            _optional_path(resolved.ffmpeg),
            _optional_path(resolved.ffprobe),
        ).model_dump(by_alias=True)

    def preview_csv(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = MappingFileParams.model_validate(raw)
        return [
            row.model_dump(by_alias=True)
            for row in preview_mapping_file(self.database, Path(params.path))
        ]

    def preview_folder(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        params = MappingFileParams.model_validate(raw)
        return [
            row.model_dump(by_alias=True)
            for row in preview_folder(self.database, Path(params.path))
        ]

    def confirm_batch(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = BatchConfirmParams.model_validate(raw)
        resolved = (
            resolve_mapping_file(self.database, Path(params.path))
            if params.kind == "file"
            else resolve_folder(self.database, Path(params.path))
        )
        selected = set(params.row_numbers)
        added = 0
        added_item_ids: list[str] = []
        failed: list[dict[str, Any]] = []
        for row, source in resolved:
            if row.row_number not in selected:
                continue
            if row.status != "matched" or not row.asset_id or not source:
                failed.append(
                    {
                        "rowNumber": row.row_number,
                        "message": "The row is no longer a valid unambiguous match.",
                    }
                )
                continue
            try:
                override = params.row_settings.get(row.row_number)
                processing = (
                    override.processing
                    if override
                    else row.processing
                    if row.uses_row_settings
                    else params.processing
                )
                looping = (
                    override.looping
                    if override
                    else row.looping
                    if row.uses_row_settings
                    else params.looping
                )
                project = self.projects.confirm_replacement(
                    params.project_id,
                    row.asset_id,
                    source,
                    processing,
                    looping,
                )
                added += 1
                added_item_ids.append(project.target_assets[-1].id)
            except Exception as error:
                failed.append(
                    {"rowNumber": row.row_number, "message": str(error)}
                )
        rollback_token: str | None = None
        project = self.projects.load(params.project_id)
        if added_item_ids:
            project, rollback_token = self.projects.record_batch_import(
                params.project_id, added_item_ids
            )
        return {
            "project": project.model_dump(by_alias=True),
            "added": added,
            "failed": failed,
            "rollbackToken": rollback_token,
        }

    def rollback_batch(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = BatchRollbackParams.model_validate(raw)
        project, removed = self.projects.rollback_batch_import(
            params.project_id, params.transaction_id
        )
        return {
            "project": project.model_dump(by_alias=True),
            "removed": removed,
        }

    def start_build(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = BuildParams.model_validate(raw)
        if params.job_id in self.jobs:
            raise StudioError("JOB_EXISTS", "A build with this job ID already exists.")
        token = CancellationToken()
        self.jobs[params.job_id] = token
        try:
            diagnostics = self._diagnostics()
            result = BuildJob(
                self.paths, self.projects, diagnostics, self.emit_event
            ).run(
                params.project_id,
                params.job_id,
                token,
                retry_failed_only=params.retry_failed_only,
            )
            return result.model_dump(by_alias=True)
        finally:
            self.jobs.pop(params.job_id, None)

    def cancel_build(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = CancelParams.model_validate(raw)
        token = self.jobs.get(params.job_id)
        if token:
            token.cancel()
        return {"cancelled": bool(token)}

    def validate_export(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = ProjectIdParams.model_validate(raw)
        manifest = self.projects.load(params.project_id)
        if not manifest.build_history or not manifest.build_history[-1].output_relative_path:
            raise StudioError("EXPORT_NOT_FOUND", "This project has no completed export.")
        vpk = self.paths.root / manifest.build_history[-1].output_relative_path
        entries = list_vpk(vpk)
        expected = {
            item.target.compiled_path.casefold()
            for item in manifest.target_assets + manifest.visual_assets
            if item.enabled
        }
        actual = {entry.path.casefold() for entry in entries}
        return {
            "valid": actual == expected and len(entries) == len(expected),
            "entryCount": len(entries),
            "missing": sorted(expected - actual),
            "unexpected": sorted(actual - expected),
        }

    def create_zip(self, raw: dict[str, Any]) -> dict[str, str]:
        params = CreateZipParams.model_validate(raw)
        return {
            "path": create_zip(
                self.paths,
                self.projects,
                params.project_id,
                params.version,
            )
        }

    def create_compatibility_copy(self, raw: dict[str, Any]) -> dict[str, str]:
        params = CreateZipParams.model_validate(raw)
        return {
            "path": create_compatibility_copy(
                self.paths,
                self.projects,
                params.project_id,
                params.version,
            )
        }

    def inspect_packages(self, raw: dict[str, Any]) -> list[dict[str, object]]:
        params = PackagePathsParams.model_validate(raw)
        return inspect_packages([Path(value) for value in params.paths])

    def combine_packages(self, raw: dict[str, Any]) -> dict[str, object]:
        params = CombinePackagesParams.model_validate(raw)
        return combine_packages(
            [Path(value) for value in params.paths],
            Path(params.output_path),
            self.emit_event,
            [
                RenameRule(package=rule.package, source=rule.source, target=rule.target)
                for rule in params.renames
            ],
        )

    def extract_package(self, raw: dict[str, Any]) -> dict[str, object]:
        """Write a new package holding only the chosen files from another."""
        params = ExtractPackageParams.model_validate(raw)
        return extract_package(
            Path(params.path),
            Path(params.output_path),
            params.internal_paths,
            self.emit_event,
        )

    def inspect_mod(self, raw: dict[str, Any]) -> dict[str, object]:
        """Describe an existing mod package against the indexed game files."""
        params = ModPackageParams.model_validate(raw)
        report = inspect_mod_package(Path(params.path), self.database)
        payload = report.as_payload()
        # Without an index every path looks orphaned, which would read as "this
        # mod is broken". Say so explicitly instead.
        payload["indexed"] = self.database.count_assets() > 0
        return payload

    def compare_mods(self, raw: dict[str, Any]) -> dict[str, object]:
        """Report what two mod packages have in common."""
        params = CompareModsParams.model_validate(raw)
        return compare_mod_packages([Path(value) for value in params.paths]).as_payload()

    def preview_mod_sound(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Decompile one sound out of an installed mod so it can be played.

        The same export the game archive uses, pointed at the mod's own .vpk.
        Cache validity is keyed on the package's modification time, so
        reinstalling a mod produces a fresh preview rather than the old one.
        """
        params = ModSoundPreviewParams.model_validate(raw)
        package = Path(params.path)
        internal = normalize_internal_path(params.internal_path)
        if not internal.casefold().endswith(".vsnd_c"):
            raise validation_error(
                "Only compiled sounds can be previewed", path=internal
            )
        if not package.is_file():
            raise validation_error("Mod package does not exist", path=str(package))

        diagnostics = self._diagnostics()
        preview = export_package_sound(
            _optional_path(diagnostics.resolved.source2_viewer_cli),
            self.paths,
            package,
            internal,
            cache_root=self.paths.cache
            / "mod-previews"
            / _package_cache_key(package)
            / _path_cache_key(internal),
        )
        metadata = inspect_audio(preview, _optional_path(diagnostics.resolved.ffprobe))
        metadata.preview_path = str(preview)
        return metadata.model_dump(by_alias=True)

    def backup_packages(self, raw: dict[str, Any]) -> dict[str, object]:
        """Move packages out of the addons folder into the backup folder."""
        params = BackupPackagesParams.model_validate(raw)
        return move_packages_to_backup(
            [Path(value) for value in params.paths], self.paths.backups
        ).as_payload()

    def addon_conflicts(self, raw: dict[str, Any]) -> dict[str, object]:
        """Report installed mods that claim the same game path."""
        params = AddonConflictParams.model_validate(raw)
        directory = (
            Path(params.directory) if params.directory else self._default_addons_directory()
        )
        return find_addon_conflicts(directory).as_payload()

    def _default_addons_directory(self) -> Path:
        """``<deadlock>/game/citadel/addons``, where Source 2 loads mods from."""
        deadlock_root = self._diagnostics().resolved.deadlock_root
        if not deadlock_root:
            raise capability_error(
                "Choose your Deadlock installation in Diagnostics before checking "
                "installed mods."
            )
        return Path(deadlock_root) / "game" / "citadel" / "addons"
