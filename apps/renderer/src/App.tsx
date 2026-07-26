import {
  Activity,
  ArrowDown,
  ArrowUp,
  AudioLines,
  BookOpen,
  Box,
  Check,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Copy,
  Download,
  ExternalLink,
  FileArchive,
  FileAudio,
  FolderOpen,
  Gauge,
  GitFork,
  Image as ImageIcon,
  Info,
  Layers3,
  ListMusic,
  Merge,
  PackageCheck,
  PackageOpen,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Tag,
  Trash2,
  Upload,
  UserRound,
  Wrench,
  X
} from "lucide-react";
import appIconUrl from "../../../build/icon.png";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { StatusBadge } from "./components/StatusBadge";
import { SoundTutorial } from "./components/SoundTutorial";
import { WaveformPlayer } from "./components/WaveformPlayer";
import type {
  AudioMetadata,
  AppInfo,
  Bootstrap,
  BuildProgress,
  BuildResult,
  CompatibilityReport,
  DiagnosticProgress,
  Diagnostics,
  IndexHistoryEntry,
  LoopSettings,
  ProcessingSettings,
  ProjectManifest,
  ProjectSummary,
  PackageCombineResult,
  PackageInventory,
  PackageProgress,
  RequirementInstallResult,
  RequirementProgress,
  Settings,
  SoundAsset,
  SoundCategory,
  UpdateInfo,
  UpdateProgress,
  VisualResourceAsset,
  VisualResourceKind,
  VisualSourceMetadata
} from "./types";
import { DEFAULT_LOOP, DEFAULT_PROCESSING } from "./types";

type View =
  | "home"
  | "sounds"
  | "visuals"
  | "projects"
  | "packages"
  | "diagnostics"
  | "about";

const NAV_ITEMS: Array<{ id: View; label: string; icon: typeof AudioLines }> = [
  { id: "home", label: "Overview", icon: Gauge },
  { id: "sounds", label: "Sounds", icon: ListMusic },
  { id: "visuals", label: "Visuals (WIP)", icon: ImageIcon },
  { id: "projects", label: "Projects", icon: Layers3 },
  { id: "packages", label: "PAK Combiner", icon: Merge },
  { id: "diagnostics", label: "Diagnostics", icon: Activity },
  { id: "about", label: "About", icon: Info }
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null) return "-";
  const seconds = milliseconds / 1000;
  return `${seconds.toFixed(seconds >= 10 ? 1 : 2)}s`;
}

function formatRelativeTime(isoTimestamp: string): string {
  const then = Date.parse(isoTimestamp);
  if (Number.isNaN(then)) return "unknown";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const units: Array<[number, Intl.RelativeTimeFormatUnit]> = [
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"]
  ];
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  let value = seconds / 60;
  for (const [step, unit] of units) {
    if (Math.abs(value) < step) return formatter.format(-Math.round(value), unit);
    value /= step;
  }
  return formatter.format(-Math.round(value), "year");
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** unit;
  return `${value.toFixed(unit === 0 || value >= 100 ? 0 : 1)} ${units[unit]}`;
}

// Notices default to the destructive tone; confirmations opt into "info" so a
// successful result is not dressed up as a failure.
type Notice = { text: string; tone: "info" | "error" };
const INFO_NOTICE_MS = 6000;

// The boot screen lingers briefly after the workspace is ready, then crossfades
// away over the mounted shell instead of cutting straight to it.
type BootPhase = "loading" | "fading" | "done";
const BOOT_SETTLE_MS = 500;
const BOOT_FADE_MS = 420;

// Rendered even while idle so it can fade in and out. It is positioned out of
// flow, so mounting it costs no layout and toggling it never reflows the page.
function ActivityBar({
  active,
  label
}: {
  active: boolean;
  label: string;
}) {
  return (
    <div
      className={active ? "activity-bar is-active" : "activity-bar"}
      role="status"
      aria-live="polite"
      aria-hidden={!active}
    >
      <div className="activity-track" aria-hidden="true">
        <i />
      </div>
      {label && <span className="activity-label">{label}</span>}
    </div>
  );
}

