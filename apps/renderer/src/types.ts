export type CheckStatus =
  | "found"
  | "missing"
  | "invalid"
  | "unsupportedVersion"
  | "capabilityUnavailable";

export type Settings = {
  csdkRootOverride: string | null;
  source2ViewerOverride: string | null;
  source2ViewerCliOverride: string | null;
  ffmpegOverride: string | null;
  ffprobeOverride: string | null;
  deadlockRootOverride: string | null;
  vpkPackagerOverride: string | null;
  setupCompleted: boolean;
  tutorialCompleted: boolean;
};

export type UpdateInfo = {
  currentVersion: string;
  latestVersion: string | null;
  available: boolean;
  releaseName: string | null;
  releaseNotes: string;
  publishedAt: string | null;
  releaseUrl: string;
  assetName: string | null;
  assetUrl: string | null;
  assetSize: number | null;
  assetDigest: string | null;
  canInstall: boolean;
  status: "available" | "current" | "noReleases";
};

export type UpdateProgress = {
  event: "update.progress";
  stage: string;
  message: string;
  downloadedBytes: number;
  totalBytes: number;
};

export type AppInfo = {
  name: string;
  version: string;
  platform: string;
  architecture: string;
  electronVersion: string;
  chromiumVersion: string;
  portable: boolean;
  dataRoot: string;
  repositoryUrl: string;
};

export type ToolCheck = {
  id: string;
  label: string;
  status: CheckStatus;
  path: string | null;
  version: string | null;
  detail: string;
};

export type Diagnostics = {
  checkedAt: string;
  portablePaths: Record<string, string>;
  checks: ToolCheck[];
  resolved: Record<string, string | null>;
  canIndex: boolean;
  canPreviewOriginal: boolean;
  canProcessAudio: boolean;
  canCompile: boolean;
  canPackageHeadlessly: boolean;
  canBuild: boolean;
};

export type SoundCategory =
  | "hero"
  | "voice"
  | "ability"
  | "weapon"
  | "ui"
  | "music"
  | "ambient"
  | "announcer"
  | "objective"
  | "item"
  | "general"
  | "unclassified";

export type SoundAsset = {
  id: string;
  internalPath: string;
  compiledPath: string;
  filename: string;
  extension: string;
  category: SoundCategory;
  heroId: string | null;
  heroName: string | null;
  abilityName: string | null;
  soundEvent: string | null;
  durationMs: number | null;
  sampleRate: number | null;
  channels: number | null;
  sourceArchive: string;
  archiveFingerprint: string;
  assetFingerprint: string | null;
  lastIndexedAt: string;
};

export type VisualResourceKind = "texture" | "material";

export type VisualResourceAsset = {
  id: string;
  internalPath: string;
  compiledPath: string;
  filename: string;
  kind: VisualResourceKind;
  sourceArchive: string;
  archiveFingerprint: string;
  assetFingerprint: string | null;
  storedSize: number;
  lastIndexedAt: string;
};

export type VisualSourceMetadata = {
  format: string;
  width: number | null;
  height: number | null;
  mode: string | null;
  hasAlpha: boolean | null;
  colorSpace: string | null;
  probableNormalMap: boolean;
  previewPath: string | null;
  textPreview: string | null;
  dependencies: string[];
  warnings: string[];
};

export type VisualReplacementItem = {
  id: string;
  order: number;
  enabled: boolean;
  target: VisualResourceAsset;
  sourceFilename: string;
  sourceRelativePath: string;
  sourceMetadata: VisualSourceMetadata;
  status: string;
  validationMessages: string[];
  lastError: string | null;
};

export type AudioMetadata = {
  durationMs: number | null;
  sampleRate: number | null;
  channels: number | null;
  codec: string | null;
  peakDb: number | null;
  integratedLoudness: number | null;
  previewPath: string | null;
  warnings: string[];
};

export type ProcessingSettings = {
  trimStartSeconds: number;
  trimEndSeconds: number | null;
  autoTrimSilence: boolean;
  fadeInSeconds: number;
  fadeOutSeconds: number;
  gainDb: number;
  normalize: boolean;
  targetLoudnessLufs: number;
  peakHeadroomDb: number;
  channels: number | null;
  sampleRate: number | null;
};

export type LoopSettings = {
  enabled: boolean;
  startSeconds: number | null;
  endSeconds: number | null;
  startSample: number | null;
  endSample: number | null;
};

export type ReplacementItem = {
  id: string;
  order: number;
  enabled: boolean;
  target: SoundAsset;
  sourceFilename: string;
  sourceRelativePath: string;
  processedRelativePath: string | null;
  sourceMetadata: AudioMetadata;
  processing: ProcessingSettings;
  looping: LoopSettings;
  status: string;
  validationMessages: string[];
  lastError: string | null;
};

