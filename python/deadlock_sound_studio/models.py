from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class StudioModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        serialize_by_alias=True,
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class CheckStatus(StrEnum):
    FOUND = "found"
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED_VERSION = "unsupportedVersion"
    CAPABILITY_UNAVAILABLE = "capabilityUnavailable"


class PortablePaths(StudioModel):
    root: str
    tools: str
    data: str
    cache: str
    projects: str
    exports: str
    logs: str
    backups: str


class Settings(StudioModel):
    csdk_root_override: str | None = None
    source2_viewer_override: str | None = None
    source2_viewer_cli_override: str | None = None
    ffmpeg_override: str | None = None
    ffprobe_override: str | None = None
    deadlock_root_override: str | None = None
    vpk_packager_override: str | None = None
    setup_completed: bool = False
    tutorial_completed: bool = False


class ToolCheck(StudioModel):
    id: str
    label: str
    status: CheckStatus
    path: str | None = None
    version: str | None = None
    detail: str


class ResolvedTools(StudioModel):
    csdk_root: str | None = None
    csdk_config: str | None = None
    resource_compiler: str | None = None
    vpk_packager: str | None = None
    source2_viewer: str | None = None
    source2_viewer_cli: str | None = None
    ffmpeg: str | None = None
    ffprobe: str | None = None
    deadlock_root: str | None = None
    deadlock_archive: str | None = None
    lame_encoder: str | None = None


class DiagnosticReport(StudioModel):
    checked_at: str
    portable_paths: PortablePaths
    checks: list[ToolCheck]
    resolved: ResolvedTools
    can_index: bool
    can_preview_original: bool
    can_process_audio: bool
    can_compile: bool
    can_package_headlessly: bool
    can_build: bool


class SoundCategory(StrEnum):
    HERO = "hero"
    VOICE = "voice"
    ABILITY = "ability"
    WEAPON = "weapon"
    UI = "ui"
    MUSIC = "music"
    AMBIENT = "ambient"
    ANNOUNCER = "announcer"
    OBJECTIVE = "objective"
    ITEM = "item"
    GENERAL = "general"
    UNCLASSIFIED = "unclassified"


class SoundAsset(StudioModel):
    id: str
    internal_path: str
    compiled_path: str
    filename: str
    extension: str
    category: SoundCategory
    hero_id: str | None = None
    hero_name: str | None = None
    ability_name: str | None = None
    sound_event: str | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    source_archive: str
    archive_fingerprint: str
    asset_fingerprint: str | None = None
    last_indexed_at: str


class VisualResourceKind(StrEnum):
    TEXTURE = "texture"
    MATERIAL = "material"


class VisualResourceAsset(StudioModel):
    id: str
    internal_path: str
    compiled_path: str
    filename: str
    kind: VisualResourceKind
    source_archive: str
    archive_fingerprint: str
    asset_fingerprint: str | None = None
    stored_size: int = 0
    last_indexed_at: str


class VisualSourceMetadata(StudioModel):
    format: str
    width: int | None = None
    height: int | None = None
    mode: str | None = None
    has_alpha: bool | None = None
    color_space: str | None = None
    probable_normal_map: bool = False
    preview_path: str | None = None
    text_preview: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AudioMetadata(StudioModel):
    duration_ms: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None
    peak_db: float | None = None
    integrated_loudness: float | None = None
    preview_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ProcessingSettings(StudioModel):
    trim_start_seconds: float = Field(default=0, ge=0)
    trim_end_seconds: float | None = Field(default=None, gt=0)
    auto_trim_silence: bool = False
    fade_in_seconds: float = Field(default=0, ge=0)
    fade_out_seconds: float = Field(default=0, ge=0)
    gain_db: float = Field(default=0, ge=-60, le=30)
    normalize: bool = True
    target_loudness_lufs: float = Field(default=-16, ge=-30, le=-5)
    peak_headroom_db: float = Field(default=-1, ge=-12, le=0)
    channels: int | None = Field(default=None, ge=1, le=2)
    sample_rate: int | None = Field(default=44_100, ge=8_000, le=192_000)


class LoopSettings(StudioModel):
    enabled: bool = False
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    start_sample: int | None = Field(default=None, ge=0)
    end_sample: int | None = Field(default=None, gt=0)