function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [view, setActiveView] = useState<View>("home");
  const [activeProject, setActiveProject] = useState<ProjectManifest | null>(null);
  const [notice, setNoticeState] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<BuildProgress | null>(null);
  const [diagnosticProgress, setDiagnosticProgress] = useState<DiagnosticProgress | null>(null);
  const [requirementProgress, setRequirementProgress] = useState<RequirementProgress | null>(null);
  const [packageProgress, setPackageProgress] = useState<PackageProgress | null>(null);
  const [updateProgress, setUpdateProgress] = useState<UpdateProgress | null>(null);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updatePromptOpen, setUpdatePromptOpen] = useState(false);
  const [checkingForUpdates, setCheckingForUpdates] = useState(false);
  const [installingUpdate, setInstallingUpdate] = useState(false);
  const [buildModalProject, setBuildModalProject] = useState<ProjectManifest | null>(null);
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [bootMessage, setBootMessage] = useState("Starting secure Python workspace…");
  const [bootPhase, setBootPhase] = useState<BootPhase>("loading");
  const [appVersion, setAppVersion] = useState<string | null>(null);
  const startupCheckStarted = useRef(false);
  const tutorialCheckStarted = useRef(false);

  const setNotice = useCallback((message: string | null) => {
    setNoticeState(message ? { text: message, tone: "error" } : null);
  }, []);

  const setInfoNotice = useCallback((message: string | null) => {
    setNoticeState(message ? { text: message, tone: "info" } : null);
  }, []);

  // Confirmations clear themselves; failures stay until dismissed.
  useEffect(() => {
    if (notice?.tone !== "info") return;
    const timer = window.setTimeout(() => setNoticeState(null), INFO_NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const setView = useCallback((nextView: View) => {
    const documentWithTransitions = document as Document & {
      startViewTransition?: (update: () => void) => unknown;
    };
    if (!documentWithTransitions.startViewTransition) {
      setActiveView(nextView);
      return;
    }
    documentWithTransitions.startViewTransition(() => {
      flushSync(() => setActiveView(nextView));
    });
  }, []);

  const loadBootstrap = useCallback(async () => {
    setBusy(true);
    try {
      if (!startupCheckStarted.current) {
        startupCheckStarted.current = true;
        setBootMessage("Checking GitHub for application updates…");
        setCheckingForUpdates(true);
        try {
          const availableUpdate = await window.studio.checkForUpdates();
          setUpdateInfo(availableUpdate);
          setUpdatePromptOpen(availableUpdate.available);
        } catch (error) {
          setUpdateInfo(null);
          console.warn("Startup update check failed", error);
        } finally {
          setCheckingForUpdates(false);
        }
      }
      setBootMessage("Loading settings and checking required tools…");
      const result = await window.studio.backend<Bootstrap>("app.bootstrap");
      setBootstrap(result);
      if (activeProject) {
        const refreshed = await window.studio.backend<ProjectManifest>("projects.get", {
          projectId: activeProject.id
        });
        setActiveProject(refreshed);
      }
      if (result.autoIndex.warning) {
        setNotice(`The first-run resource catalog could not be built: ${result.autoIndex.warning}`);
      } else if (result.autoIndex.attempted) {
        setInfoNotice(
          `Resource catalog ready: ${result.autoIndex.indexed.toLocaleString()} sounds and ${(result.autoIndex.visualIndexed ?? result.visualCount).toLocaleString()} visuals indexed.`
        );
      } else {
        setNoticeState(null);
      }
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }, [activeProject?.id]);

  useEffect(() => {
    void loadBootstrap();
  }, []);

  useEffect(() => {
    window.studio
      .appInfo()
      .then((info) => setAppVersion(info.version))
      .catch(() => setAppVersion(null));
  }, []);

  // Hold the boot screen a beat once the workspace is ready, then fade it out
  // over the shell so startup does not snap between two screens.
  useEffect(() => {
    if (!bootstrap || bootPhase === "done") return;
    const delay = bootPhase === "loading" ? BOOT_SETTLE_MS : BOOT_FADE_MS;
    const nextPhase: BootPhase = bootPhase === "loading" ? "fading" : "done";
    const timer = window.setTimeout(() => setBootPhase(nextPhase), delay);
    return () => window.clearTimeout(timer);
  }, [bootstrap, bootPhase]);

  useEffect(() => {
    if (
      !bootstrap?.settings.setupCompleted ||
      bootstrap.settings.tutorialCompleted ||
      updatePromptOpen ||
      tutorialCheckStarted.current
    ) {
      return;
    }
    tutorialCheckStarted.current = true;
    setTutorialOpen(true);
  }, [
    bootstrap?.settings.setupCompleted,
    bootstrap?.settings.tutorialCompleted,
    updatePromptOpen
  ]);

  useEffect(
    () =>
      window.studio.onBackendEvent((event) => {
        if (event.event === "build.progress") setProgress(event as BuildProgress);
        if (event.event === "diagnostics.progress") {
          setDiagnosticProgress(event as unknown as DiagnosticProgress);
        }
        if (event.event === "requirements.progress") {
          setRequirementProgress(event as unknown as RequirementProgress);
        }
        if (event.event === "packages.progress") {
          setPackageProgress(event as unknown as PackageProgress);
        }
        if (event.event === "update.progress") {
          setUpdateProgress(event as unknown as UpdateProgress);
        }
        if (event.event === "diagnostics.progress" && typeof event.message === "string") {
          setBootMessage(event.message);
        }
        if (event.event === "index.progress" && typeof event.message === "string") {
          setBootMessage(event.message);
        }
      }),
    []
  );

  async function selectProject(project: ProjectSummary) {
    setBusy(true);
    try {
      const manifest = await window.studio.backend<ProjectManifest>("projects.get", {
        projectId: project.id
      });
      setActiveProject(manifest);
      setView("projects");
      return manifest;
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setBusy(false);
    }
    return null;
  }

  function closeTutorial() {
    setTutorialOpen(false);
    if (!bootstrap || bootstrap.settings.tutorialCompleted) return;
    const nextSettings = {
      ...bootstrap.settings,
      tutorialCompleted: true
    };
    void window.studio
      .backend<Diagnostics>("settings.save", nextSettings)
      .then((diagnostics) =>
        setBootstrap((current) =>
          current
            ? { ...current, diagnostics, settings: nextSettings }
            : current
        )
      )
      .catch((error) =>
        setNotice(`Could not save tutorial progress: ${errorMessage(error)}`)
      );
  }

  async function exportProject(project: ProjectSummary) {
    const manifest = await selectProject(project);
    if (manifest) setBuildModalProject(manifest);
  }

  async function checkUpdates(manual = true) {
    setCheckingForUpdates(true);
    try {
      const result = await window.studio.checkForUpdates();
      setUpdateInfo(result);
      setUpdatePromptOpen(result.available);
      if (manual && !result.available) {
        setInfoNotice(
          result.status === "noReleases"
            ? "No published GitHub releases are available yet."
            : `Deadlock Mod Maker ${result.currentVersion} is up to date.`
        );
      }
    } catch (error) {
      setNotice(`Update check failed: ${errorMessage(error)}`);
    } finally {
      setCheckingForUpdates(false);
    }
  }

  async function installAvailableUpdate() {
    setInstallingUpdate(true);
    setUpdateProgress({
      event: "update.progress",
      stage: "starting",
      message: "Preparing the application update…",
      downloadedBytes: 0,
      totalBytes: updateInfo?.assetSize ?? 0
    });
    try {
      await window.studio.installUpdate();
    } catch (error) {
      setInstallingUpdate(false);
      setNotice(`Update installation failed: ${errorMessage(error)}`);
    }
  }

  const bootOverlay =
    bootPhase === "done" ? null : (
      <main
        className={bootPhase === "fading" ? "boot-screen is-leaving" : "boot-screen"}
        aria-hidden={bootPhase === "fading"}
      >
        <div className="brand-mark">
          <img src={appIconUrl} alt="" />
        </div>
        <h1>Deadlock Mod Maker</h1>
        <p>{notice?.text ?? "Preparing your workspace."}</p>
        <ActivityBar active={!notice} label={bootMessage} />
        {notice && <button onClick={() => void loadBootstrap()}>Try again</button>}
      </main>
    );

  if (!bootstrap) return bootOverlay;

  const diagnosticState = bootstrap.diagnostics.canBuild
    ? "Build ready"
    : bootstrap.diagnostics.canIndex
      ? "Setup incomplete"
      : "Setup required";

  return (
    <>
      {bootOverlay}
      <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <img src={appIconUrl} alt="" />
          </div>
          <div>
            <strong>Deadlock</strong>
            <span>Mod Maker</span>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                data-tutorial={`${item.id}-nav`}
                className={view === item.id ? "active" : ""}
                onClick={() => setView(item.id)}
              >
                <Icon size={17} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <button className="setup-card" onClick={() => setView("diagnostics")}>
            <span className={`setup-dot ${bootstrap.diagnostics.canBuild ? "ready" : ""}`} />
            <span>
              <strong>{diagnosticState}</strong>
              <small>
                {bootstrap.diagnostics.checks.filter((item) => item.status === "found").length}/
                {bootstrap.diagnostics.checks.length} checks found
              </small>
            </span>
          </button>
          <p className="version">{appVersion ? `v${appVersion}` : ""}</p>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{NAV_ITEMS.find((item) => item.id === view)?.label}</h1>
            <p>
              {view === "about"
                ? "Build details, updates, and project links"
                : activeProject
                ? `${activeProject.displayName} · ${activeProject.targetAssets.length + activeProject.visualAssets.length} replacement${activeProject.targetAssets.length + activeProject.visualAssets.length === 1 ? "" : "s"}`
                : view === "packages"
                  ? "Inspect and combine Valve package files"
                : "No active project"}
            </p>
          </div>
          <div className="topbar-actions">
            {activeProject && (
              <button
                className="icon-button active-project-button"
                title={`Open project: ${activeProject.displayName}`}
                aria-label={`Open project: ${activeProject.displayName}`}
                onClick={() => setView("projects")}
              >
                <Box size={15} />
              </button>
            )}
            <button className="icon-button" title="Refresh" onClick={() => void loadBootstrap()}>
              <RefreshCw size={17} className={busy ? "spin" : ""} />
            </button>
          </div>
        </header>

        <ActivityBar
          active={busy}
          label={bootMessage}
        />

        {notice && (
          <div className={notice.tone === "error" ? "notice error" : "notice"}>
            {notice.tone === "error" ? <CircleAlert size={16} /> : <Check size={16} />}
            <span>{notice.text}</span>
            <button aria-label="Dismiss message" onClick={() => setNoticeState(null)}>
              <X size={15} />
            </button>
          </div>
        )}

        <div className="content" key={view}>
          {view === "home" && (
            <Overview
              bootstrap={bootstrap}
              activeProject={activeProject}
              onNavigate={setView}
              onOpenProject={(project) => void selectProject(project)}
            />
          )}
          {view === "sounds" && (
            <SoundBrowser
              diagnostics={bootstrap.diagnostics}
              soundCount={bootstrap.soundCount}
              activeProject={activeProject}
              onProjectChanged={(project) => {
                setActiveProject(project);
                void loadBootstrap();
              }}
              onNotice={setNotice}
              onIndexed={() => void loadBootstrap()}
              onRequireProject={() => {
                setNotice("Create or select a project before choosing replacement audio.");
                setView("projects");
              }}
            />
          )}
          {view === "visuals" && (
            <VisualBrowser
              diagnostics={bootstrap.diagnostics}
              visualCount={bootstrap.visualCount}
              activeProject={activeProject}
              onProjectChanged={(project) => {
                setActiveProject(project);
                void loadBootstrap();
              }}
              onNotice={setNotice}
              onIndexed={() => void loadBootstrap()}
              onRequireProject={() => {
                setNotice("Create or select a project before choosing a visual replacement.");
                setView("projects");
              }}
            />
          )}
          {view === "projects" && (
            <ProjectsPage
              projects={bootstrap.projects}
              activeProject={activeProject}
              onSelect={selectProject}
              onProjectChanged={(project) => {
                setActiveProject(project);
                void loadBootstrap();
              }}
              onProjectDeleted={(projectId) => {
                setBootstrap((current) =>
                  current
                    ? {
                        ...current,
                        projects: current.projects.filter((project) => project.id !== projectId)
                      }
                    : current
                );
                if (activeProject?.id === projectId) setActiveProject(null);
              }}
              onNavigate={setView}
              onExportProject={(project) => void exportProject(project)}
              onOpenBuild={() => activeProject && setBuildModalProject(activeProject)}
              onNotice={setNotice}
            />
          )}
          {view === "packages" && (
            <PackageCombinerPage
              progress={packageProgress}
              onProgressReset={() => setPackageProgress(null)}
              onNotice={setNotice}
            />
          )}
          {view === "diagnostics" && (
            <DiagnosticsPage
              diagnostics={bootstrap.diagnostics}
              settings={bootstrap.settings}
              progress={diagnosticProgress}
              requirementProgress={requirementProgress}
              onScanStart={() => {
                setDiagnosticProgress(null);
                setRequirementProgress(null);
              }}
              onChanged={(diagnostics, settings) =>
                setBootstrap({ ...bootstrap, diagnostics, settings })
              }
              onNotice={setNotice}
            />
          )}
          {view === "about" && (
            <AboutPage
              updateInfo={updateInfo}
              checkingForUpdates={checkingForUpdates}
              onCheckUpdates={() => void checkUpdates(true)}
              onShowUpdate={() => setUpdatePromptOpen(true)}
              onReplayTutorial={() => setTutorialOpen(true)}
              onNotice={setNotice}
            />
          )}
        </div>
      </section>
      {buildModalProject && (
        <BuildExportModal
          project={buildModalProject}
          diagnostics={bootstrap.diagnostics}
          progress={progress}
          onProgress={setProgress}
          onClose={() => setBuildModalProject(null)}
          onProjectChanged={(project) => {
            setActiveProject(project);
            setBuildModalProject(project);
            void loadBootstrap();
          }}
          onNotice={setNotice}
        />
      )}
      {!bootstrap.settings.setupCompleted && (
        <SetupWizard
          diagnostics={bootstrap.diagnostics}
          settings={bootstrap.settings}
          progress={diagnosticProgress}
          requirementProgress={requirementProgress}
          onScanStart={() => {
            setDiagnosticProgress(null);
            setRequirementProgress(null);
          }}
          onComplete={(diagnostics, settings) => {
            setBootstrap({ ...bootstrap, diagnostics, settings });
            if (settings.setupCompleted) void loadBootstrap();
          }}
          onNotice={setNotice}
        />
      )}
      {updatePromptOpen && updateInfo?.available && bootstrap.settings.setupCompleted && (
        <UpdatePrompt
          update={updateInfo}
          progress={updateProgress}
          installing={installingUpdate}
          onInstall={() => void installAvailableUpdate()}
          onLater={() => setUpdatePromptOpen(false)}
        />
      )}
      {tutorialOpen && bootstrap.settings.setupCompleted && !updatePromptOpen && (
        <SoundTutorial onNavigate={setView} onClose={closeTutorial} />
      )}
      </div>
    </>
  );
}

function Overview({
  bootstrap,
  activeProject,
  onNavigate,
  onOpenProject
}: {
  bootstrap: Bootstrap;
  activeProject: ProjectManifest | null;
  onNavigate: (view: View) => void;
  onOpenProject: (project: ProjectSummary) => void;
}) {
  const recentProjects = [...bootstrap.projects]
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .slice(0, 5);
  const blockedChecks = bootstrap.diagnostics.checks.filter((check) => check.status !== "found");
  // A project built against a different archive than the one currently indexed
  // is very likely broken in-game. Projects that never built are not stale.
  const staleProjects = bootstrap.gameFingerprint
    ? bootstrap.projects.filter(
        (project) => project.gameFingerprint && project.gameFingerprint !== bootstrap.gameFingerprint
      )
    : [];

  return (
    <div className="page-stack">
      <PageHeading
        title="Welcome"
        description="Pick a sound or visual to replace, then export the result as a VPK."
        actions={
          <>
            <button className="primary" onClick={() => onNavigate("sounds")}>
              <Search size={16} /> Browse sounds
            </button>
            <button onClick={() => onNavigate("visuals")}>
              <ImageIcon size={16} /> Browse visuals
            </button>
            <button onClick={() => onNavigate("projects")}>
              <Plus size={16} /> {activeProject ? "Review project" : "Create project"}
            </button>
          </>
        }
      />
      <div className="metric-grid">
        <Metric
          label="Indexed resources"
          value={(bootstrap.soundCount + bootstrap.visualCount).toLocaleString()}
          detail={`${bootstrap.soundCount.toLocaleString()} sounds · ${bootstrap.visualCount.toLocaleString()} visuals`}
        />
        <Metric
          label="Active project"
          value={
            activeProject
              ? (activeProject.targetAssets.length + activeProject.visualAssets.length).toString()
              : "-"
          }
          detail={activeProject?.displayName ?? "Choose or create one"}
        />
        <Metric
          label="Build readiness"
          value={bootstrap.diagnostics.canBuild ? "Ready" : "Blocked"}
          detail={
            bootstrap.diagnostics.canBuild
              ? "Audio, compiler, and packager found"
              : "Open Diagnostics for missing capabilities"
          }
        />
      </div>

      {staleProjects.length > 0 && (
        <section className="card overview-stale">
          <div className="section-heading">
            <div>
              <h3>
                {staleProjects.length} project{staleProjects.length === 1 ? "" : "s"} built against
                an older game version
              </h3>
              <p>
                Deadlock has been updated since {staleProjects.length === 1 ? "it was" : "they were"}{" "}
                last built, so the replaced files may no longer match. Open one to re-point its
                targets and export again.
              </p>
            </div>
          </div>
          <ul className="overview-stale-list">
            {staleProjects.slice(0, 4).map((project) => (
              <li key={project.id}>
                <span>
                  <strong>{project.displayName}</strong>
                  <small>Last edited {formatRelativeTime(project.updatedAt)}</small>
                </span>
                <button onClick={() => onOpenProject(project)}>
                  <Wrench size={14} /> Review &amp; repair
                </button>
              </li>
            ))}
          </ul>
          {staleProjects.length > 4 && (
            <p className="overview-more">and {staleProjects.length - 4} more</p>
          )}
        </section>
      )}

      {blockedChecks.length > 0 && (
        <section className="card overview-blockers">
          <div className="section-heading">
            <div>
              <h3>{blockedChecks.length} tool{blockedChecks.length === 1 ? "" : "s"} still need attention</h3>
              <p>Builds stay blocked until these resolve.</p>
            </div>
            <button onClick={() => onNavigate("diagnostics")}>
              <Activity size={15} /> Open Diagnostics
            </button>
          </div>
          <ul className="overview-blocker-list">
            {blockedChecks.slice(0, 4).map((check) => (
              <li key={check.id}>
                <StatusBadge status={check.status} />
                <strong>{check.label}</strong>
                <span>{check.detail}</span>
              </li>
            ))}
          </ul>
          {blockedChecks.length > 4 && (
            <p className="overview-more">
              and {blockedChecks.length - 4} more
            </p>
          )}
        </section>
      )}

      <section className="card overview-projects">
        <div className="section-heading">
          <div>
            <h3>Projects</h3>
            <p>
              {recentProjects.length
                ? "Most recently edited first."
                : "Mods you create are saved locally and listed here."}
            </p>
          </div>
          <button onClick={() => onNavigate("projects")}>
            <Layers3 size={15} /> All projects
          </button>
        </div>
        {recentProjects.length === 0 ? (
          <div className="empty compact">
            <Layers3 size={22} />
            <strong>No projects yet</strong>
            <span>Create one to start collecting replacements.</span>
          </div>
        ) : (
          <ul className="overview-project-list">
            {recentProjects.map((project) => (
              <li key={project.id}>
                <button
                  className={project.id === activeProject?.id ? "selected" : ""}
                  onClick={() => onOpenProject(project)}
                >
                  <span className="overview-project-name">
                    <strong>{project.displayName}</strong>
                    <small>
                      {project.enabledCount} of {project.replacementCount} enabled ·{" "}
                      {formatRelativeTime(project.updatedAt)}
                    </small>
                  </span>
                  <span className={`overview-build-state ${buildStateClass(project.lastBuildSuccess)}`}>
                    {project.lastBuildSuccess === null
                      ? "Never built"
                      : project.lastBuildSuccess
                        ? "Last build passed"
                        : "Last build failed"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function buildStateClass(success: boolean | null): string {
  if (success === null) return "neutral";
  return success ? "passed" : "failed";
}

// Replaces window.confirm, which renders an unstyled OS dialog. Escape cancels
// and the destructive action is never the default focus.
function ConfirmDialog({
  title,
  body,
  confirmLabel,
  destructive,
  busy,
  onConfirm,
  onCancel
}: {
  title: string;
  body: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onCancel]);

  return (
    <div className="modal-backdrop confirm-backdrop" role="presentation">
      <section
        className="modal-shell confirm-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
      >
        <header className="modal-header">
          <div>
            <h2 id="confirm-title">{title}</h2>
            <p>{body}</p>
          </div>
        </header>
        <div className="modal-actions">
          <button disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            className={destructive ? "danger-button" : "primary"}
            disabled={busy}
            autoFocus
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

// Every page leads with the same plain heading block - no card, no panel, so
// the first real card on the page is actual content rather than decoration.
function PageHeading({
  title,
  description,
  actions
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <section className="page-heading">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="button-row">{actions}</div>}
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <section className="metric card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </section>
  );
}

function SoundBrowser({
  diagnostics,
  soundCount,
  activeProject,
  onProjectChanged,
  onNotice,
  onIndexed,
  onRequireProject
}: {
  diagnostics: Diagnostics;
  soundCount: number;
  activeProject: ProjectManifest | null;
  onProjectChanged: (project: ProjectManifest) => void;
  onNotice: (message: string | null) => void;
  onIndexed: () => void;
  onRequireProject: () => void;
}) {
  const [sounds, setSounds] = useState<SoundAsset[]>([]);
  const [indexHistory, setIndexHistory] = useState<IndexHistoryEntry[]>([]);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | "heroes" | "general">("all");
  const [category, setCategory] = useState<string>("");
  const [selected, setSelected] = useState<SoundAsset | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const loading = Boolean(operation);
  const [original, setOriginal] = useState<AudioMetadata | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [replacementPath, setReplacementPath] = useState<string | null>(null);
  const [replacement, setReplacement] = useState<AudioMetadata | null>(null);
  const [replacementUrl, setReplacementUrl] = useState<string | null>(null);
  const [processed, setProcessed] = useState<AudioMetadata | null>(null);
  const [processedUrl, setProcessedUrl] = useState<string | null>(null);
  const [processing, setProcessing] = useState<ProcessingSettings>({ ...DEFAULT_PROCESSING });
  const [looping, setLooping] = useState<LoopSettings>({ ...DEFAULT_LOOP });

  const search = useCallback(async () => {
    setOperation("Searching indexed sounds…");
    try {
      const result = await window.studio.backend<SoundAsset[]>("sounds.search", {
        query,
        category: category || undefined,
        scope,
        limit: 350
      });
      setSounds(result);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }, [query, category, scope]);

  const loadIndexHistory = useCallback(async () => {
    try {
      setIndexHistory(
        await window.studio.backend<IndexHistoryEntry[]>("sounds.indexHistory", {
          limit: 8
        })
      );
    } catch (error) {
      onNotice(errorMessage(error));
    }
  }, []);

  useEffect(() => {
    void search();
  }, [scope, category]);

  useEffect(() => {
    void loadIndexHistory();
  }, []);

  function resetReplacement() {
    setReplacementPath(null);
    setReplacement(null);
    setReplacementUrl(null);
    setProcessed(null);
    setProcessedUrl(null);
    setProcessing({ ...DEFAULT_PROCESSING });
    setLooping({ ...DEFAULT_LOOP });
  }

  async function chooseSound(sound: SoundAsset) {
    setSelected(sound);
    setOriginal(null);
    setOriginalUrl(null);
    resetReplacement();
  }

  async function previewOriginal() {
    if (!selected) return;
    setOperation("Preparing original preview…");
    try {
      const metadata = await window.studio.backend<AudioMetadata>("sounds.preview", {
        assetId: selected.id
      });
      setOriginal(metadata);
      setOriginalUrl(metadata.previewPath ? await window.studio.mediaUrl(metadata.previewPath) : null);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function loadReplacement(path: string) {
    setOperation("Inspecting replacement audio…");
    try {
      const metadata = await window.studio.backend<AudioMetadata>("audio.inspect", { path });
      setReplacementPath(path);
      setReplacement(metadata);
      setReplacementUrl(await window.studio.mediaUrl(path));
      setProcessed(null);
      setProcessedUrl(null);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function chooseReplacement() {
    if (!activeProject) {
      onRequireProject();
      return;
    }
    const path = await window.studio.selectAudio();
    if (path) await loadReplacement(path);
  }

  async function previewProcessed() {
    if (!replacementPath) return;
    setOperation("Processing preview audio…");
    try {
      const metadata = await window.studio.backend<AudioMetadata>("audio.previewProcessed", {
        path: replacementPath,
        processing
      });
      setProcessed(metadata);
      setProcessedUrl(metadata.previewPath ? await window.studio.mediaUrl(metadata.previewPath) : null);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function confirmReplacement() {
    if (!activeProject || !selected || !replacementPath) return;
    setOperation("Adding replacement to project…");
    try {
      const project = await window.studio.backend<ProjectManifest>("projects.confirmReplacement", {
        projectId: activeProject.id,
        assetId: selected.id,
        sourcePath: replacementPath,
        processing,
        looping
      });
      onProjectChanged(project);
      resetReplacement();
      onNotice(`Confirmed ${selected.filename}. Add another sound or review the project queue.`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function indexSounds() {
    setOperation("Indexing the Deadlock archive…");
    try {
      const result = await window.studio.backend<{ indexed: number; warnings?: string[] }>(
        "sounds.index"
      );
      onNotice(
        `Indexed ${result.indexed.toLocaleString()} compiled sounds.${
          result.warnings?.at(-1) ? ` ${result.warnings.at(-1)}` : ""
        }`
      );
      setOperation("Refreshing sound results…");
      const refreshed = await window.studio.backend<SoundAsset[]>("sounds.search", {
        query,
        category: category || undefined,
        scope,
        limit: 350
      });
      setSounds(refreshed);
      await loadIndexHistory();
      onIndexed();
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  const categories: Array<{ value: string; label: string }> = [
    { value: "", label: "Every category" },
    { value: "hero", label: "Hero" },
    { value: "voice", label: "Voice lines" },
    { value: "ability", label: "Abilities" },
    { value: "weapon", label: "Weapons" },
    { value: "ui", label: "Interface" },
    { value: "music", label: "Music" },
    { value: "ambient", label: "Ambient" },
    { value: "announcer", label: "Announcer" },
    { value: "objective", label: "Objectives" },
    { value: "item", label: "Items" },
    { value: "general", label: "General gameplay" },
    { value: "unclassified", label: "Unclassified" }
  ];

  return (
    <div className="browser-layout">
      <section className="sound-list card">
        <div className="search-row" data-tutorial="sound-search">
          <label className="search-box">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void search()}
              placeholder="Filename, path, hero, ability, event…"
            />
          </label>
          <select
            aria-label="Sound scope"
            value={scope}
            onChange={(event) =>
              setScope(event.target.value as "all" | "heroes" | "general")
            }
          >
            <option value="all">All sounds</option>
            <option value="heroes">Hero sounds</option>
            <option value="general">General sounds</option>
          </select>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            {categories.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button onClick={() => void search()} disabled={loading}>
            Search
          </button>
        </div>
        <ActivityBar active={loading} label={operation ?? ""} />
        <div className="list-summary">
          <span>{sounds.length} shown · {soundCount.toLocaleString()} indexed · {indexHistory.length} catalog version{indexHistory.length === 1 ? "" : "s"}</span>
          <button onClick={() => void indexSounds()} disabled={!diagnostics.canIndex || loading}>
            <RefreshCw size={14} /> {soundCount ? "Re-index archive" : "Index archive"}
          </button>
        </div>
        {indexHistory.length > 0 && (
          <details className="catalog-history">
            <summary>Index history</summary>
            <div>
              {indexHistory.map((entry) => (
                <span key={`${entry.archiveFingerprint}-${entry.indexedAt}`}>
                  <time>{new Date(entry.indexedAt).toLocaleString()}</time>
                  <strong>{entry.assetCount.toLocaleString()} sounds</strong>
                  <code>{entry.archiveFingerprint.slice(0, 10)}</code>
                </span>
              ))}
            </div>
          </details>
        )}
        <div className="asset-list">
          {sounds.map((sound) => (
            <button
              key={sound.id}
              className={selected?.id === sound.id ? "selected" : ""}
              onClick={() => void chooseSound(sound)}
            >
              <span className="asset-icon">
                <AudioLines size={16} />
              </span>
              <span className="asset-main">
                <strong>{sound.filename}</strong>
                <small>{sound.internalPath}</small>
              </span>
              <span className="asset-tags">
                {sound.heroName && (
                  <span title={`Hero: ${sound.heroName}`} aria-label={`Hero: ${sound.heroName}`}>
                    <UserRound size={13} aria-hidden="true" />
                  </span>
                )}
                <span title={`Category: ${sound.category}`} aria-label={`Category: ${sound.category}`}>
                  <Tag size={13} aria-hidden="true" />
                </span>
              </span>
            </button>
          ))}
          {!sounds.length && (
            <div className="empty">
              <AudioLines size={27} />
              <strong>{soundCount ? "No matching sounds" : "The local sound index is empty"}</strong>
              <span>{soundCount ? "Try a broader search." : "Run Index archive after Deadlock is detected."}</span>
            </div>
          )}
        </div>
      </section>

      <section className="editor card" data-tutorial="sound-replacement">
        {!activeProject && (
          <div className="project-required" role="note">
            <Box size={18} />
            <div>
              <strong>Choose a project before making changes</strong>
              <span>Your replacement and processing settings will be saved directly to that mod.</span>
            </div>
            <button onClick={onRequireProject}>Create or select a project</button>
          </div>
        )}
        {!selected ? (
          <div className="empty">
            <FileAudio size={30} />
            <strong>Select an original sound</strong>
            <span>Only the selected asset is exported for preview.</span>
          </div>
        ) : (
          <>
            <div className="section-heading">
              <div>
                <div className="eyebrow">{selected.heroName ?? selected.category}</div>
                <h3>{selected.filename}</h3>
                <p className="path">{selected.internalPath}</p>
              </div>
              <span
                className="metadata-icon"
                title={`Category: ${selected.category}`}
                aria-label={`Category: ${selected.category}`}
              >
                <Tag size={16} aria-hidden="true" />
              </span>
            </div>
            <div className="metadata-grid">
              <Metadata label="Duration" value={formatDuration(selected.durationMs)} />
              <Metadata label="Sample rate" value={selected.sampleRate ? `${selected.sampleRate} Hz` : "-"} />
              <Metadata label="Channels" value={selected.channels?.toString() ?? "-"} />
              <Metadata label="Sound event" value={selected.soundEvent ?? "Not associated"} />
            </div>
            <WaveformPlayer url={originalUrl} label="Original sound" />
            <button
              onClick={() => void previewOriginal()}
              disabled={loading || !diagnostics.canPreviewOriginal}
            >
              <AudioLines size={15} />
              {diagnostics.canPreviewOriginal ? "Export & preview original" : "Source2Viewer CLI required"}
            </button>

            <div
              className="drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (!activeProject) {
                  onRequireProject();
                  return;
                }
                const file = event.dataTransfer.files[0];
                if (file) {
                  void window.studio.droppedFilePath(file).then(loadReplacement).catch((error) => onNotice(errorMessage(error)));
                }
              }}
            >
              <Upload size={22} />
              <div>
                <strong>{replacementPath ? "Choose a different file" : "Drop MP3 or WAV here"}</strong>
                <span>Selection never changes the original file.</span>
              </div>
              <button onClick={() => void chooseReplacement()}>Choose replacement</button>
            </div>

            {replacement && (
              <>
                <WaveformPlayer
                  url={replacementUrl}
                  label={`Source · ${replacementPath?.split(/[\\/]/).pop()}`}
                  accent="#d4d4d4"
                  durationMs={replacement.durationMs}
                  editable={{
                    processing,
                    looping,
                    onProcessing: setProcessing,
                    onLooping: setLooping
                  }}
                />
                <div className="compare-strip">
                  <Metadata label="Replacement length" value={formatDuration(replacement.durationMs)} />
                  <Metadata label="Channels" value={replacement.channels?.toString() ?? "-"} />
                  <Metadata label="Sample rate" value={replacement.sampleRate ? `${replacement.sampleRate} Hz` : "-"} />
                  <Metadata label="Codec" value={replacement.codec ?? "-"} />
                </div>
                <ProcessingEditor
                  processing={processing}
                  looping={looping}
                  onProcessing={setProcessing}
                  onLooping={setLooping}
                />
                <div className="button-row">
                  <button onClick={() => void previewProcessed()} disabled={!diagnostics.canProcessAudio || loading}>
                    <Settings2 size={15} /> Process preview
                  </button>
                  <button onClick={resetReplacement}>Cancel</button>
                </div>
                {processedUrl && <WaveformPlayer url={processedUrl} label="Processed preview" accent="#ffbf69" />}
                <div className="confirm-panel">
                  <div>
                    <strong>Confirm this mapping</strong>
                    <span>
                      {activeProject
                        ? `Adds it to ${activeProject.displayName}; compilation starts later.`
                        : "Create or select a project before confirming."}
                    </span>
                  </div>
                  <button
                    className="primary"
                    disabled={!activeProject || loading}
                    onClick={() => void confirmReplacement()}
                  >
                    <Plus size={15} /> Confirm replacement
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function VisualBrowser({
  diagnostics,
  visualCount,
  activeProject,
  onProjectChanged,
  onNotice,
  onIndexed,
  onRequireProject
}: {
  diagnostics: Diagnostics;
  visualCount: number;
  activeProject: ProjectManifest | null;
  onProjectChanged: (project: ProjectManifest) => void;
  onNotice: (message: string | null) => void;
  onIndexed: () => void;
  onRequireProject: () => void;
}) {
  const [assets, setAssets] = useState<VisualResourceAsset[]>([]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"" | VisualResourceKind>("");
  const [selected, setSelected] = useState<VisualResourceAsset | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [original, setOriginal] = useState<VisualSourceMetadata | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [replacementPath, setReplacementPath] = useState<string | null>(null);
  const [replacement, setReplacement] = useState<VisualSourceMetadata | null>(null);
  const [replacementUrl, setReplacementUrl] = useState<string | null>(null);

  const search = useCallback(async () => {
    setOperation("Searching indexed visual resources…");
    try {
      setAssets(
        await window.studio.backend<VisualResourceAsset[]>("visuals.search", {
          query,
          kind: kind || undefined,
          limit: 400
        })
      );
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }, [query, kind]);

  useEffect(() => {
    void search();
  }, [kind]);

  function chooseAsset(asset: VisualResourceAsset) {
    setSelected(asset);
    setOriginal(null);
    setOriginalUrl(null);
    setReplacementPath(null);
    setReplacement(null);
    setReplacementUrl(null);
  }

  async function previewOriginal() {
    if (!selected) return;
    setOperation("Exporting the selected original resource…");
    try {
      const metadata = await window.studio.backend<VisualSourceMetadata>("visuals.preview", {
        assetId: selected.id
      });
      setOriginal(metadata);
      setOriginalUrl(
        metadata.previewPath ? await window.studio.mediaUrl(metadata.previewPath) : null
      );
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function chooseReplacement() {
    if (!selected) return;
    if (!activeProject) {
      onRequireProject();
      return;
    }
    const sourcePath = await window.studio.selectVisual(selected.kind);
    if (!sourcePath) return;
    setOperation("Inspecting replacement source…");
    try {
      const metadata = await window.studio.backend<VisualSourceMetadata>(
        "visuals.inspectSource",
        { path: sourcePath, kind: selected.kind }
      );
      setReplacementPath(sourcePath);
      setReplacement(metadata);
      setReplacementUrl(
        metadata.previewPath ? await window.studio.mediaUrl(metadata.previewPath) : null
      );
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function confirm() {
    if (!selected || !replacementPath || !activeProject) return;
    setOperation("Adding visual replacement to the project…");
    try {
      const project = await window.studio.backend<ProjectManifest>(
        "projects.confirmVisualReplacement",
        {
          projectId: activeProject.id,
          assetId: selected.id,
          sourcePath: replacementPath
        }
      );
      onProjectChanged(project);
      setReplacement(null);
      setReplacementPath(null);
      setReplacementUrl(null);
      onNotice(`Confirmed ${selected.filename} for ${project.displayName}.`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function indexResources() {
    setOperation("Indexing sounds, textures, and materials…");
    try {
      const result = await window.studio.backend<{
        indexed: number;
        visualIndexed: number;
      }>("sounds.index");
      onNotice(
        `Indexed ${result.visualIndexed.toLocaleString()} visual resources and ${result.indexed.toLocaleString()} sounds.`
      );
      await search();
      onIndexed();
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  const renderPreview = (
    metadata: VisualSourceMetadata | null,
    url: string | null,
    label: string
  ) => {
    if (!metadata) {
      return <div className="visual-preview empty-preview">{label} not loaded</div>;
    }
    if (url) {
      return (
        <figure className="visual-preview">
          <img src={url} alt={label} />
          <figcaption>{label}</figcaption>
        </figure>
      );
    }
    return (
      <div className="material-preview">
        <strong>{label}</strong>
        <pre>{metadata.textPreview ?? "No material text was exported."}</pre>
      </div>
    );
  };

  return (
    <div className="browser-layout visual-browser">
      <section className="sound-list card">
        <div className="search-row">
          <label className="search-box">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void search()}
              placeholder="Texture or material filename/path…"
            />
          </label>
          <select
            value={kind}
            aria-label="Visual resource kind"
            onChange={(event) => setKind(event.target.value as "" | VisualResourceKind)}
          >
            <option value="">Textures & materials</option>
            <option value="texture">Textures</option>
            <option value="material">Materials</option>
          </select>
          <button onClick={() => void search()} disabled={Boolean(operation)}>
            <Search size={14} /> Search
          </button>
          <button onClick={() => void indexResources()} disabled={!diagnostics.canIndex || Boolean(operation)}>
            <RefreshCw size={14} /> Index
          </button>
        </div>
        <ActivityBar active={Boolean(operation)} label={operation ?? ""} />
        <div className="list-summary">
          <span>{assets.length.toLocaleString()} shown · {visualCount.toLocaleString()} indexed</span>
        </div>
        <div className="asset-list">
          {assets.map((asset) => (
            <button
              key={asset.id}
              className={selected?.id === asset.id ? "selected" : ""}
              onClick={() => chooseAsset(asset)}
            >
              <span className="asset-icon"><ImageIcon size={15} /></span>
              <span className="asset-main">
                <strong>{asset.filename}</strong>
                <small>{asset.internalPath}</small>
              </span>
              <span className="asset-tags">{asset.kind}</span>
            </button>
          ))}
          {!assets.length && (
            <div className="empty compact">
              <ImageIcon size={25} />
              <strong>No visual resources found</strong>
              <span>Index the archive or broaden the search.</span>
            </div>
          )}
        </div>
      </section>
      <section className="editor card">
        {!activeProject && (
          <div className="project-required" role="note">
            <Box size={18} />
            <div>
              <strong>Choose a project before making changes</strong>
              <span>The selected replacement will be stored in that mod instead of temporary state.</span>
            </div>
            <button onClick={onRequireProject}>Create or select a project</button>
          </div>
        )}
        {!selected ? (
          <div className="empty">
            <ImageIcon size={30} />
            <strong>Select a texture or material</strong>
            <span>The original is exported only when you request a preview.</span>
          </div>
        ) : (
          <>
            <div className="section-heading">
              <div>
                <div className="eyebrow">{selected.kind}</div>
                <h3>{selected.filename}</h3>
                <p className="path">{selected.internalPath}</p>
              </div>
            </div>
            <div className="metadata-grid">
              <Metadata label="Kind" value={selected.kind} />
              <Metadata label="Stored size" value={formatBytes(selected.storedSize)} />
              <Metadata label="Fingerprint" value={selected.assetFingerprint ?? "-"} />
              <Metadata label="Output" value={selected.compiledPath.split("/").pop() ?? selected.filename} />
            </div>
            <div className="visual-compare">
              {renderPreview(original, originalUrl, "Original")}
              {renderPreview(replacement, replacementUrl, "Replacement")}
            </div>
            <div className="button-row">
              <button
                disabled={!diagnostics.canPreviewOriginal || Boolean(operation)}
                onClick={() => void previewOriginal()}
              >
                <ImageIcon size={15} />
                {diagnostics.canPreviewOriginal ? "Preview original" : "Source2Viewer CLI required"}
              </button>
              <button disabled={Boolean(operation)} onClick={() => void chooseReplacement()}>
                <Upload size={15} /> Choose {selected.kind === "texture" ? "PNG, TGA, or PSD" : "VMAT"}
              </button>
            </div>
            {replacement && (
              <>
                <div className="metadata-grid">
                  <Metadata label="Format" value={replacement.format} />
                  <Metadata
                    label="Dimensions"
                    value={
                      replacement.width && replacement.height
                        ? `${replacement.width} × ${replacement.height}`
                        : "Text resource"
                    }
                  />
                  <Metadata label="Color space" value={replacement.colorSpace ?? "Material-defined"} />
                  <Metadata
                    label="Alpha / dependencies"
                    value={
                      replacement.hasAlpha !== null
                        ? replacement.hasAlpha
                          ? "Alpha"
                          : "Opaque"
                        : `${replacement.dependencies.length} referenced`
                    }
                  />
                </div>
                {replacement.probableNormalMap && (
                  <p className="warning">Normal-map naming detected; linear color and BC5 output will be used.</p>
                )}
                {replacement.warnings.map((warning) => (
                  <p className="warning" key={warning}>{warning}</p>
                ))}
                <div className="confirm-panel">
                  <div>
                    <strong>Confirm this visual mapping</strong>
                    <span>
                      {activeProject
                        ? `Adds it to ${activeProject.displayName}; compilation runs during Build & Export.`
                        : "Create or select a project first."}
                    </span>
                  </div>
                  <button
                    className="primary"
                    disabled={!activeProject || Boolean(operation)}
                    onClick={() => void confirm()}
                  >
                    <Plus size={15} /> Confirm replacement
                  </button>
                </div>
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}

function Metadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="metadata">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ProcessingEditor({
  processing,
  looping,
  onProcessing,
  onLooping
}: {
  processing: ProcessingSettings;
  looping: LoopSettings;
  onProcessing: (value: ProcessingSettings) => void;
  onLooping: (value: LoopSettings) => void;
}) {
  const number = (key: keyof ProcessingSettings, nullable = false) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const raw = event.currentTarget.value;
    onProcessing({ ...processing, [key]: nullable && raw === "" ? null : Number(raw) });
  };
  return (
    <details className="processing" open>
      <summary>
        <span><Settings2 size={16} /> Processing settings</span>
        <ChevronDown size={16} />
      </summary>
      <div className="form-grid">
        <label>Trim start (s)<input type="number" min="0" step="0.01" value={processing.trimStartSeconds} onChange={number("trimStartSeconds")} /></label>
        <label>Trim end (s)<input type="number" min="0" step="0.01" value={processing.trimEndSeconds ?? ""} onChange={number("trimEndSeconds", true)} placeholder="End" /></label>
        <label>Fade in (s)<input type="number" min="0" step="0.01" value={processing.fadeInSeconds} onChange={number("fadeInSeconds")} /></label>
        <label>Fade out (s)<input type="number" min="0" step="0.01" value={processing.fadeOutSeconds} onChange={number("fadeOutSeconds")} /></label>
        <label>Gain (dB)<input type="number" min="-60" max="30" step="0.5" value={processing.gainDb} onChange={number("gainDb")} /></label>
        <label>Sample rate<select value={processing.sampleRate ?? ""} onChange={(event) => onProcessing({ ...processing, sampleRate: event.target.value ? Number(event.target.value) : null })}><option value="">Keep source</option><option value="44100">44,100 Hz</option><option value="48000">48,000 Hz</option></select></label>
        <label>Channels<select value={processing.channels ?? ""} onChange={(event) => onProcessing({ ...processing, channels: event.target.value ? Number(event.target.value) : null })}><option value="">Keep source</option><option value="1">Mono</option><option value="2">Stereo</option></select></label>
        <label className="check"><input type="checkbox" checked={processing.normalize} onChange={(event) => onProcessing({ ...processing, normalize: event.target.checked })} /> Loudness normalization</label>
        <label className="check"><input type="checkbox" checked={processing.autoTrimSilence} onChange={(event) => onProcessing({ ...processing, autoTrimSilence: event.target.checked })} /> Automatic silence trim</label>
        <label className="check"><input type="checkbox" checked={looping.enabled} onChange={(event) => onLooping({ ...looping, enabled: event.target.checked })} /> Looping sound</label>
        {looping.enabled && (
          <>
            <label>Loop start (s)<input type="number" min="0" step="0.001" value={looping.startSeconds ?? ""} onChange={(event) => onLooping({ ...looping, startSeconds: event.target.value ? Number(event.target.value) : null })} /></label>
            <label>Loop end (s)<input type="number" min="0" step="0.001" value={looping.endSeconds ?? ""} onChange={(event) => onLooping({ ...looping, endSeconds: event.target.value ? Number(event.target.value) : null })} /></label>
          </>
        )}
      </div>
      <button className="text-button" onClick={() => { onProcessing({ ...DEFAULT_PROCESSING }); onLooping({ ...DEFAULT_LOOP }); }}>
        Reset processing settings
      </button>
    </details>
  );
}

function ProjectsPage({
  projects,
  activeProject,
  onSelect,
  onProjectChanged,
  onProjectDeleted,
  onNavigate,
  onExportProject,
  onOpenBuild,
  onNotice
}: {
  projects: ProjectSummary[];
  activeProject: ProjectManifest | null;
  onSelect: (project: ProjectSummary) => void;
  onProjectChanged: (project: ProjectManifest) => void;
  onProjectDeleted: (projectId: string) => void;
  onNavigate: (view: View) => void;
  onExportProject: (project: ProjectSummary) => void;
  onOpenBuild: () => void;
  onNotice: (message: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [expandedItem, setExpandedItem] = useState<string | null>(null);
  const [compatibility, setCompatibility] = useState<CompatibilityReport | null>(null);
  const [checkingCompatibility, setCheckingCompatibility] = useState(false);
  const [projectOperation, setProjectOperation] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ProjectSummary | null>(null);
  const [repairing, setRepairing] = useState(false);
  const projectBusy = creating || checkingCompatibility || repairing || Boolean(projectOperation);

  useEffect(() => {
    setCompatibility(null);
    setExpandedItem(null);
  }, [activeProject?.id]);

  async function create() {
    if (!name.trim()) return;
    setCreating(true);
    setProjectOperation("Creating project…");
    try {
      const project = await window.studio.backend<ProjectManifest>("projects.create", {
        displayName: name.trim(),
        description: "",
        author: ""
      });
      onProjectChanged(project);
      setName("");
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setCreating(false);
      setProjectOperation(null);
    }
  }

  async function deleteProject(project: ProjectSummary) {
    setPendingDelete(null);
    setProjectOperation(`Moving ${project.displayName} to recovery backups…`);
    try {
      const result = await window.studio.backend<{ projectId: string; backupPath: string }>(
        "projects.delete",
        { projectId: project.id }
      );
      onProjectDeleted(result.projectId);
      onNotice(`Deleted ${project.displayName}. Recovery copy: ${result.backupPath}`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  async function toggle(itemId: string, enabled: boolean) {
    if (!activeProject) return;
    setProjectOperation(enabled ? "Enabling replacement…" : "Disabling replacement…");
    try {
      const project = await window.studio.backend<ProjectManifest>("projects.updateReplacement", {
        projectId: activeProject.id,
        itemId,
        changes: { enabled }
      });
      onProjectChanged(project);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  async function remove(itemId: string) {
    if (!activeProject) return;
    setProjectOperation("Removing replacement…");
    try {
      const project = await window.studio.backend<ProjectManifest>("projects.removeReplacement", {
        projectId: activeProject.id,
        itemId
      });
      onProjectChanged(project);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  async function toggleVisual(itemId: string, enabled: boolean) {
    if (!activeProject) return;
    setProjectOperation(enabled ? "Enabling visual replacement…" : "Disabling visual replacement…");
    try {
      const project = await window.studio.backend<ProjectManifest>(
        "projects.updateVisualReplacement",
        { projectId: activeProject.id, itemId, changes: { enabled } }
      );
      onProjectChanged(project);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  async function removeVisual(itemId: string) {
    if (!activeProject) return;
    setProjectOperation("Removing visual replacement…");
    try {
      const project = await window.studio.backend<ProjectManifest>(
        "projects.removeVisualReplacement",
        { projectId: activeProject.id, itemId }
      );
      onProjectChanged(project);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  async function move(itemId: string, nextIndex: number) {
    if (!activeProject) return;
    setProjectOperation("Reordering replacement queue…");
    try {
      const project = await window.studio.backend<ProjectManifest>("projects.reorderReplacement", {
        projectId: activeProject.id,
        itemId,
        newIndex: nextIndex
      });
      onProjectChanged(project);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  async function checkCompatibility() {
    if (!activeProject) return;
    setCheckingCompatibility(true);
    setProjectOperation("Comparing the queue with the current game index…");
    try {
      const report = await window.studio.backend<CompatibilityReport>(
        "projects.compatibility",
        { projectId: activeProject.id }
      );
      setCompatibility(report);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setCheckingCompatibility(false);
      setProjectOperation(null);
    }
  }

  async function remapTarget(itemId: string, asset: SoundAsset) {
    if (!activeProject) return;
    setProjectOperation(`Remapping target to ${asset.filename}…`);
    try {
      const project = await window.studio.backend<ProjectManifest>(
        "projects.remapTarget",
        {
          projectId: activeProject.id,
          itemId,
          assetId: asset.id
        }
      );
      onProjectChanged(project);
      const report = await window.studio.backend<CompatibilityReport>(
        "projects.compatibility",
        { projectId: project.id }
      );
      setCompatibility(report);
      onNotice(`Remapped the replacement target to ${asset.internalPath}.`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setProjectOperation(null);
    }
  }

  // Re-points every repairable item at its best current match. Rows the backend
  // could not find a candidate for are left alone and reported, so a partial
  // repair never looks like a complete one.
  async function repairStaleTargets() {
    if (!activeProject || !compatibility) return;
    const repairable = compatibility.rows.filter(
      (row) => row.status !== "exactMatch" && row.candidates.length > 0
    );
    const unrepairable = compatibility.rows.filter(
      (row) => row.status !== "exactMatch" && row.candidates.length === 0
    );
    if (repairable.length === 0) {
      onNotice("No replacement targets could be matched automatically.");
      return;
    }
    setRepairing(true);
    let repaired = 0;
    try {
      for (const [index, row] of repairable.entries()) {
        setProjectOperation(`Re-pointing ${index + 1} of ${repairable.length} replacements…`);
        await window.studio.backend<ProjectManifest>("projects.remapTarget", {
          projectId: activeProject.id,
          itemId: row.itemId,
          assetId: row.candidates[0].asset.id
        });
        repaired += 1;
      }
      setProjectOperation("Re-checking against the current game index…");
      const project = await window.studio.backend<ProjectManifest>("projects.get", {
        projectId: activeProject.id
      });
      onProjectChanged(project);
      const report = await window.studio.backend<CompatibilityReport>(
        "projects.compatibility",
        { projectId: project.id }
      );
      setCompatibility(report);
      onNotice(
        unrepairable.length
          ? `Re-pointed ${repaired} replacement${repaired === 1 ? "" : "s"}. ${unrepairable.length} still need a target chosen by hand.`
          : `Re-pointed ${repaired} replacement${repaired === 1 ? "" : "s"}. Rebuild to export an updated VPK.`
      );
      if (!unrepairable.length) onOpenBuild();
    } catch (error) {
      onNotice(`Repaired ${repaired} of ${repairable.length} before failing: ${errorMessage(error)}`);
    } finally {
      setRepairing(false);
      setProjectOperation(null);
    }
  }

  return (
    <div className="projects-layout">
      <ActivityBar
        active={projectBusy}
        label={projectOperation ?? "Updating project…"}
      />
      <section className="card project-list" data-tutorial="project-create">
        <div className="section-heading"><div><h3>Projects</h3></div></div>
        <div className="inline-create">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="My mod" onKeyDown={(event) => event.key === "Enter" && void create()} />
          <button className="primary" disabled={projectBusy || !name.trim()} onClick={() => void create()}><Plus size={15} /> Create</button>
        </div>
        <div className="project-items">
          {projects.map((project) => (
            <div className="project-row" key={project.id}>
              <button
                disabled={projectBusy}
                className={`project-select ${activeProject?.id === project.id ? "selected" : ""}`}
                onClick={() => onSelect(project)}
              >
                <span><strong>{project.displayName}</strong><small>{project.enabledCount} enabled · {project.replacementCount} total</small></span>
                <StatusBadge status={project.lastBuildSuccess === false ? "invalid" : "found"} />
              </button>
              <button
                className="icon-button export-project"
                disabled={projectBusy}
                title={`Build and export ${project.displayName}`}
                aria-label={`Build and export ${project.displayName}`}
                onClick={() => onExportProject(project)}
              >
                <PackageCheck size={15} />
              </button>
              <button
                className="icon-button delete-project"
                disabled={projectBusy}
                title={`Delete ${project.displayName}`}
                aria-label={`Delete ${project.displayName}`}
                onClick={() => setPendingDelete(project)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          {!projects.length && <div className="empty compact"><Box size={24} /><strong>No projects yet</strong></div>}
        </div>
      </section>
      <section className="card queue" data-tutorial="project-build">
        {!activeProject ? (
          <div className="empty"><Layers3 size={30} /><strong>Choose or create a project</strong><span>Confirmed replacements appear here.</span></div>
        ) : (
          <>
            <div className="section-heading">
              <div><h3>{activeProject.displayName}</h3><p>{activeProject.targetAssets.length + activeProject.visualAssets.length} confirmed mappings</p></div>
              <div className="button-row">
                <button onClick={() => void checkCompatibility()} disabled={checkingCompatibility || !activeProject.targetAssets.length}>
                  <ShieldCheck size={15} /> Check game update
                </button>
                <button
                  className="primary"
                  disabled={
                    !activeProject.targetAssets.some((item) => item.enabled) &&
                    !activeProject.visualAssets.some((item) => item.enabled)
                  }
                  onClick={onOpenBuild}
                >
                  <PackageCheck size={15} /> Build & export
                </button>
                <button onClick={() => onNavigate("sounds")}><Plus size={15} /> Add sounds</button>
                <button onClick={() => onNavigate("visuals")}><ImageIcon size={15} /> Add visuals</button>
              </div>
            </div>
            <div className="package-modes">
              <label><input type="radio" checked readOnly /> Single VPK</label>
              <label className="disabled"><input type="radio" disabled /> Split by hero · planned</label>
              <label className="disabled"><input type="radio" disabled /> Split by category · planned</label>
            </div>
            {compatibility && (
              <div className="compatibility-panel">
                <div className="compatibility-summary">
                  <strong>Current catalog comparison</strong>
                  <span>{compatibility.counts.exactMatch} exact</span>
                  <span>{compatibility.counts.changedAsset} changed</span>
                  <span>{compatibility.counts.missing} missing</span>
                  {compatibility.rows.some(
                    (row) => row.status !== "exactMatch" && row.candidates.length > 0
                  ) && (
                    <button
                      className="primary"
                      disabled={projectBusy}
                      onClick={() => void repairStaleTargets()}
                    >
                      <Wrench size={14} /> Repair and rebuild
                    </button>
                  )}
                </div>
                {compatibility.rows
                  .filter((row) => row.status !== "exactMatch")
                  .map((row) => (
                    <div className="compatibility-row" key={row.itemId}>
                      <StatusBadge status={row.status} />
                      <code>{row.targetPath}</code>
                      {row.candidates.length ? (
                        <div className="candidate-stack">
                          {row.candidates.map((candidate) => (
                            <div key={candidate.asset.id}>
                              <span>
                                {candidate.asset.internalPath} ·{" "}
                                {Math.round(candidate.score * 100)}% match
                              </span>
                              <button
                                disabled={projectBusy}
                                onClick={() =>
                                  void remapTarget(row.itemId, candidate.asset)
                                }
                              >
                                Approve remap
                              </button>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span>
                          {row.status === "changedAsset"
                            ? "The path still exists, but its archive fingerprint changed."
                            : "No same-filename relocation candidate was found."}
                        </span>
                      )}
                    </div>
                  ))}
                {!compatibility.counts.changedAsset && !compatibility.counts.missing && (
                  <p>Every queued target still matches the current indexed game archive.</p>
                )}
              </div>
            )}
            <div className="queue-items">
              {activeProject.targetAssets.map((item, index) => (
                <article key={item.id} className={!item.enabled ? "disabled-item" : ""}>
                  <div className="queue-item-row">
                    <label className="enable"><input type="checkbox" disabled={projectBusy} checked={item.enabled} onChange={(event) => void toggle(item.id, event.target.checked)} /></label>
                    <span className="queue-number">{index + 1}</span>
                    <div className="queue-main">
                      <strong>{item.target.filename}</strong>
                      <code>{item.target.internalPath}</code>
                      <span>{item.sourceFilename} · {formatDuration(item.sourceMetadata.durationMs)}</span>
                      {item.validationMessages.map((message) => <em key={message}>{message}</em>)}
                    </div>
                    <div className="queue-status">
                      <StatusBadge status={item.status} />
                      {item.looping.enabled && <StatusBadge status="loop" />}
                    </div>
                    <div className="queue-actions">
                      <button className="icon-button" onClick={() => setExpandedItem(expandedItem === item.id ? null : item.id)} title="Edit source and settings"><Settings2 size={14} /></button>
                      <button className="icon-button" disabled={projectBusy || index === 0} onClick={() => void move(item.id, index - 1)} title="Move up"><ChevronUp size={14} /></button>
                      <button className="icon-button" disabled={projectBusy || index === activeProject.targetAssets.length - 1} onClick={() => void move(item.id, index + 1)} title="Move down"><ChevronDown size={14} /></button>
                      <button className="icon-button danger" disabled={projectBusy} onClick={() => void remove(item.id)} title="Remove"><Trash2 size={14} /></button>
                    </div>
                  </div>
                  {expandedItem === item.id && (
                    <QueueEditor
                      project={activeProject}
                      item={item}
                      onProjectChanged={onProjectChanged}
                      onNotice={onNotice}
                    />
                  )}
                </article>
              ))}
              {!activeProject.targetAssets.length && activeProject.visualAssets.length > 0 && <div className="empty compact"><AudioLines size={24} /><strong>No sound replacements</strong><button onClick={() => onNavigate("sounds")}>Browse indexed sounds</button></div>}
              {activeProject.visualAssets.length > 0 && (
                <div className="queue-group-label">
                  <ImageIcon size={14} />
                  Visual replacements
                </div>
              )}
              {activeProject.visualAssets.map((item) => (
                <article key={item.id} className={!item.enabled ? "disabled-item" : ""}>
                  <div className="queue-item-row visual-queue-row">
                    <label className="enable">
                      <input
                        type="checkbox"
                        disabled={projectBusy}
                        checked={item.enabled}
                        onChange={(event) => void toggleVisual(item.id, event.target.checked)}
                      />
                    </label>
                    <span className="queue-number"><ImageIcon size={13} /></span>
                    <div className="queue-main">
                      <strong>{item.target.filename}</strong>
                      <code>{item.target.internalPath}</code>
                      <span>
                        {item.sourceFilename} · {item.target.kind}
                        {item.sourceMetadata.width && item.sourceMetadata.height
                          ? ` · ${item.sourceMetadata.width} × ${item.sourceMetadata.height}`
                          : ""}
                      </span>
                      {item.validationMessages.map((message) => <em key={message}>{message}</em>)}
                    </div>
                    <div className="queue-status"><StatusBadge status={item.status} /></div>
                    <div className="queue-actions">
                      <button
                        className="icon-button danger"
                        disabled={projectBusy}
                        onClick={() => void removeVisual(item.id)}
                        title="Remove visual replacement"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </article>
              ))}
              {!activeProject.targetAssets.length && !activeProject.visualAssets.length && (
                <div className="empty">
                  <Layers3 size={26} />
                  <strong>The replacement queue is empty</strong>
                  <span>Add a sound, texture, or material.</span>
                </div>
              )}
            </div>
            <div className="queue-footer"><span>{activeProject.targetAssets.filter((item) => item.enabled).length + activeProject.visualAssets.filter((item) => item.enabled).length} enabled for the next build</span><button className="primary" disabled={!activeProject.targetAssets.some((item) => item.enabled) && !activeProject.visualAssets.some((item) => item.enabled)} onClick={onOpenBuild}><PackageCheck size={15} /> Build & export</button></div>
          </>
        )}
      </section>

      {pendingDelete && (
        <ConfirmDialog
          title={`Delete ${pendingDelete.displayName}?`}
          body="The project is moved to the recovery backups folder, so it can be restored later. Exported VPKs are left untouched."
          confirmLabel="Delete project"
          destructive
          busy={Boolean(projectOperation)}
          onConfirm={() => void deleteProject(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}

function QueueEditor({
  project,
  item,
  onProjectChanged,
  onNotice
}: {
  project: ProjectManifest;
  item: ProjectManifest["targetAssets"][number];
  onProjectChanged: (project: ProjectManifest) => void;
  onNotice: (message: string | null) => void;
}) {
  const [processing, setProcessing] = useState<ProcessingSettings>(item.processing);
  const [looping, setLooping] = useState<LoopSettings>(item.looping);
  const [copyFrom, setCopyFrom] = useState("");
  const [operation, setOperation] = useState<string | null>(null);
  const saving = Boolean(operation);

  useEffect(() => {
    setProcessing(item.processing);
    setLooping(item.looping);
  }, [item.id, item.processing, item.looping]);

  async function saveSettings() {
    setOperation("Saving processing settings…");
    try {
      const updated = await window.studio.backend<ProjectManifest>(
        "projects.updateReplacement",
        {
          projectId: project.id,
          itemId: item.id,
          changes: { processing, looping }
        }
      );
      onProjectChanged(updated);
      onNotice(`Saved processing settings for ${item.target.filename}.`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function replaceSource() {
    const sourcePath = await window.studio.selectAudio();
    if (!sourcePath) return;
    setOperation("Inspecting and replacing source audio…");
    try {
      const updated = await window.studio.backend<ProjectManifest>("projects.replaceSource", {
        projectId: project.id,
        itemId: item.id,
        sourcePath
      });
      onProjectChanged(updated);
      onNotice(`Replaced the source audio for ${item.target.filename}.`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function duplicateSettings() {
    if (!copyFrom) return;
    setOperation("Copying processing settings…");
    try {
      const updated = await window.studio.backend<ProjectManifest>(
        "projects.duplicateSettings",
        {
          projectId: project.id,
          sourceItemId: copyFrom,
          targetItemId: item.id
        }
      );
      onProjectChanged(updated);
      onNotice(`Copied processing and loop settings to ${item.target.filename}.`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  const otherItems = project.targetAssets.filter((candidate) => candidate.id !== item.id);
  return (
    <div className="queue-editor">
      <ActivityBar active={saving} label={operation ?? ""} />
      <ProcessingEditor
        processing={processing}
        looping={looping}
        onProcessing={setProcessing}
        onLooping={setLooping}
      />
      <div className="queue-editor-actions">
        <button onClick={() => void replaceSource()} disabled={saving}>
          <FileAudio size={14} /> Choose new source
        </button>
        <select value={copyFrom} onChange={(event) => setCopyFrom(event.target.value)}>
          <option value="">Copy settings from…</option>
          {otherItems.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.target.filename}
            </option>
          ))}
        </select>
        <button onClick={() => void duplicateSettings()} disabled={saving || !copyFrom}>
          <Copy size={14} /> Copy settings
        </button>
        <button className="primary" onClick={() => void saveSettings()} disabled={saving}>
          <Settings2 size={14} /> Save settings
        </button>
      </div>
    </div>
  );
}

function BuildExportModal({
  project,
  diagnostics,
  progress,
  onProgress,
  onClose,
  onProjectChanged,
  onNotice
}: {
  project: ProjectManifest;
  diagnostics: Diagnostics;
  progress: BuildProgress | null;
  onProgress: (progress: BuildProgress | null) => void;
  onClose: () => void;
  onProjectChanged: (project: ProjectManifest) => void;
  onNotice: (message: string | null) => void;
}) {
  const [locked, setLocked] = useState(false);
  const [result, setResult] = useState<BuildResult | null>(null);

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal-shell build-export-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="build-export-title"
      >
        <header className="modal-header">
          <div>
            <h2 id="build-export-title">
              {result
                ? result.success
                  ? "Export complete"
                  : "Export failed"
                : `Build & export ${project.displayName}`}
            </h2>
            <p>
              {result
                ? result.success
                  ? `${project.displayName} packaged as a VPK. Open the folder below to collect it.`
                  : `${project.displayName} did not finish. The details below show what stopped it.`
                : "Process the enabled replacements and package them into a VPK."}
            </p>
          </div>
          <button
            className="icon-button"
            aria-label="Close build and export"
            title={locked ? "Wait for the current operation to finish" : "Close"}
            disabled={locked}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>
        <div className="modal-scroll">
          <BuildPage
            activeProject={project}
            diagnostics={diagnostics}
            progress={progress}
            onProgress={onProgress}
            onProjectChanged={onProjectChanged}
            onNotice={onNotice}
            onBuildingChange={setLocked}
            onResult={setResult}
          />
        </div>
      </section>
    </div>
  );
}

function BuildPage({
  activeProject,
  diagnostics,
  progress,
  onProgress,
  onProjectChanged,
  onNotice,
  onBuildingChange,
  onResult
}: {
  activeProject: ProjectManifest | null;
  diagnostics: Diagnostics;
  progress: BuildProgress | null;
  onProgress: (progress: BuildProgress | null) => void;
  onProjectChanged: (project: ProjectManifest) => void;
  onNotice: (message: string | null) => void;
  onBuildingChange?: (building: boolean) => void;
  onResult?: (result: BuildResult | null) => void;
}) {
  const [building, setBuilding] = useState(false);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [exportOperation, setExportOperation] = useState<string | null>(null);
  const percent = progress?.total ? Math.round((progress.completed / progress.total) * 100) : 0;

  useEffect(() => {
    onBuildingChange?.(building || Boolean(exportOperation));
  }, [building, exportOperation, onBuildingChange]);

  useEffect(() => {
    onResult?.(result);
  }, [result, onResult]);
  async function build(retryFailedOnly = false) {
    if (!activeProject) return;
    const job = crypto.randomUUID();
    const retryCount = [...activeProject.targetAssets, ...activeProject.visualAssets].filter(
      (item) => item.enabled && item.status === "failed"
    ).length;
    setJobId(job);
    setBuilding(true);
    setResult(null);
    onProgress({ event: "build.progress", jobId: job, stage: retryFailedOnly ? "retry" : "validate", completed: 0, total: retryFailedOnly ? retryCount : [...activeProject.targetAssets, ...activeProject.visualAssets].filter((item) => item.enabled).length, currentItem: null });
    try {
      const output = await window.studio.backend<BuildResult>("build.start", {
        projectId: activeProject.id,
        jobId: job,
        retryFailedOnly
      });
      setResult(output);
      const project = await window.studio.backend<ProjectManifest>("projects.get", { projectId: activeProject.id });
      onProjectChanged(project);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setBuilding(false);
    }
  }
  async function cancel() {
    if (!jobId) return;
    setExportOperation("Cancelling build…");
    try {
      await window.studio.backend("build.cancel", { jobId });
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setExportOperation(null);
    }
  }
  async function validate() {
    if (!activeProject) return;
    setExportOperation("Validating exported VPK contents…");
    try {
      const validation = await window.studio.backend<{ valid: boolean; entryCount: number }>("build.validateExport", { projectId: activeProject.id });
      onNotice(validation.valid ? `Validation passed: ${validation.entryCount} exact VPK entries.` : "Export validation failed.");
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setExportOperation(null);
    }
  }
  async function zip() {
    if (!activeProject || !result?.success) return;
    setExportOperation("Creating sharing ZIP…");
    try {
      const created = await window.studio.backend<{ path: string }>("export.createZip", { projectId: activeProject.id, version: result.version });
      onNotice(`Created sharing ZIP: ${created.path}`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setExportOperation(null);
    }
  }
  async function compatibilityCopy() {
    if (!activeProject || !result?.success) return;
    setExportOperation("Creating compatibility copy…");
    try {
      const created = await window.studio.backend<{ path: string }>(
        "export.createCompatibilityCopy",
        { projectId: activeProject.id, version: result.version }
      );
      onNotice(`Created optional compatibility copy: ${created.path}`);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setExportOperation(null);
    }
  }
  const enabledSoundCount =
    activeProject?.targetAssets.filter((item) => item.enabled).length ?? 0;
  const enabledVisualCount =
    activeProject?.visualAssets.filter((item) => item.enabled).length ?? 0;
  const canBuildProject =
    diagnostics.canCompile &&
    diagnostics.canPackageHeadlessly &&
    (enabledSoundCount === 0 || diagnostics.canProcessAudio);
  const blockers = diagnostics.checks.filter(
    (check) =>
      check.status !== "found" &&
      ["resourceCompiler", "vpkUtility", ...(enabledSoundCount ? ["ffmpeg", "ffprobe"] : [])].includes(
        check.id
      )
  );
  return (
    <div className="page-stack narrow">
      {result && (
        <section className={`card result-card ${result.success ? "success" : "failed"}`}>
          <div className="section-heading">
            <div>
              <h3>{result.success ? "Export complete" : "Export failed"}</h3>
              <p>{result.message}</p>
            </div>
            <StatusBadge status={result.success ? "found" : "invalid"} />
          </div>
          {result.warnings.map((warning) => (
            <p className="warning" key={warning}>{warning}</p>
          ))}
          <div className="button-row">
            {!result.success && result.itemResults.some((item) => item.status === "failed") && (
              <button
                className="primary"
                disabled={building || Boolean(exportOperation)}
                onClick={() => void build(true)}
              >
                <RefreshCw size={15} /> Retry failed items
              </button>
            )}
            {!result.success && !result.itemResults.some((item) => item.status === "failed") && (
              <button
                className="primary"
                disabled={building || Boolean(exportOperation)}
                onClick={() => void build(false)}
              >
                <RefreshCw size={15} /> Restart build
              </button>
            )}
            {result.exportDirectory && (
              <button className="primary" onClick={() => void window.studio.openPath(result.exportDirectory!)}>
                <FolderOpen size={15} /> Open export folder
              </button>
            )}
            {result.success && <button disabled={Boolean(exportOperation)} onClick={() => void validate()}>Validate again</button>}
            {result.success && <button disabled={Boolean(exportOperation)} onClick={() => void zip()}>Create ZIP</button>}
            {result.success && <button disabled={Boolean(exportOperation)} onClick={() => void compatibilityCopy()}>Create pak01_dir.vpk copy</button>}
            {result.guidedFallbackDirectory && (
              <button onClick={() => void window.studio.openPath(result.guidedFallbackDirectory!)}>
                Open prepared staging
              </button>
            )}
          </div>
        </section>
      )}
      <section className="card build-card">
        <div className="section-heading"><div><h2>{activeProject?.displayName ?? "Choose a project to export."}</h2></div><PackageCheck size={28} /></div>
        {!activeProject && <div className="empty compact"><Box size={24} /><strong>No active project</strong><span>Select one on Projects.</span></div>}
        {activeProject && <div className="build-summary"><Metadata label="Enabled resources" value={(enabledSoundCount + enabledVisualCount).toString()} /><Metadata label="Sounds / visuals" value={`${enabledSoundCount} / ${enabledVisualCount}`} /><Metadata label="Prior builds" value={activeProject.buildHistory.length.toString()} /><Metadata label="Readiness" value={canBuildProject ? "Ready" : "Blocked"} /></div>}
        {blockers.length > 0 && <div className="blockers">{blockers.map((blocker) => <div key={blocker.id}><StatusBadge status={blocker.status} /><span>{blocker.label}: {blocker.detail}</span></div>)}</div>}
        {building && progress && <div className="progress-panel"><div><strong>{progress.stage.replace(/([A-Z])/g, " $1")}</strong><span>{progress.completed}/{progress.total} · {progress.currentItem ?? "Project"}</span></div><div className="progress-track"><span style={{ width: `${percent}%` }} /></div></div>}
        <ActivityBar active={Boolean(exportOperation)} label={exportOperation ?? ""} />
        <div className="button-row">
          <button className="primary" disabled={!activeProject || !canBuildProject || building || Boolean(exportOperation) || enabledSoundCount + enabledVisualCount === 0} onClick={() => void build(false)}><PackageCheck size={16} /> Process project</button>
          {building && <button className="danger-button" disabled={Boolean(exportOperation)} onClick={() => void cancel()}><X size={15} /> Cancel build</button>}
        </div>
      </section>
      {result?.itemResults.length ? (
        <section className="card item-build-results">
          <div className="section-heading">
            <div>
              <h3>Build details</h3>
              <p>Inspect compiler runs for each replacement. A JSON report is saved only when a build fails.</p>
            </div>
            {result.itemLogPath && (
              <button onClick={() => void window.studio.openPath(result.itemLogPath!)}>
                <FolderOpen size={14} /> Open failure report
              </button>
            )}
          </div>
          <div className="item-log-list">
            {result.itemResults.map((item) => (
              <details key={item.itemId}>
                <summary>
                  <StatusBadge status={item.status} />
                  <code>{item.targetPath}</code>
                  <span>
                    {item.reusedCompiledOutput
                      ? "Reused verified compiled output"
                      : `${item.processRecords.length} tool run${item.processRecords.length === 1 ? "" : "s"}`}
                  </span>
                </summary>
                {item.error && <p className="warning">{item.error}</p>}
                {item.processRecords.map((record, index) => (
                  <div className="process-log" key={`${record.startedAt}-${index}`}>
                    <div>
                      <strong>{record.executablePath.split(/[\\/]/).pop()}</strong>
                      <span>Exit {record.exitCode ?? "-"} · {record.durationMs} ms</span>
                    </div>
                    <code>{record.sanitizedArguments.join(" ")}</code>
                    {record.stdout && <pre><strong>stdout</strong>{record.stdout.slice(-12000)}</pre>}
                    {record.stderr && <pre><strong>stderr</strong>{record.stderr.slice(-12000)}</pre>}
                  </div>
                ))}
              </details>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function PackageCombinerPage({
  progress,
  onProgressReset,
  onNotice
}: {
  progress: PackageProgress | null;
  onProgressReset: () => void;
  onNotice: (message: string | null) => void;
}) {
  const [packages, setPackages] = useState<PackageInventory[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [combining, setCombining] = useState(false);
  const [result, setResult] = useState<PackageCombineResult | null>(null);

  const duplicatePaths = useMemo(() => {
    const owners = new Map<string, { path: string; packages: string[] }>();
    for (const packageFile of packages) {
      for (const entry of packageFile.entries) {
        const key = entry.path.toLowerCase();
        const existing = owners.get(key);
        if (existing) existing.packages.push(packageFile.filename);
        else owners.set(key, { path: entry.path, packages: [packageFile.filename] });
      }
    }
    return [...owners.values()].filter((entry) => entry.packages.length > 1);
  }, [packages]);

  const totalEntries = packages.reduce((total, packageFile) => total + packageFile.entryCount, 0);

  async function choosePackages() {
    try {
      const selected = await window.studio.selectPackages();
      if (!selected.length) return;
      const paths = [
        ...packages.map((packageFile) => packageFile.path),
        ...selected.filter(
          (value) =>
            !packages.some(
              (packageFile) => packageFile.path.toLowerCase() === value.toLowerCase()
            )
        )
      ];
      setLoading(true);
      setResult(null);
      const inspected = await window.studio.backend<PackageInventory[]>("packages.inspect", {
        paths
      });
      setPackages(inspected);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  function removePackage(index: number) {
    setPackages((current) => current.filter((_, currentIndex) => currentIndex !== index));
    setResult(null);
  }

  function movePackage(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= packages.length) return;
    setPackages((current) => {
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setResult(null);
  }

  async function combine() {
    try {
      const outputPath = await window.studio.selectPackageOutput();
      if (!outputPath) return;
      onProgressReset();
      setCombining(true);
      setResult(null);
      const combined = await window.studio.backend<PackageCombineResult>("packages.combine", {
        paths: packages.map((packageFile) => packageFile.path),
        outputPath
      });
      setResult(combined);
      onNotice(null);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setCombining(false);
    }
  }

  const progressTotal = progress?.total || 1;
  const progressCompleted = Math.min(progress?.completed ?? 0, progressTotal);
  const progressPercent = Math.round((progressCompleted / progressTotal) * 100);

  return (
    <div className="page-stack package-combiner-page">
      <PageHeading
        title="Inspect and combine PAK files"
        description="Add multiple Valve-format .vpk or .pak files. Every internal item is listed before the packages are merged into one single-file VPK."
        actions={
          <>
            {packages.length > 0 && (
              <button
                disabled={loading || combining}
                onClick={() => {
                  setPackages([]);
                  setResult(null);
                }}
              >
                <Trash2 size={15} /> Clear
              </button>
            )}
            <button className="primary" disabled={loading || combining} onClick={() => void choosePackages()}>
              <FileArchive size={15} /> Add PAK files
            </button>
          </>
        }
      />

      <ActivityBar active={loading} label="Reading package directories…" />

      {packages.length === 0 && !loading ? (
        <section className="card empty package-empty">
          <PackageOpen size={28} />
          <strong>No packages selected</strong>
          <span>Add two or more .vpk or Valve-format .pak files to inspect their contents.</span>
          <button className="primary" onClick={() => void choosePackages()}>
            <FileArchive size={15} /> Choose package files
          </button>
        </section>
      ) : (
        <>
          <section className="package-summary card">
            <Metadata label="Packages" value={packages.length.toString()} />
            <Metadata label="Listed items" value={totalEntries.toLocaleString()} />
            <Metadata label="Overridden paths" value={duplicatePaths.length.toLocaleString()} />
            <label className="package-search">
              <Search size={14} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Filter internal items"
                aria-label="Filter package items"
              />
            </label>
          </section>

          <div className="package-file-list">
            {packages.map((packageFile, index) => {
              const normalizedSearch = search.trim().toLowerCase();
              const matchingEntries = packageFile.entries.filter(
                (entry) => !normalizedSearch || entry.path.toLowerCase().includes(normalizedSearch)
              );
              const shownEntries = matchingEntries.slice(0, 500);
              return (
                <article className="package-file card" key={packageFile.path}>
                  <header className="package-file-head">
                    <FileArchive size={20} />
                    <div>
                      <strong>{packageFile.filename}</strong>
                      <code title={packageFile.path}>{packageFile.path}</code>
                    </div>
                    <span>
                      {packageFile.entryCount.toLocaleString()} items · {formatBytes(packageFile.sizeBytes)}
                    </span>
                    <div className="package-order-actions">
                      <button
                        className="icon-button"
                        title="Move package up"
                        aria-label={`Move ${packageFile.filename} up`}
                        disabled={index === 0 || combining}
                        onClick={() => movePackage(index, -1)}
                      >
                        <ArrowUp size={14} />
                      </button>
                      <button
                        className="icon-button"
                        title="Move package down"
                        aria-label={`Move ${packageFile.filename} down`}
                        disabled={index === packages.length - 1 || combining}
                        onClick={() => movePackage(index, 1)}
                      >
                        <ArrowDown size={14} />
                      </button>
                      <button
                        className="icon-button danger"
                        title="Remove package"
                        aria-label={`Remove ${packageFile.filename}`}
                        disabled={combining}
                        onClick={() => removePackage(index)}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </header>
                  <details className="package-contents" open>
                    <summary>
                      <span>Contents</span>
                      <small>
                        {matchingEntries.length.toLocaleString()} matching item
                        {matchingEntries.length === 1 ? "" : "s"}
                      </small>
                    </summary>
                    <div className="package-entry-list">
                      {shownEntries.map((entry) => (
                        <div className="package-entry" key={entry.path}>
                          <code title={entry.path}>{entry.path}</code>
                          <span>{formatBytes(entry.sizeBytes)}</span>
                        </div>
                      ))}
                      {matchingEntries.length === 0 && (
                        <div className="package-entry-empty">No internal items match this filter.</div>
                      )}
                    </div>
                    {matchingEntries.length > shownEntries.length && (
                      <p className="package-entry-limit">
                        Showing the first {shownEntries.length.toLocaleString()} matches. Narrow
                        the filter to inspect the remaining items.
                      </p>
                    )}
                  </details>
                </article>
              );
            })}
          </div>

          <section className="combine-panel card">
            <div>
              <h3>Merge order</h3>
              <p>
                Lower packages override matching paths above them.{" "}
                {duplicatePaths.length
                  ? `${duplicatePaths.length.toLocaleString()} internal path${duplicatePaths.length === 1 ? "" : "s"} will be overridden.`
                  : "No duplicate internal paths are currently present."}
              </p>
            </div>
            <button
              className="primary"
              disabled={packages.length < 2 || loading || combining}
              onClick={() => void combine()}
            >
              <Merge size={15} /> Combine into one package
            </button>
          </section>
        </>
      )}

      {combining && (
        <section className="progress-panel package-combine-progress" role="status" aria-live="polite">
          <div>
            <strong>{progress?.message ?? "Preparing package merge…"}</strong>
            <span>{progressCompleted}/{progressTotal}</span>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-label="Package merge progress"
            aria-valuemin={0}
            aria-valuemax={progressTotal}
            aria-valuenow={progressCompleted}
          >
            <span style={{ width: `${progressPercent}%` }} />
          </div>
        </section>
      )}

      {result && (
        <section className="result-card success package-result card">
          <div className="section-heading">
            <div>
              <h3>{result.entryCount.toLocaleString()} items written</h3>
              <p>
                {result.conflictCount.toLocaleString()} overridden path
                {result.conflictCount === 1 ? "" : "s"} · {formatBytes(result.sizeBytes)}
              </p>
            </div>
            <PackageCheck size={26} />
          </div>
          <code className="package-output-path">{result.outputPath}</code>
          <button onClick={() => void window.studio.openPath(result.outputPath)}>
            <FolderOpen size={15} /> Show combined package
          </button>
        </section>
      )}
    </div>
  );
}

function SetupWizard({
  diagnostics,
  settings,
  progress,
  requirementProgress,
  onScanStart,
  onComplete,
  onNotice
}: {
  diagnostics: Diagnostics;
  settings: Settings;
  progress: DiagnosticProgress | null;
  requirementProgress: RequirementProgress | null;
  onScanStart: () => void;
  onComplete: (diagnostics: Diagnostics, settings: Settings) => void;
  onNotice: (message: string | null) => void;
}) {
  const [completing, setCompleting] = useState(false);
  const [setupNotice, setSetupNotice] = useState<string | null>(null);
  const passed = diagnostics.checks.filter((check) => check.status === "found").length;
  const ready = passed === diagnostics.checks.length;

  async function finishSetup() {
    if (!ready) return;
    setCompleting(true);
    try {
      const next = { ...settings, setupCompleted: true };
      const report = await window.studio.backend<Diagnostics>("settings.save", next);
      onComplete(report, next);
      onNotice(null);
    } catch (error) {
      const message = errorMessage(error);
      setSetupNotice(message);
      onNotice(message);
    } finally {
      setCompleting(false);
    }
  }

  return (
    <div className="modal-backdrop setup-backdrop">
      <section
        className="modal-shell setup-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="setup-wizard-title"
      >
        <header className="modal-header setup-wizard-header">
          <div>
            <h2 id="setup-wizard-title">Set up required tools</h2>
            <p>
              Complete the checklist before entering the workspace. Locations are referenced in
              place and can be changed later from Diagnostics.
            </p>
          </div>
          <div className="setup-count" aria-label={`${passed} of ${diagnostics.checks.length} checks passed`}>
            <strong>{passed}/{diagnostics.checks.length}</strong>
            <span>checks ready</span>
          </div>
        </header>
        <div className="modal-scroll">
          {setupNotice && (
            <div className="notice error">
              <CircleAlert size={16} />
              <span>{setupNotice}</span>
              <button aria-label="Dismiss setup message" onClick={() => setSetupNotice(null)}>
                <X size={15} />
              </button>
            </div>
          )}
          <DiagnosticsPage
            diagnostics={diagnostics}
            settings={settings}
            progress={progress}
            requirementProgress={requirementProgress}
            onScanStart={onScanStart}
            onChanged={onComplete}
            onNotice={(message) => {
              setSetupNotice(message);
              onNotice(message);
            }}
          />
        </div>
        <footer className="setup-wizard-footer">
          <span>
            {ready
              ? "Everything is intact. Finish setup to open Mod Maker."
              : "Resolve every item marked with an × to continue."}
          </span>
          <button
            className="primary"
            disabled={!ready || completing}
            onClick={() => void finishSetup()}
          >
            <ShieldCheck size={16} />
            {completing ? "Saving setup…" : "Finish setup"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function AboutPage({
  updateInfo,
  checkingForUpdates,
  onCheckUpdates,
  onShowUpdate,
  onReplayTutorial,
  onNotice
}: {
  updateInfo: UpdateInfo | null;
  checkingForUpdates: boolean;
  onCheckUpdates: () => void;
  onShowUpdate: () => void;
  onReplayTutorial: () => void;
  onNotice: (message: string | null) => void;
}) {
  const [info, setInfo] = useState<AppInfo | null>(null);

  useEffect(() => {
    void window.studio
      .appInfo()
      .then(setInfo)
      .catch((error) => onNotice(`Could not load build information: ${errorMessage(error)}`));
  }, [onNotice]);

  async function open(kind: "repository" | "profile" | "releases" | "issues") {
    try {
      await window.studio.openExternal(kind);
    } catch (error) {
      onNotice(errorMessage(error));
    }
  }

  return (
    <div className="page-stack about-page">
      <PageHeading
        title={`Deadlock Mod Maker ${info ? `v${info.version}` : ""}`.trim()}
        description="Build details, update checks, and project links."
      />

      <div className="about-grid">
        <section className="card about-build">
          <div className="section-heading">
            <div>
              <h3>Application</h3>
            </div>
            <Info size={21} />
          </div>
          <dl>
            <div><dt>Version</dt><dd>{info?.version ?? "Loading…"}</dd></div>
            <div><dt>Distribution</dt><dd>{info?.portable ? "Portable Windows app" : "Development build"}</dd></div>
            <div><dt>System</dt><dd>{info ? `${info.platform} · ${info.architecture}` : "Loading…"}</dd></div>
            <div><dt>Runtime</dt><dd>{info ? `Electron ${info.electronVersion} · Chromium ${info.chromiumVersion}` : "Loading…"}</dd></div>
            <div><dt>Local data</dt><dd><code>{info?.dataRoot ?? "Loading…"}</code></dd></div>
          </dl>
        </section>

        <section className="card about-update">
          <div className="section-heading">
            <div>
              <h3>Updates</h3>
              <p>Checks the latest published release on GitHub.</p>
            </div>
            <RefreshCw size={21} className={checkingForUpdates ? "spin" : ""} />
          </div>
          <div className="update-state">
            <StatusBadge status={updateInfo?.available ? "missing" : "found"} />
            <div>
              <strong>
                {updateInfo?.available
                  ? `Version ${updateInfo.latestVersion} is available`
                  : updateInfo?.status === "noReleases"
                    ? "No releases published yet"
                    : "This build is current"}
              </strong>
              <span>
                {updateInfo?.publishedAt
                  ? `Published ${new Date(updateInfo.publishedAt).toLocaleDateString()}`
                  : "Update checks never upload project data."}
              </span>
            </div>
          </div>
          <div className="button-row">
            <button className="primary" disabled={checkingForUpdates} onClick={onCheckUpdates}>
              <RefreshCw size={15} /> {checkingForUpdates ? "Checking…" : "Check for updates"}
            </button>
            {updateInfo?.available && (
              <button onClick={onShowUpdate}>
                <Download size={15} /> View update
              </button>
            )}
          </div>
        </section>
      </div>

      <section className="card about-tutorial">
        <div>
          <h3>Sound mod tutorial</h3>
          <p>
            Replay the four-step guide to creating a project, replacing a sound,
            and exporting the finished mod.
          </p>
        </div>
        <button className="primary" onClick={onReplayTutorial}>
          <BookOpen size={16} /> Replay tutorial
        </button>
      </section>

      <section className="card about-links">
        <div>
          <h3>Project & social links</h3>
        </div>
        <div className="button-row">
          <button onClick={() => void open("profile")}><GitFork size={16} /> Nick on GitHub</button>
          <button onClick={() => void open("repository")}><ExternalLink size={16} /> Repository</button>
          <button onClick={() => void open("releases")}><PackageOpen size={16} /> Releases</button>
          <button onClick={() => void open("issues")}><CircleAlert size={16} /> Report an issue</button>
          <button
            onClick={() =>
              void window.studio.openLicenses().catch((error) => onNotice(errorMessage(error)))
            }
          >
            <FileArchive size={16} /> Third-party notices
          </button>
        </div>
      </section>

      {/* The GPL asks that interactive programs carry this notice where users
          can see it; an about box is the form it suggests for a GUI. */}
      <p className="about-licence">
        Deadlock Mod Maker is free software under the GNU General Public License v3 or later, and
        comes with absolutely no warranty. Deadlock is a trademark of Valve Corporation; this tool
        is not affiliated with Valve and bundles no game content.
      </p>
    </div>
  );
}

function UpdatePrompt({
  update,
  progress,
  installing,
  onInstall,
  onLater
}: {
  update: UpdateInfo;
  progress: UpdateProgress | null;
  installing: boolean;
  onInstall: () => void;
  onLater: () => void;
}) {
  const total = progress?.totalBytes || update.assetSize || 1;
  const completed = Math.min(progress?.downloadedBytes ?? 0, total);
  const percent = Math.round((completed / total) * 100);

  return (
    <div className="modal-backdrop update-backdrop">
      <section
        className="modal-shell update-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="update-title"
      >
        <header className="modal-header">
          <div>
            <h2 id="update-title">{update.releaseName ?? `Mod Maker ${update.latestVersion}`}</h2>
            <p>
              You are using {update.currentVersion}. Version {update.latestVersion} is available.
            </p>
          </div>
          {!installing && (
            <button className="icon-button" aria-label="Remind me later" onClick={onLater}>
              <X size={18} />
            </button>
          )}
        </header>
        {update.releaseNotes && <p className="update-notes">{update.releaseNotes.slice(0, 1200)}</p>}
        {installing && (
          <div className="progress-panel" role="status" aria-live="polite">
            <div>
              <strong>{progress?.message ?? "Preparing download…"}</strong>
              <span>{percent}%</span>
            </div>
            <div className="progress-track" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
              <span style={{ width: `${percent}%` }} />
            </div>
          </div>
        )}
        <footer className="modal-actions">
          <button disabled={installing} onClick={onLater}>Later</button>
          <button
            className="primary"
            disabled={installing}
            onClick={
              update.canInstall
                ? onInstall
                : () => void window.studio.openExternal("releases")
            }
          >
            <Download size={16} />
            {installing
              ? "Installing…"
              : update.canInstall
                ? "Download, update & relaunch"
                : "Open release downloads"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function DiagnosticsPage({
  diagnostics,
  settings,
  progress,
  requirementProgress,
  onScanStart,
  onChanged,
  onNotice
}: {
  diagnostics: Diagnostics;
  settings: Settings;
  progress: DiagnosticProgress | null;
  requirementProgress: RequirementProgress | null;
  onScanStart: () => void;
  onChanged: (diagnostics: Diagnostics, settings: Settings) => void;
  onNotice: (message: string | null) => void;
}) {
  const [local, setLocal] = useState<Settings>(settings);
  const [operation, setOperation] = useState<string | null>(null);
  const userSelectedIds = [
    "csdkRoot",
    "source2Viewer",
    "source2ViewerCli",
    "ffmpeg",
    "ffprobe",
    "deadlock"
  ];
  const selectedToolChecks = diagnostics.checks.filter((check) =>
    userSelectedIds.includes(check.id)
  );
  const automaticChecks = diagnostics.checks.filter((check) =>
    !userSelectedIds.includes(check.id)
  );
  const selectedToolsReady = selectedToolChecks.every((check) => check.status === "found");
  const downloadableMissing = selectedToolChecks.filter(
    (check) =>
      check.id !== "csdkRoot" &&
      ["source2Viewer", "source2ViewerCli", "ffmpeg", "ffprobe"].includes(check.id) &&
      check.status !== "found"
  );
  const automaticFound = automaticChecks.filter((check) => check.status === "found").length;
  const installingRequirements = operation === "Installing downloadable requirements…";
  const scanTotal = progress?.total || 7;
  const scanCompleted = operation ? Math.min(progress?.completed ?? 0, scanTotal) : scanTotal;
  const scanPercent = Math.round((scanCompleted / scanTotal) * 100);
  const requirementTotal = requirementProgress?.total || 1;
  const requirementCompleted = Math.min(requirementProgress?.completed ?? 0, requirementTotal);
  const requirementPercent = requirementProgress?.totalBytes
    ? Math.round(
        Math.min(
          1,
          requirementProgress.downloadedBytes / requirementProgress.totalBytes
        ) * 100
      )
    : Math.round((requirementCompleted / requirementTotal) * 100);

  useEffect(() => setLocal(settings), [settings]);

  async function saveSelections(next: Settings) {
    onScanStart();
    setOperation("Scanning the selected tools…");
    try {
      const report = await window.studio.backend<Diagnostics>("settings.save", next);
      setLocal(next);
      onChanged(report, next);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function saveSelection(
    key:
      | "csdkRootOverride"
      | "source2ViewerOverride"
      | "source2ViewerCliOverride"
      | "deadlockRootOverride",
    path: string
  ) {
    await saveSelections({ ...local, [key]: path });
  }

  async function chooseCsdk() {
    const path = await window.studio.selectFolder();
    if (!path) return;
    await saveSelection("csdkRootOverride", path);
  }

  async function chooseSource2Viewer() {
    const path = await window.studio.selectExecutable("source2Viewer");
    if (!path) return;
    await saveSelection("source2ViewerOverride", path);
  }

  async function chooseSource2ViewerCli() {
    try {
      const path = await window.studio.selectExecutable("source2ViewerCli");
      if (!path) return;
      await saveSelection("source2ViewerCliOverride", path);
    } catch (error) {
      onNotice(errorMessage(error));
    }
  }

  async function chooseDeadlock() {
    const path = await window.studio.selectFolder();
    if (!path) return;
    await saveSelection("deadlockRootOverride", path);
  }

  async function chooseFfmpeg() {
    try {
      const selection = await window.studio.selectFfmpeg();
      if (!selection) return;
      await saveSelections({
        ...local,
        ffmpegOverride: selection.ffmpeg,
        ffprobeOverride: selection.ffprobe
      });
    } catch (error) {
      onNotice(errorMessage(error));
    }
  }

  async function openDependency(kind: "ffmpeg" | "source2Viewer", label: string) {
    try {
      await window.studio.openDownload(kind);
      onNotice(`Opened the official ${label} download page.`);
    } catch (error) {
      onNotice(errorMessage(error));
    }
  }

  async function rerun() {
    onScanStart();
    setOperation("Scanning the selected tools…");
    try {
      const report = await window.studio.backend<Diagnostics>("diagnostics.run");
      onChanged(report, local);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  async function installRequirements() {
    onScanStart();
    setOperation("Installing downloadable requirements…");
    try {
      const result = await window.studio.backend<RequirementInstallResult>(
        "requirements.install"
      );
      setLocal(result.settings);
      onChanged(result.diagnostics, result.settings);
      onNotice(null);
    } catch (error) {
      onNotice(errorMessage(error));
    } finally {
      setOperation(null);
    }
  }

  function rowAction(check: Diagnostics["checks"][number]) {
    if (check.id === "csdkRoot") {
      return (
        <button disabled={Boolean(operation)} onClick={() => void chooseCsdk()}>
          <FolderOpen size={14} /> Choose CSDK folder
        </button>
      );
    }
    if (check.id === "source2Viewer") {
      return (
        <button disabled={Boolean(operation)} onClick={() => void chooseSource2Viewer()}>
          <FolderOpen size={14} /> Choose viewer file
        </button>
      );
    }
    if (check.id === "source2ViewerCli") {
      return (
        <div className="dependency-actions">
          <button disabled={Boolean(operation)} onClick={() => void chooseSource2ViewerCli()}>
            <FolderOpen size={14} /> Choose CLI
          </button>
          {check.status !== "found" && (
            <button onClick={() => void openDependency("source2Viewer", "Source 2 Viewer")}>
              <Download size={14} /> Download page
            </button>
          )}
        </div>
      );
    }
    if (
      check.id === "ffmpeg" ||
      (check.id === "ffprobe" && check.status !== "found")
    ) {
      return (
        <div className="dependency-actions">
          <button disabled={Boolean(operation)} onClick={() => void chooseFfmpeg()}>
            <FolderOpen size={14} /> Choose FFmpeg
          </button>
          {check.status !== "found" && (
            <button onClick={() => void openDependency("ffmpeg", "FFmpeg")}>
              <Download size={14} /> Download page
            </button>
          )}
        </div>
      );
    }
    if (check.id === "deadlock") {
      return (
        <button disabled={Boolean(operation)} onClick={() => void chooseDeadlock()}>
          <FolderOpen size={14} /> Choose Deadlock folder
        </button>
      );
    }
    return null;
  }

  return (
    <div className="page-stack diagnostics-page">
      <PageHeading
        title={diagnostics.canBuild ? "All tools found" : "Setup checklist"}
        description="Choose the external tool and game locations below. CSDK components and the game archive are checked automatically, and nothing from the selected folders is copied."
        actions={
          <>
            <button disabled={Boolean(operation)} onClick={() => void rerun()}>
              <RefreshCw size={15} /> Scan again
            </button>
            <button
              className="primary"
              disabled={Boolean(operation) || downloadableMissing.length === 0}
              onClick={() => void installRequirements()}
            >
              <Download size={15} /> Download all requirements
            </button>
          </>
        }
      />

      {operation && (
        <section className="diagnostic-progress" role="status" aria-live="polite">
          <div>
            <strong>
              {installingRequirements
                ? requirementProgress?.message ?? operation
                : progress?.message ?? operation}
            </strong>
            <span>
              {installingRequirements && requirementProgress?.totalBytes
                ? `${formatBytes(requirementProgress.downloadedBytes)} / ${formatBytes(requirementProgress.totalBytes)}`
                : installingRequirements
                  ? `${requirementCompleted}/${requirementTotal}`
                  : `${scanCompleted}/${scanTotal}`}
            </span>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-label={installingRequirements ? "Requirements download progress" : "Diagnostics scan progress"}
            aria-valuemin={0}
            aria-valuemax={installingRequirements ? 100 : scanTotal}
            aria-valuenow={installingRequirements ? requirementPercent : scanCompleted}
          >
            <span style={{ width: `${installingRequirements ? requirementPercent : scanPercent}%` }} />
          </div>
        </section>
      )}

      <section className="diagnostic-selections">
        <header>
          <div>
            <h3>Selected tools</h3>
            <p>
              Choose tools manually or download the missing Source 2 Viewer and FFmpeg files.
              CSDK and Deadlock remain user-selected and are never copied.
            </p>
          </div>
          <StatusBadge status={selectedToolsReady ? "found" : "missing"} />
        </header>
        {selectedToolChecks.map((check) => (
          <div className="diagnostic-row" key={check.id}>
            <StatusBadge status={check.status} />
            <div className="diagnostic-copy">
              <strong>{check.label}</strong>
              <p>{check.detail}</p>
              {check.path && <code title={check.path}>{check.path}</code>}
              {check.version && <small>Version {check.version}</small>}
            </div>
            <div className="diagnostic-action">{rowAction(check)}</div>
          </div>
        ))}
      </section>

      <section className="diagnostic-checklist">
        <header>
          <div>
            <h3>Automatically discovered requirements</h3>
            <p>{automaticFound} of {automaticChecks.length} checks passed</p>
          </div>
          <StatusBadge
            status={automaticFound === automaticChecks.length ? "found" : "missing"}
          />
        </header>
        {automaticChecks.map((check) => (
          <div className="diagnostic-row" key={check.id}>
            <StatusBadge status={check.status} />
            <div className="diagnostic-copy">
              <strong>{check.label}</strong>
              <p>{check.detail}</p>
              {check.path && <code title={check.path}>{check.path}</code>}
              {check.version && <small>Version {check.version}</small>}
            </div>
            <div className="diagnostic-action">{rowAction(check)}</div>
          </div>
        ))}
      </section>

      <details className="portable-paths">
        <summary>Application-owned folders</summary>
        <div>
          {Object.entries(diagnostics.portablePaths).map(([label, value]) => (
            <p key={label}><span>{label}</span><code>{value}</code></p>
          ))}
        </div>
      </details>
    </div>
  );
}

export default App;