export type ProjectManifest = {
  schemaVersion: number;
  id: string;
  name: string;
  displayName: string;
  description: string;
  author: string;
  createdAt: string;
  updatedAt: string;
  gameFingerprint: string;
  packageMode: "single-vpk" | "split-by-hero" | "split-by-category" | "custom-groups";
  targetAssets: ReplacementItem[];
  visualAssets: VisualReplacementItem[];
  buildHistory: Array<{
    version: string;
    startedAt: string;
    finishedAt: string;
    success: boolean;
    outputRelativePath: string | null;
    checksum: string | null;
    warnings: string[];
  }>;
  exportHistory: unknown[];
  batchImportHistory: Array<{
    id: string;
    createdAt: string;
    itemIds: string[];
    rolledBackAt: string | null;
  }>;
};

export type ProjectSummary = {
  id: string;
  name: string;
  displayName: string;
  updatedAt: string;
  replacementCount: number;
  enabledCount: number;
  lastBuildSuccess: boolean | null;
  /** Archive the project was last built against; compare with Bootstrap.gameFingerprint. */
  gameFingerprint: string;
};

export type Bootstrap = {
  paths: Record<string, string>;
  settings: Settings;
  diagnostics: Diagnostics;
  projects: ProjectSummary[];
  soundCount: number;
  visualCount: number;
  /** Fingerprint of the most recently indexed game archive ("" if never indexed). */
  gameFingerprint: string;
  autoIndex: {
    attempted: boolean;
    indexed: number;
    visualIndexed?: number;
    warning: string | null;
  };
};

export type BuildProgress = {
  event: "build.progress";
  jobId: string;
  stage: string;
  completed: number;
  total: number;
  currentItem: string | null;
};

export type DiagnosticProgress = {
  event: "diagnostics.progress";
  stage: string;
  completed: number;
  total: number;
  message: string;
};

export type RequirementProgress = {
  event: "requirements.progress";
  stage: string;
  completed: number;
  total: number;
  message: string;
  downloadedBytes: number;
  totalBytes: number;
};

export type RequirementInstallResult = {
  diagnostics: Diagnostics;
  settings: Settings;
  installed: string[];
  skipped: string[];
};

export type PackageEntry = {
  path: string;
  sizeBytes: number;
  crc32: string;
  archiveIndex: number;
};

export type PackageInventory = {
  path: string;
  filename: string;
  sizeBytes: number;
  entryCount: number;
  entries: PackageEntry[];
};

export type PackageProgress = {
  event: "packages.progress";
  stage: string;
  completed: number;
  total: number;
  message: string;
};

export type PackageCombineResult = {
  outputPath: string;
  entryCount: number;
  inputCount: number;
  conflictCount: number;
  conflicts: Array<{
    path: string;
    replacedPackage: string;
    winnerPackage: string;
  }>;
  sizeBytes: number;
};

export type ProcessRecord = {
  executablePath: string;
  executableVersion: string | null;
  sanitizedArguments: string[];
  startedAt: string;
  durationMs: number;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  producedFiles: string[];
};

export type ItemBuildResult = {
  itemId: string;
  targetPath: string;
  status: string;
  sourceRelativePath: string;
  compiledRelativePath: string | null;
  error: string | null;
  processRecords: ProcessRecord[];
  reusedCompiledOutput: boolean;
};

export type BuildResult = {
  success: boolean;
  version: string;
  stage: string;
  message: string;
  itemResults: ItemBuildResult[];
  conflicts: Array<{ kind: string; itemIds: string[]; targetPath: string; message: string }>;
  vpkPath: string | null;
  exportDirectory: string | null;
  itemLogPath: string | null;
  guidedFallbackDirectory: string | null;
  warnings: string[];
};

export type BatchRow = {
  rowNumber: number;
  originalPath: string;
  replacementFile: string;
  assetId: string | null;
  status: string;
  messages: string[];
  processing: ProcessingSettings;
  looping: LoopSettings;
  usesRowSettings: boolean;
};

export type BatchConfirmResult = {
  project: ProjectManifest;
  added: number;
  failed: Array<{ rowNumber: number; message: string }>;
  rollbackToken: string | null;
};

export type CompatibilityReport = {
  projectId: string;
  projectFingerprint: string;
  checked: number;
  counts: {
    exactMatch: number;
    changedAsset: number;
    missing: number;
  };
  rows: Array<{
    itemId: string;
    targetPath: string;
    status: "exactMatch" | "changedAsset" | "missing";
    candidates: Array<{ asset: SoundAsset; score: number }>;
  }>;
};

export type IndexHistoryEntry = {
  archiveFingerprint: string;
  indexedAt: string;
  assetCount: number;
  priorFingerprint: string | null;
};

export const DEFAULT_PROCESSING: ProcessingSettings = {
  trimStartSeconds: 0,
  trimEndSeconds: null,
  autoTrimSilence: false,
  fadeInSeconds: 0,
  fadeOutSeconds: 0,
  gainDb: 0,
  normalize: true,
  targetLoudnessLufs: -16,
  peakHeadroomDb: -1,
  channels: null,
  sampleRate: 44100
};