class ItemStatus(StrEnum):
    CONFIRMED = "confirmed"
    PROCESSING_AUDIO = "processingAudio"
    GENERATING_SOURCE = "generatingSource"
    COMPILING = "compiling"
    VERIFYING = "verifying"
    READY_FOR_PACKAGING = "readyForPackaging"
    PACKAGED = "packaged"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReplacementItem(StudioModel):
    id: str
    order: int
    enabled: bool = True
    target: SoundAsset
    source_filename: str
    source_relative_path: str
    processed_relative_path: str | None = None
    source_metadata: AudioMetadata = Field(default_factory=AudioMetadata)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    looping: LoopSettings = Field(default_factory=LoopSettings)
    status: ItemStatus = ItemStatus.CONFIRMED
    validation_messages: list[str] = Field(default_factory=list)
    last_error: str | None = None


class VisualReplacementItem(StudioModel):
    id: str
    order: int
    enabled: bool = True
    target: VisualResourceAsset
    source_filename: str
    source_relative_path: str
    source_metadata: VisualSourceMetadata
    status: ItemStatus = ItemStatus.CONFIRMED
    validation_messages: list[str] = Field(default_factory=list)
    last_error: str | None = None


class PackageMode(StrEnum):
    SINGLE_VPK = "single-vpk"
    SPLIT_BY_HERO = "split-by-hero"
    SPLIT_BY_CATEGORY = "split-by-category"
    CUSTOM_GROUPS = "custom-groups"


class BuildHistoryEntry(StudioModel):
    version: str
    started_at: str
    finished_at: str
    success: bool
    output_relative_path: str | None = None
    checksum: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ExportHistoryEntry(StudioModel):
    version: str
    exported_at: str
    relative_path: str


class BatchImportTransaction(StudioModel):
    id: str
    created_at: str
    item_ids: list[str]
    rolled_back_at: str | None = None


class ProjectManifest(StudioModel):
    schema_version: int = 2
    id: str
    name: str
    display_name: str
    description: str = ""
    author: str = ""
    created_at: str
    updated_at: str
    game_fingerprint: str = ""
    package_mode: PackageMode = PackageMode.SINGLE_VPK
    target_assets: list[ReplacementItem] = Field(default_factory=list)
    visual_assets: list[VisualReplacementItem] = Field(default_factory=list)
    build_settings: dict[str, Any] = Field(default_factory=dict)
    build_history: list[BuildHistoryEntry] = Field(default_factory=list)
    export_history: list[ExportHistoryEntry] = Field(default_factory=list)
    batch_import_history: list[BatchImportTransaction] = Field(default_factory=list)


class ProjectSummary(StudioModel):
    id: str
    name: str
    display_name: str
    updated_at: str
    replacement_count: int
    enabled_count: int
    last_build_success: bool | None = None
    # Lets the UI spot a project built against a superseded game archive without
    # running a full compatibility pass over every project.
    game_fingerprint: str = ""


class ConflictKind(StrEnum):
    DUPLICATE_TARGET = "duplicateTarget"
    CASE_INSENSITIVE_COLLISION = "caseInsensitiveCollision"
    COMPILED_TARGET_COLLISION = "compiledTargetCollision"
    INVALID_TARGET = "invalidTarget"


class Conflict(StudioModel):
    kind: ConflictKind
    item_ids: list[str]
    target_path: str
    message: str


class ProcessRecord(StudioModel):
    executable_path: str
    executable_version: str | None = None
    sanitized_arguments: list[str]
    started_at: str
    duration_ms: int
    exit_code: int | None = None
    stdout: str
    stderr: str
    produced_files: list[str] = Field(default_factory=list)


class ItemBuildResult(StudioModel):
    item_id: str
    target_path: str
    status: ItemStatus
    source_relative_path: str
    compiled_relative_path: str | None = None
    error: str | None = None
    process_records: list[ProcessRecord] = Field(default_factory=list)
    reused_compiled_output: bool = False


class BuildResult(StudioModel):
    success: bool
    version: str
    stage: str
    message: str
    item_results: list[ItemBuildResult] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    vpk_path: str | None = None
    export_directory: str | None = None
    checksum: str | None = None
    report_path: str | None = None
    item_log_path: str | None = None
    guided_fallback_directory: str | None = None
    warnings: list[str] = Field(default_factory=list)


class IndexResult(StudioModel):
    indexed: int
    visual_indexed: int = 0
    archive_fingerprint: str
    warnings: list[str] = Field(default_factory=list)
    duration_ms: int


class BatchPreviewRow(StudioModel):
    row_number: int
    original_path: str
    replacement_file: str
    asset_id: str | None = None
    status: str
    messages: list[str] = Field(default_factory=list)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    looping: LoopSettings = Field(default_factory=LoopSettings)
    uses_row_settings: bool = False
