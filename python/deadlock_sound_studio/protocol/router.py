from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..audio import inspect_audio, process_audio
from ..batch import (
    preview_folder,
    preview_mapping_file,
    resolve_folder,
    resolve_mapping_file,
)
from ..build import BuildJob, create_compatibility_copy, create_zip
from ..database import Database
from ..diagnostics import run_diagnostics
from ..errors import StudioError, capability_error
from ..external.process import CancellationToken
from ..indexing import index_archive
from ..models import (
    LoopSettings,
    ProcessingSettings,
    Settings,
    VisualResourceKind,
)
from ..packages import combine_packages, inspect_packages
from ..paths import AppPaths
from ..projects import ProjectService, detect_conflicts
from ..requirements import install_missing_requirements
from ..settings import load_settings, save_settings
from ..source_viewer import export_sound_preview, export_visual_preview
from ..updates import relocation_score
from ..visuals import inspect_visual_source
from ..vpk import list_vpk


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


class CombinePackagesParams(PackagePathsParams):
    output_path: str = Field(alias="outputPath")


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
            "sounds.preview": self.preview_sound,
            "visuals.search": self.search_visuals,
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
        return run_diagnostics(
            self.paths,
            load_settings(self.paths),
            self.emit_event if emit_progress else None,
        )

    def bootstrap(self, raw: dict[str, Any]) -> dict[str, Any]:
        ParamsModel.model_validate(raw)
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
            Path(ffprobe) if ffprobe else None,
        ).model_dump(by_alias=True)

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
            Path(ffprobe) if ffprobe else None,
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
                status = "exactMatch" if exact else "changedAsset"
                # The path still exists, so the fix is to re-point the item at
                # whatever now lives there. Offering it as a candidate lets the
                # UI repair changed and relocated assets through one code path.
                candidates: list[dict[str, Any]] = (
                    []
                    if exact
                    else [{"asset": current.model_dump(by_alias=True), "score": 1.0}]
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
            Path(cli) if cli else None,
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
            Path(cli) if cli else None,
            self.paths,
            asset,
        )
        ffprobe = diagnostics.resolved.ffprobe
        metadata = inspect_audio(preview, Path(ffprobe) if ffprobe else None)
        metadata.preview_path = str(preview)
        return metadata.model_dump(by_alias=True)

    def inspect_audio(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = AudioInspectParams.model_validate(raw)
        diagnostics = self._diagnostics()
        ffprobe = diagnostics.resolved.ffprobe
        return inspect_audio(
            Path(params.path),
            Path(ffprobe) if ffprobe else None,
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
            Path(resolved.ffmpeg) if resolved.ffmpeg else None,
            Path(resolved.ffprobe) if resolved.ffprobe else None,
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
        )