export const DEFAULT_LOOP: LoopSettings = {
  enabled: false,
  startSeconds: null,
  endSeconds: null,
  startSample: null,
  endSample: null
};

/**
 * Reading mod packages that already exist, rather than building new ones.
 * Backend: python/deadlock_sound_studio/mods/
 */

/** One file inside a downloaded mod, described against the indexed game archive. */
export type ModEntry = {
  path: string;
  /** "sound" | "texture" | "material" | "other" — see KIND_BY_EXTENSION in inspection.py. */
  kind: string;
  sizeBytes: number;
  /**
   * "matched"   - the game ships this path, so the replacement will apply.
   * "missing"   - an indexed kind, but the path is not in the catalog.
   * "unchecked" - a kind this app does not index (Panorama UI, models), so
   *               nothing can be said either way.
   */
  status: "matched" | "missing" | "unchecked";
  heroName: string | null;
};

/** Result of `mods.inspect`. */
export type ModPackageReport = {
  path: string;
  filename: string;
  sizeBytes: number;
  entryCount: number;
  matchedCount: number;
  missingCount: number;
  uncheckedCount: number;
  /** Entry count per kind, e.g. { sound: 12, texture: 3 }. */
  countsByKind: Record<string, number>;
  heroes: string[];
  /** "abrams_voice_pack.vpk" -> "Abrams Voice Pack"; pass to projects.create. */
  suggestedProjectName: string;
  /** False when the archive has never been indexed, so every entry looks orphaned. */
  indexed: boolean;
  entries: ModEntry[];
};

/** One installed mod file found in the addons folder. */
export type InstalledPackage = {
  path: string;
  filename: string;
  entryCount: number;
  sizeBytes: number;
  /** Deadlock Mod Manager's id for the owning mod, or the filename if unmanaged. */
  modId: string;
  /** The mod's display name from the manager's catalogue, when resolvable. */
  modName: string | null;
  /** Disabled mods stay on disk but are never loaded, so they cannot conflict. */
  enabled: boolean;
  /** Set when the package could not be read; it is reported rather than skipped. */
  error: string | null;
};

/** One game path claimed by more than one installed mod. */
export type AddonConflict = {
  path: string;
  filenames: string[];
  modIds: string[];
};

/** Two mods that overlap, and by how much. */
export type ModConflict = {
  modIds: string[];
  filenames: string[];
  pathCount: number;
  examplePaths: string[];
};

/**
 * Result of `mods.addonConflicts`. Reports *that* mods collide, not which one
 * wins — that depends on the game's addon load order, which is not predicted here.
 */
export type AddonConflictReport = {
  directory: string;
  packageCount: number;
  enabledCount: number;
  disabledCount: number;
  /** True when a .dmm.json was found, so mod grouping is trustworthy. */
  usesModManager: boolean;
  conflictCount: number;
  /** Overlaps on readmes and uncompiled sources the game does not load. */
  otherOverlapCount: number;
  modConflictCount: number;
  /** Enabled packages sharing no loaded file, so merging them loses nothing. */
  mergeableCount: number;
  mergeable: InstalledPackage[];
  unreadableCount: number;
  packages: InstalledPackage[];
  conflicts: AddonConflict[];
  otherOverlaps: AddonConflict[];
  modConflicts: ModConflict[];
};

/** One package in a `mods.compare` result. */
export type ComparedPackage = {
  path: string;
  filename: string;
  entryCount: number;
  sizeBytes: number;
  /** Paths only this package has. These always survive a merge. */
  uniqueCount: number;
};

/** One path present in more than one compared package. */
export type SharedPath = {
  path: string;
  kind: string;
  filenames: string[];
  /**
   * True when picking a winner is not enough, because the file bundles several
   * things separately. A Deadlock hero and their weapon share one .vmdl_c; a
   * single Panorama stylesheet holds the crosshair *and* the hit marker. Those
   * collisions cannot be split by choosing files.
   */
  inseparable: boolean;
};

/**
 * A package whose materials the other package's model never asks for. Two mods
 * can share no path at all and still fail to combine: if one replaces the hero
 * model and points every material slot at its own folder, the other's textures
 * are never loaded — no conflict, no effect.
 */
export type ReferenceWarning = {
  modelPackage: string;
  modelPath: string;
  supplierPackage: string;
  unreferencedCount: number;
  examples: string[];
  /** Move each material to the slot the model reads, matched on filename. */
  suggestedRenames: Array<{ source: string; target: string }>;
  /** Materials with no matching slot; left alone rather than guessed at. */
  unmatched: string[];
};

/** A redirect passed to `packages.combine`. */
export type RenameRule = {
  package: string;
  source: string;
  target: string;
};

/** Result of `mods.compare`: can these packages be combined? */
export type ModComparisonReport = {
  packages: ComparedPackage[];
  sharedCount: number;
  blockerCount: number;
  /** False when a shared path is inseparable, or a model orphans the other mod. */
  mergeable: boolean;
  referenceWarnings: ReferenceWarning[];
  countsByKind: Record<string, number>;
  shared: SharedPath[];
};
